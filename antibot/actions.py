"""
Shared action pipeline for the antibot cog.

Every detector funnels into ``take_action``: one place that enforces immunity,
debounces duplicate punishment, dispatches the configured action
(ban/kick/timeout/role), deletes offending messages, writes a modlog case, and
posts an alert embed. Detectors never call discord mod APIs directly.
"""

from datetime import timedelta
from typing import Dict, List, Optional, Tuple

import discord
from redbot.core import modlog
from redbot.core.utils.chat_formatting import humanize_timedelta

__all__ = ["take_action", "report", "CASE_LABELS"]

# Human labels for each antibot casetype (embed titles + modlog case_str).
CASE_LABELS = {
    "antibot_spam": "Cross-channel spam",
    "antibot_join": "Suspicious join",
    "antibot_roleping": "Role-ping abuse",
    "antibot_spammer": "Suspected spammer (Discord flag)",
    "antibot_honeypot": "Honeypot trip",
    "antibot_signature": "Signature match",
    "antibot_dm": "Unusual DM activity",
}

_PUNITIVE = {"timeout", "kick", "ban", "role"}
_ACTION_DEBOUNCE = 5.0  # seconds; stop two detectors double-punishing one event
_TIMEOUT_MAX = 28 * 86400  # discord hard cap
_BAN_DELETE_SECONDS = 3600  # purge last hour of the banned user's messages


def _humanize_days(seconds: float) -> str:
    """Humanized duration rounded to whole days, for the age / tenure fields in
    alerts so they read `3 days` instead of `2 days, 21 hours, 4 minutes`."""
    days = round((seconds or 0) / 86400)
    if days <= 0:
        return "less than a day"
    return humanize_timedelta(seconds=days * 86400)


def _member_detail_fields(member, action_cfg, action):
    """(name, value) pairs describing the acted-on member. Shared by the alert embed
    and the modlog reason so both carry the same context: timeout length, account age
    and creation date, time in server and join date."""
    fields = []
    if action == "timeout" and action_cfg:
        secs = min(int(action_cfg.get("timeout_seconds", 3600)), _TIMEOUT_MAX)
        fields.append(("Duration", humanize_timedelta(seconds=secs) or f"{secs}s"))
    now = discord.utils.utcnow()
    fields.append(("Account age", _humanize_days((now - member.created_at).total_seconds())))
    fields.append(("Account created", discord.utils.format_dt(member.created_at, "D")))
    joined = member.joined_at
    if joined:
        fields.append(("In server", _humanize_days((now - joined).total_seconds())))
        fields.append(("Joined server", discord.utils.format_dt(joined, "D")))
    return fields


async def take_action(
    cog,
    guild: discord.Guild,
    member: discord.Member,
    action_cfg: Dict,
    reason: str,
    case_type: str,
    *,
    evidence: Optional[Dict] = None,
    extra_fields: Optional[Dict[str, str]] = None,
) -> bool:
    """Run the configured action against ``member``. Returns True on success."""
    action = (action_cfg or {}).get("action", "none")

    # 1) immunity re-check (defense in depth)
    if cog.is_immune(member):
        return False

    # 2) debounce: skip if we just actioned this member moments ago
    now = discord.utils.utcnow().timestamp()
    last = await cog.config.member(member).last_action_ts()
    if action in _PUNITIVE and last and (now - last) < _ACTION_DEBOUNCE:
        return False

    # 3) best-effort DM before acting. Ban uses a configurable custom message
    # (no DM unless one is set); the other actions use the generic notice.
    if action in _PUNITIVE and action_cfg.get("dm", True):
        if action == "ban":
            await _safe_ban_dm(cog, guild, member, reason)
        else:
            await _safe_dm(member, guild, action, reason)

    # 4) dispatch. failed_reason stays None on success; a set value flows to the
    # alert (ACTION FAILED) and owner ping below without aborting the pipeline.
    failed_reason = None
    if action in _PUNITIVE:
        _, failed_reason = await _dispatch(cog, guild, member, action, action_cfg, reason)

    # 5) delete offending messages (any action, if configured)
    if action_cfg.get("delete_messages", True) and evidence and evidence.get("messages"):
        await _delete_messages(guild, evidence["messages"], reason)

    # 6) modlog case for any real trip (log/notify or punitive), honoring the
    # detector's modlog toggle. Skipped for "none" and when a punitive dispatch failed
    # (failed_reason is only ever set on punitive actions, None for log/notify). The
    # case reason carries the same detail the alert embed shows (age, dates, signals).
    if action != "none" and action_cfg.get("modlog", True) and failed_reason is None:
        details = _member_detail_fields(member, action_cfg, action)
        details += [(str(k), str(v)) for k, v in (extra_fields or {}).items()]
        # Bold each label and code-format plain values; leave <t:…> timestamps raw so
        # they still render as dates in the case embed.
        lines = [f"**{n}:** {v if v.startswith('<t:') else f'`{v}`'}" for n, v in details]
        full_reason = reason + ("\n" + "\n".join(lines) if lines else "")
        try:
            await modlog.create_case(
                cog.bot,
                guild,
                discord.utils.utcnow(),
                case_type,
                member,
                moderator=guild.me,
                reason=full_reason[:2000],
            )
        except Exception:
            pass

    # 7) alert embed to the notify channel / role
    await _send_alert(
        cog,
        guild,
        member,
        case_type,
        action,
        reason,
        action_cfg=action_cfg,
        extra_fields=extra_fields,
        failed_reason=failed_reason,
    )

    # 8) owner ping on permission failure
    if failed_reason is not None:
        try:
            await guild.owner.send(
                f":warning: AntiBot could not `{action}` {member} in **{guild}** "
                f"({failed_reason}). Please check my permissions and role position."
            )
        except Exception:
            pass

    # 9) bookkeeping: only punitive actions arm the debounce window, so a
    # non-punitive notify/log can never suppress a later real action.
    if action in _PUNITIVE:
        await cog.config.member(member).last_action_ts.set(now)

    return failed_reason is None and action in _PUNITIVE


async def report(
    cog,
    guild: discord.Guild,
    member: discord.Member,
    case_type: str,
    reason: str,
    *,
    extra_fields: Optional[Dict[str, str]] = None,
) -> None:
    """Notify-only path (no punishment, no modlog), e.g. honeypot exempt member."""
    await _send_alert(cog, guild, member, case_type, "notify", reason, extra_fields=extra_fields)


# --- internals ------------------------------------------------------------ #
async def _dispatch(cog, guild, member, action, action_cfg, reason) -> Tuple[bool, Optional[str]]:
    try:
        if action == "timeout":
            secs = min(int(action_cfg.get("timeout_seconds", 3600)), _TIMEOUT_MAX)
            await member.timeout(timedelta(seconds=secs), reason=reason)
        elif action == "kick":
            await guild.kick(member, reason=reason)
        elif action == "ban":
            delete_secs = _BAN_DELETE_SECONDS if action_cfg.get("delete_messages", True) else 0
            await guild.ban(member, reason=reason, delete_message_seconds=delete_secs)
            # Auto-learn is best-effort and runs after the ban already succeeded, so a
            # failure here must never make the ban look failed.
            if await cog.config.guild(guild).auto_learn_on_ban():
                try:
                    await cog.capture_signature(member, trust="auto", label=f"auto: {reason[:60]}")
                except Exception:  # noqa: BLE001
                    pass
        elif action == "role":
            return await _apply_role(cog, guild, member, reason)
        return True, None
    except discord.Forbidden:
        return False, "forbidden"
    except discord.HTTPException as e:
        return False, f"http {getattr(e, 'status', '?')}"


async def _apply_role(cog, guild, member, reason) -> Tuple[bool, Optional[str]]:
    role_id = await cog.config.guild(guild).quarantine_role()
    role = guild.get_role(role_id) if role_id else None
    if role is None:
        return False, "role not set/deleted"
    me = guild.me
    if role >= me.top_role or not me.guild_permissions.manage_roles:
        return False, "role hierarchy"
    if role in member.roles:
        return True, None
    try:
        # single atomic edit (rolemanagement.update_roles_atomically pattern)
        await member.edit(roles=[*member.roles, role], reason=reason)
        return True, None
    except discord.Forbidden:
        return False, "forbidden"
    except discord.HTTPException as e:
        return False, f"http {getattr(e, 'status', '?')}"


async def _delete_messages(guild, messages: List[Tuple[int, int]], reason: str) -> None:
    """Bulk-delete evidence messages, grouped per channel. Best-effort."""
    by_channel: Dict[int, List[int]] = {}
    for chan_id, msg_id in messages:
        if msg_id:
            by_channel.setdefault(chan_id, []).append(msg_id)
    for chan_id, ids in by_channel.items():
        channel = guild.get_channel_or_thread(chan_id)
        if channel is None or not hasattr(channel, "delete_messages"):
            continue
        partials = [channel.get_partial_message(i) for i in dict.fromkeys(ids)]
        try:
            if len(partials) == 1:
                await partials[0].delete()
            else:
                # delete_messages caps at 100 and refuses >14d-old messages
                await channel.delete_messages(partials[:100], reason=reason)
        except (discord.Forbidden, discord.HTTPException, discord.NotFound):
            # fall back to individual best-effort deletes
            for pm in partials:
                try:
                    await pm.delete()
                except (discord.Forbidden, discord.HTTPException, discord.NotFound):
                    pass


async def _safe_dm(member, guild, action, reason) -> None:
    verb = {"timeout": "timed out in", "kick": "kicked from", "ban": "banned from", "role": "restricted in"}.get(
        action, "actioned in"
    )
    try:
        await member.send(f"You have been {verb} **{guild}** by automated moderation.\nReason: {reason}")
    except Exception:
        pass


async def _safe_ban_dm(cog, guild, member, reason) -> None:
    """DM a configurable ban message before banning. No DM if none is set (default).
    Supports {guild} / {member} / {reason} placeholders (moreadmin `bandm` style)."""
    template = await cog.config.guild(guild).ban_dm_message()
    if not template:
        return
    try:
        text = template.format(guild=guild.name, member=member.name, reason=reason or "")
    except (KeyError, IndexError, ValueError):
        text = template  # bad placeholder in the template -> send it verbatim
    try:
        await member.send(text[:2000])  # Discord DM content cap
    except Exception:
        pass


async def _send_alert(
    cog, guild, member, case_type, action, reason, *, action_cfg=None, extra_fields=None, failed_reason=None
) -> None:
    chan_id = await cog.config.guild(guild).notify_channel()
    channel = guild.get_channel_or_thread(chan_id) if chan_id else None
    if channel is None:
        return

    label = CASE_LABELS.get(case_type, case_type)
    colour = discord.Colour.red() if action in _PUNITIVE else discord.Colour.orange()
    # Clip against Discord's embed limits so an oversized reason/label can't fail the send.
    embed = discord.Embed(title=f"AntiBot: {label}"[:256], colour=colour, description=reason[:4096])
    embed.add_field(name="Action", value=action)
    for fname, fvalue in _member_detail_fields(member, action_cfg, action):
        embed.add_field(name=fname, value=fvalue)
    for name, value in (extra_fields or {}).items():
        embed.add_field(name=str(name)[:256], value=str(value)[:1024])
    if failed_reason:
        embed.add_field(name=":x: ACTION FAILED", value=str(failed_reason)[:1024], inline=False)
    embed.set_footer(text=f"User ID: {member.id}")
    avatar = member.display_avatar
    embed.set_author(name=str(member), url=avatar.url)
    embed.set_thumbnail(url=avatar.url)

    role_id = await cog.config.guild(guild).notify_role()
    role = guild.get_role(role_id) if role_id else None
    content = role.mention if role else None
    allowed = discord.AllowedMentions(roles=[role] if role else False, everyone=False, users=False)
    try:
        await channel.send(content=content, embed=embed, allowed_mentions=allowed)
    except (discord.Forbidden, discord.HTTPException):
        pass
