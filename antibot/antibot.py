"""
AntiBot - automated anti-bot / anti-raid moderation for Red.

Six detectors funnel into one shared action pipeline (see actions.py):
  * cross-channel spam (same message across many channels)
  * suspicious joins (account age gate)
  * role-ping abuse (with temporary role lockdown)
  * Discord's suspected-spammer badge (join + post-join)
  * honeypot channels (with time-in-server / role safeguards)
  * learned bot "signatures" (human-in-the-loop, weighted matching)

Pure logic lives in simhash.py / signatures.py / detectors.py (unit-tested);
this module is the discord/redbot wiring: config, listeners, and commands.
"""

import asyncio
import time
from collections import deque
from typing import Dict, Union

import discord
from redbot.core import Config, checks, commands, modlog
from redbot.core.commands.converter import parse_timedelta
from redbot.core.utils.chat_formatting import humanize_timedelta

from . import actions, detectors, signatures

LOG = "[antibot] {}"
_ROLEPING_NOTICE = "\N{SHIELD} That {role} ping was from a bot and has been handled, you can safely ignore it."
_ACTIONS = ("none", "log", "notify", "timeout", "kick", "ban", "role")
_DETECTORS = ("spam", "join", "roleping", "spammer", "honeypot", "dmflag")
_PUNITIVE = ("timeout", "kick", "ban", "role")
_SIG_STORE_CAP = 200
_MIN_FUZZY_LEN = 12  # normalized-text length below which SimHash near-dup is disabled

_CASETYPES = [
    {"name": "antibot_spam", "default_setting": True, "image": "\N{FIRE}", "case_str": "AntiBot: Cross-channel spam"},
    {"name": "antibot_join", "default_setting": True, "image": "\N{BUST IN SILHOUETTE}", "case_str": "AntiBot: Suspicious join"},
    {"name": "antibot_roleping", "default_setting": True, "image": "\N{BELL}", "case_str": "AntiBot: Role-ping abuse"},
    {"name": "antibot_spammer", "default_setting": True, "image": "\N{WARNING SIGN}", "case_str": "AntiBot: Suspected spammer"},
    {"name": "antibot_honeypot", "default_setting": True, "image": "\N{HONEY POT}", "case_str": "AntiBot: Honeypot trip"},
    {"name": "antibot_signature", "default_setting": True, "image": "\N{ROBOT FACE}", "case_str": "AntiBot: Signature match"},
    {"name": "antibot_dm", "default_setting": True, "image": "\N{ENVELOPE}", "case_str": "AntiBot: Unusual DM activity"},
]


def _action_cfg(action: str = "notify", **kw) -> Dict:
    cfg = {
        "action": action,
        "timeout_seconds": 3600,
        "dm": True,
        "modlog": True,
        "delete_messages": True,
    }
    cfg.update(kw)
    return cfg


class AntiBot(commands.Cog):
    """Automated anti-bot / anti-raid protection."""

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=0xA471B07, force_registration=True)

        self.default_guild = {
            "enabled": True,
            "notify_channel": None,
            "notify_role": None,
            "quarantine_role": None,
            "whitelist_roles": [],
            "whitelist_channels": [],
            "auto_learn_on_ban": True,
            "ban_dm_message": None,  # custom DM before a ban action (None = no DM)
            "locked_roles": {},  # role_id(str) -> unlock unix-ts
            "spam": {
                "enabled": True, "channels": 3, "window": 10, "simhash_distance": 8,
                "cooldown": 60, "action": _action_cfg("timeout"),
            },
            "join": {
                "enabled": True, "age_new_seconds": 604800, "age_kick_seconds": 0,
                "action": _action_cfg("notify"),
            },
            "spammer": {
                "enabled": True, "check_on_message": True, "action": _action_cfg("notify"),
            },
            "honeypot": {
                "enabled": False, "channels": [], "exempt_after_seconds": 604800,
                "exempt_roles": [], "report_exempt": True,
                "report_immune": False,  # also report (never action) immune posters
                "action": _action_cfg("notify"),
            },
            "roleping": {
                "enabled": True, "watched_roles": [], "threshold": 2, "window": 10,
                "lockdown": True, "lockdown_seconds": 300,
                # new-member gate: active iff either window > 0. A member is "new"
                # (and thus actionable) if within the account-age OR the joined window.
                "new_account_seconds": 0,        # account age (created) counted as "new"
                "new_member_seconds": 0,          # joined-server-more-recently-than counted as "new"
                "min_role_members": 0,            # only act on pings of roles with >= this many members
                "notice_message": _ROLEPING_NOTICE,  # public "it was a bot" notice (blank = off)
                "action": _action_cfg("timeout"),
            },
            "signatures": {
                "enabled": True, "simhash_distance": 8,
                "weights": dict(signatures.DEFAULT_WEIGHTS),
                # Non-destructive defaults so a fresh install never auto-kicks/bans while
                # being configured. Strongest default is `role` (reversible quarantine).
                "tiers": [
                    {"min": 0.90, "action": _action_cfg("role")},
                    {"min": 0.70, "action": _action_cfg("notify")},
                    {"min": 0.50, "action": _action_cfg("log")},
                ],
            },
            "dmflag": {
                # Unusual-DM detector: a new / just-joined account DMing the bot itself.
                # Discord hides its own "unusual DM activity" flag from bots, so this is
                # the observable proxy. Off by default (DMs are lower-evidence); notify
                # default. Either-window gate (see detectors.dm_new_actionable).
                "enabled": False,
                "new_account_seconds": 604800,   # account younger than this -> "new"
                "new_member_seconds": 86400,      # joined more recently than this -> "new"
                "min_messages": 1,                # DMs to the bot before it fires
                "ignore_commands": True,          # skip DMs that are bot command invocations
                "action": _action_cfg("notify"),
            },
            "signature_store": [],
        }
        default_member = {"last_action_ts": 0.0}  # debounce timestamp only
        self.config.register_guild(**self.default_guild)
        self.config.register_member(**default_member)

        # in-memory detector state (rebuilt on load)
        self.cross = detectors.CrossChannelDetector()
        self.roleping = detectors.RolePingDetector()
        self._recent_roles: Dict = {}  # (guild_id, user_id) -> set[role_id]
        self._recent_texts: Dict = {}  # (guild_id, user_id) -> deque[str] (for sig learn)
        self._dm_counts: Dict = {}  # (guild_id, user_id) -> count of DMs to the bot
        self._restore_tasks: set = set()  # pending precise role-unlock tasks

        self._task = asyncio.create_task(self._bg_loop())

    async def initialize(self):
        try:
            await modlog.register_casetypes(_CASETYPES)
        except RuntimeError:
            pass

    def cog_unload(self):
        self._task.cancel()
        for t in self._restore_tasks:
            t.cancel()

    # --- helpers ---------------------------------------------------------- #
    def is_immune(self, member) -> bool:
        """Static immunity (bot / owner / admin / bot-owner). Whitelist roles
        are guild-config and checked separately in the listeners."""
        if not isinstance(member, discord.Member):
            return False
        if member.bot or member == member.guild.owner:
            return True
        if member.guild_permissions.administrator:
            return True
        if member.id in (self.bot.owner_ids or set()):
            return True
        return False

    def _whitelisted(self, member, conf) -> bool:
        wl = conf.get("whitelist_roles", [])
        return bool(wl) and any(r.id in wl for r in member.roles)

    def _member_verified(self, member, conf) -> bool:
        """Bound the per-message signature/spammer scans to newer accounts."""
        age = (discord.utils.utcnow() - member.created_at).total_seconds()
        return age >= conf.get("join", {}).get("age_new_seconds", 604800)

    async def _store_add(self, guild, sig):
        async with self.config.guild(guild).signature_store() as store:
            store.append(sig)
            if len(store) > _SIG_STORE_CAP:
                del store[0 : len(store) - _SIG_STORE_CAP]

    async def capture_signature(self, member, *, trust="confirmed", label="", created_by=0, message_texts=None):
        guild = member.guild
        if message_texts is None:  # default to cached recent messages (across channels)
            message_texts = list(self._recent_texts.get((guild.id, member.id), []))
        recent = self._recent_roles.get((guild.id, member.id))
        sig = signatures.build_signature(
            member, label=label, created_by=created_by, trust=trust,
            message_texts=message_texts, recent_roles=recent,
        )
        await self._store_add(guild, sig)
        return sig

    # --- background loop -------------------------------------------------- #
    async def _bg_loop(self):
        await self.bot.wait_until_ready()
        while not self.bot.is_closed():
            try:
                await self._restore_locked_roles()
                now = time.time()
                self.cross.sweep(now, 3600)
                self.roleping.sweep(now, 3600)
                if len(self._recent_roles) > 10000:  # bound the role-grab cache
                    self._recent_roles.clear()
                if len(self._recent_texts) > 10000:  # bound the message-text cache
                    self._recent_texts.clear()
                if len(self._dm_counts) > 10000:  # bound the DM-to-bot counter
                    self._dm_counts.clear()
            except asyncio.CancelledError:
                break
            except Exception as e:  # noqa: BLE001
                print(LOG.format(f"bg loop error: {e}"))
                await asyncio.sleep(10)
            await asyncio.sleep(15)

    async def _restore_locked_roles(self):
        now = time.time()
        for guild in self.bot.guilds:
            locked = await self.config.guild(guild).locked_roles()
            if not locked:
                continue
            expired = [rid for rid, ts in locked.items() if now >= ts]
            for rid in expired:
                role = guild.get_role(int(rid))
                if role is not None and not role.mentionable:
                    try:
                        await role.edit(mentionable=True, reason="AntiBot: lockdown expired")
                    except (discord.Forbidden, discord.HTTPException):
                        pass
            if expired:
                async with self.config.guild(guild).locked_roles() as lk:
                    for rid in expired:
                        lk.pop(rid, None)

    async def _lock_role(self, guild, role, seconds):
        me = guild.me
        if role >= me.top_role or not me.guild_permissions.manage_roles or not role.mentionable:
            return
        try:
            await role.edit(mentionable=False, reason="AntiBot: role-ping abuse lockdown")
        except (discord.Forbidden, discord.HTTPException):
            return
        async with self.config.guild(guild).locked_roles() as locked:
            locked[str(role.id)] = time.time() + seconds
        # precise restore (the bg loop is only a restart backstop)
        task = asyncio.create_task(self._schedule_restore(guild.id, role.id, seconds))
        self._restore_tasks.add(task)
        task.add_done_callback(self._restore_tasks.discard)

    async def _schedule_restore(self, guild_id, role_id, seconds):
        try:
            await asyncio.sleep(seconds)
        except asyncio.CancelledError:
            return
        guild = self.bot.get_guild(guild_id)
        if guild is None:
            return
        # respect a manual re-lock: only restore if still due (not pushed out)
        locked = await self.config.guild(guild).locked_roles()
        due = locked.get(str(role_id))
        if due is not None and due > time.time() + 5:
            return  # a later lock extended it; that lock owns the restore
        role = guild.get_role(role_id)
        if role is not None and not role.mentionable:
            try:
                await role.edit(mentionable=True, reason="AntiBot: lockdown expired")
            except (discord.Forbidden, discord.HTTPException):
                pass
        async with self.config.guild(guild).locked_roles() as lk:
            lk.pop(str(role_id), None)

    # --- listeners -------------------------------------------------------- #
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return
        if message.guild is None:
            # DM to the bot: the only DM signal a bot can observe (Discord hides its
            # own "unusual DM activity" flag from the API).
            await self._handle_bot_dm(message)
            return
        guild = message.guild
        if await self.bot.cog_disabled_in_guild(self, guild):
            return
        conf = await self.config.guild(guild).all()
        if not conf.get("enabled", True):
            return
        member = message.author
        if not isinstance(member, discord.Member):
            member = guild.get_member(member.id)
            if member is None:
                return  # uncached/left author: can't evaluate roles, immunity, or age
        immune = self.is_immune(member) or self._whitelisted(member, conf)

        # Honeypot first: ANY post in a trap channel trips, even a command-like one
        # (and this avoids the get_context cost for trap messages). Immune members
        # (owner/admin/bot-owner/whitelisted) are normally skipped, but if
        # report_immune is on they get a report (never an action). Bots already gone.
        hp = conf.get("honeypot", {})
        if hp.get("enabled") and message.channel.id in hp.get("channels", []):
            if not immune or hp.get("report_immune", False):
                await self._handle_honeypot(message, member, hp, immune=immune)
            return

        if immune:
            return

        now = time.time()

        # Skip valid command invocations for the remaining content detectors.
        ctx = await self.bot.get_context(message)
        if ctx.valid:
            return

        if message.channel.id in conf.get("whitelist_channels", []):
            return

        # Discord suspected-spammer badge, on message
        sp = conf.get("spammer", {})
        if sp.get("enabled") and sp.get("check_on_message", True):
            if getattr(message.author.public_flags, "spammer", False) and not self._member_verified(member, conf):
                await actions.take_action(self, guild, member, sp["action"],
                                          "Discord suspected-spammer flag", "antibot_spammer")
                return

        # role-ping abuse
        rp = conf.get("roleping", {})
        if rp.get("enabled"):
            if await self._handle_roleping(message, member, rp, now, conf):
                return

        # Content key for cross-channel spam: the message text, or for image/file
        # posts with no text, an attachment fingerprint (filename + size) so the SAME
        # image reposted across channels still clusters. Bots spam identical images in
        # voice-channel text chats, which carry no text for a text-only detector.
        norm = _normalize(message.content)
        if norm:
            content_key = norm
            # 0 = "no fuzzy" for very short text, so unrelated short posts only cluster
            # on an exact hash match (avoids SimHash false positives on tiny messages).
            sh = _simhash(norm) if len(norm) >= _MIN_FUZZY_LEN else 0
            # cache real text per user across channels (for sig learn / auto-learn)
            self._recent_texts.setdefault((guild.id, member.id), deque(maxlen=10)).append(message.content)
        elif message.attachments:
            content_key = "att:" + "|".join(sorted(f"{a.filename}:{a.size}" for a in message.attachments))
            sh = 0  # exact-only: identical file bytes -> identical size -> same key
        else:
            return

        sc = conf.get("spam", {})
        if sc.get("enabled"):
            tripped, evidence = self.cross.record(
                guild.id, member.id, message.channel.id, message.id, _norm_hash(content_key), sh, now,
                channels=sc["channels"], window=sc["window"],
                simhash_distance=sc["simhash_distance"], cooldown=sc["cooldown"],
            )
            if tripped:
                await actions.take_action(
                    self, guild, member, sc["action"],
                    f"Posted the same content across {sc['channels']}+ channels quickly",
                    "antibot_spam", evidence=evidence,
                )
                return

        sig = conf.get("signatures", {})
        if sig.get("enabled") and not self._member_verified(member, conf):
            feats = signatures.extract_message_features(
                member, message.content,
                recent_roles=self._recent_roles.get((guild.id, member.id)),
            )
            await self._match_signature(guild, member, feats, sig)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        guild = member.guild
        if await self.bot.cog_disabled_in_guild(self, guild):
            return
        conf = await self.config.guild(guild).all()
        if not conf.get("enabled", True) or self.is_immune(member):
            return

        jc = conf.get("join", {})

        sp = conf.get("spammer", {})
        if sp.get("enabled") and getattr(member.public_flags, "spammer", False):
            await actions.take_action(self, guild, member, sp["action"],
                                      "Discord suspected-spammer flag (join)", "antibot_spammer")
            return

        age = (discord.utils.utcnow() - member.created_at).total_seconds()
        if jc.get("enabled"):
            akick = jc.get("age_kick_seconds", 0)
            if akick and age < akick:
                await actions.take_action(
                    self, guild, member, jc["action"],
                    f"Account age {humanize_timedelta(seconds=int(age))} is below the "
                    f"{humanize_timedelta(seconds=akick)} threshold", "antibot_join",
                )
                return

        sig = conf.get("signatures", {})
        if sig.get("enabled"):
            feats = signatures.extract_member_features(member)
            await self._match_signature(guild, member, feats, sig)

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        if await self.bot.cog_disabled_in_guild(self, after.guild):
            return
        added = set(after.roles) - set(before.roles)
        if added:
            key = (after.guild.id, after.id)
            existing = self._recent_roles.get(key, set())
            self._recent_roles[key] = existing | {r.id for r in added if not r.is_default()}

    @commands.Cog.listener()
    async def on_user_update(self, before: discord.User, after: discord.User):
        # Only the spammer badge turning ON is interesting (verified: public_flags
        # is part of Member._update_inner_user's diff, so this dispatches on change).
        if before.public_flags.spammer or not after.public_flags.spammer:
            return
        for guild in self.bot.guilds:
            member = guild.get_member(after.id)
            if member is None or await self.bot.cog_disabled_in_guild(self, guild):
                continue
            conf = await self.config.guild(guild).all()
            if not conf.get("enabled", True):
                continue
            sp = conf.get("spammer", {})
            if not sp.get("enabled") or self.is_immune(member) or self._whitelisted(member, conf):
                continue
            await actions.take_action(self, guild, member, sp["action"],
                                      "Discord suspected-spammer flag (post-join)", "antibot_spammer")

    # --- detector handlers ------------------------------------------------ #
    async def _handle_bot_dm(self, message):
        """A member DM'd the bot. Act in the first mutual guild where the unusual-DM
        detector is enabled and the sender passes the new-account/new-member gate. The
        per-member debounce in take_action stops a second guild from double-punishing."""
        author = message.author
        for guild in self.bot.guilds:
            member = guild.get_member(author.id)
            if member is None:
                continue  # not a member here: can't evaluate age/immunity or act
            if await self.bot.cog_disabled_in_guild(self, guild):
                continue
            conf = await self.config.guild(guild).all()
            if not conf.get("enabled", True):
                continue
            dm = conf.get("dmflag", {})
            if not dm.get("enabled"):
                continue
            if self.is_immune(member) or self._whitelisted(member, conf):
                continue
            if dm.get("ignore_commands", True) and await self._is_bot_command(message):
                continue
            now = discord.utils.utcnow()
            account_age = (now - member.created_at).total_seconds()
            member_age = (now - member.joined_at).total_seconds() if member.joined_at else None
            if not detectors.dm_new_actionable(
                account_age, member_age,
                dm.get("new_account_seconds", 0), dm.get("new_member_seconds", 0),
            ):
                continue
            # Count only non-command DMs; fire once the threshold is reached.
            key = (guild.id, author.id)
            count = self._dm_counts.get(key, 0) + 1
            self._dm_counts[key] = count
            if count < max(1, dm.get("min_messages", 1)):
                continue
            # Strip backticks/newlines so the snippet stays on one tidy line in both the
            # alert embed and the code-formatted modlog reason.
            snippet = (message.content or "").replace("`", "'").replace("\n", " ").strip()
            atts = message.attachments
            await actions.take_action(
                self, guild, member, dm["action"],
                "New/just-joined member DM'd the bot", "antibot_dm",
                extra_fields={
                    "Via": "DM to bot",
                    "Message": snippet[:300] if snippet else "(no text)",
                    "Attachments": (f"{len(atts)}: " + ", ".join(a.filename for a in atts))[:300]
                    if atts else "none",
                },
            )
            return

    async def _is_bot_command(self, message) -> bool:
        """True if the DM starts with one of the bot's command prefixes (legit new
        users often DM `help`), so those don't trip the unusual-DM detector."""
        try:
            prefixes = await self.bot.get_prefix(message)
        except Exception:  # noqa: BLE001
            return False
        if isinstance(prefixes, str):
            prefixes = [prefixes]
        content = message.content or ""
        return any(content.startswith(p) for p in prefixes if p)

    async def _handle_honeypot(self, message, member, hp, *, immune=False):
        guild = message.guild
        if immune:
            # Only reached when report_immune is on. Never action a trusted account;
            # just flag that it tripped the honeypot (compromised-staff tripwire).
            await actions.report(self, guild, member, "antibot_honeypot",
                                 f"Immune member posted in honeypot <#{message.channel.id}> (no action)",
                                 extra_fields={"Trigger": "immune"})
            return
        has_exempt = any(r.id in hp.get("exempt_roles", []) for r in member.roles)
        joined = member.joined_at
        joined_seconds = (discord.utils.utcnow() - joined).total_seconds() if joined else None
        decision = detectors.honeypot_decision(
            has_exempt_role=has_exempt,
            joined_seconds=joined_seconds, exempt_after=hp.get("exempt_after_seconds", 604800),
        )
        if decision == "report":
            if hp.get("report_exempt", True):
                # Mirror honeypot_decision's precedence: role first, then join data.
                if has_exempt:
                    trigger = "exempt role"
                elif joined_seconds is None:
                    trigger = "no join data"
                else:
                    trigger = "age (time in server)"
                await actions.report(self, guild, member, "antibot_honeypot",
                                     f"Exempt member posted in honeypot <#{message.channel.id}> (no action)",
                                     extra_fields={"Trigger": trigger})
            return
        await actions.take_action(
            self, guild, member, hp["action"],
            f"Posted in honeypot channel <#{message.channel.id}>", "antibot_honeypot",
            evidence={"messages": [(message.channel.id, message.id)]},
        )

    def _roleping_gated_out(self, member, rp) -> bool:
        """True if the new-account/new-member gate should skip this member.

        The gate is active iff at least one window (`new_account_seconds` /
        `new_member_seconds`) is set. When active, act only on members who are new by
        account age OR by time-in-server (catches immediately-joining bots regardless
        of account age). Conservative on missing join data, treated as NOT new to
        avoid false positives."""
        acc = rp.get("new_account_seconds", 0)
        mem = rp.get("new_member_seconds", 0)
        if not acc and not mem:
            return False  # gate disabled -> act on everyone (subject to other guards)
        now = discord.utils.utcnow()
        if acc and (now - member.created_at).total_seconds() < acc:
            return False
        joined = member.joined_at
        if mem and joined is not None and (now - joined).total_seconds() < mem:
            return False
        return True

    async def _handle_roleping(self, message, member, rp, now, conf) -> bool:
        if self._roleping_gated_out(member, rp):
            return False
        hits = self._role_hits(message, rp)
        if not hits:
            return False
        tripped, role_id, evidence = self.roleping.record(
            message.guild.id, member.id, hits, now,
            threshold=rp.get("threshold", 2), window=rp.get("window", 10),
            # Re-fire cooldown is the window, not the lockdown length: if the user can
            # still ping (lockdown failed, or they have mention perms) they keep getting
            # actioned instead of going silent.
            cooldown=max(5, rp.get("window", 10)),
        )
        if not tripped:
            return False
        guild = message.guild
        role = guild.get_role(role_id)
        rolename = role.name if role else role_id
        await actions.take_action(
            self, guild, member, rp["action"],
            f"Pinged role @{rolename} {rp.get('threshold', 2)}+ times across channels",
            "antibot_roleping", evidence=evidence,
        )
        if rp.get("lockdown", True) and role is not None:
            await self._lock_role(guild, role, rp.get("lockdown_seconds", 300))
        if rp.get("notice_message"):  # notice fires iff a message is configured
            await self._roleping_notice(guild, role, evidence, rp)
        return True

    async def _roleping_notice(self, guild, role, evidence, rp):
        """Reassure people who saw the ping that it was a bot and is handled.

        ``{role}`` becomes the real role mention so it renders as the coloured role,
        but the message is sent with ``AllowedMentions.none()`` so it never re-pings."""
        template = rp.get("notice_message") or _ROLEPING_NOTICE
        text = template.replace("{role}", role.mention if role else "role")[:2000]
        seen = set()
        for chan_id, _ in (evidence or {}).get("messages", []):
            if chan_id in seen:
                continue
            seen.add(chan_id)
            channel = guild.get_channel_or_thread(chan_id)
            if channel is None:
                continue
            try:
                await channel.send(text, allowed_mentions=discord.AllowedMentions.none())
            except (discord.Forbidden, discord.HTTPException):
                pass
            if len(seen) >= 5:  # cap to avoid a wall of notices on a wide ping
                break

    @staticmethod
    def _role_hits(message, rp):
        watched = rp.get("watched_roles", [])
        min_members = rp.get("min_role_members", 0)
        hits = []
        for role in message.role_mentions:
            if watched:
                if role.id not in watched:
                    continue
            elif not role.mentionable:
                continue  # empty watch list => only currently-mentionable roles
            if min_members and len(role.members) < min_members:
                continue  # ignore pings of small roles (bots target the biggest ones)
            # count raw occurrences so a single message pinging the role N times counts N
            count = message.content.count(role.mention)
            for _ in range(max(1, count)):
                hits.append((role.id, message.channel.id, message.id))
        return hits

    async def _match_signature(self, guild, member, feats, sig_cfg):
        store = await self.config.guild(guild).signature_store()
        if not store:
            return
        conf, matched, why = signatures.compare_store(
            feats, store, sig_cfg.get("weights"), simhash_dist=sig_cfg.get("simhash_distance", 8)
        )
        if matched is None or conf <= 0:
            return
        tiers = sorted(sig_cfg.get("tiers", []), key=lambda t: t["min"], reverse=True)
        tier = next((t for t in tiers if conf >= t["min"]), None)
        if tier is None:
            return
        action_cfg = dict(tier["action"])
        # auto-learned signatures are notify-only until a mod confirms them
        if matched.get("trust") == "auto" and action_cfg.get("action") in _PUNITIVE:
            action_cfg = dict(action_cfg, action="notify", modlog=False)
        name = matched.get("label") or matched.get("id")
        extra = {"Confidence": f"{conf:.2f}", "Signature": name, "Signals": ", ".join(why) or "-"}
        await actions.take_action(
            self, guild, member, action_cfg,
            f"Matched bot signature '{name}' ({conf:.0%})", "antibot_signature", extra_fields=extra,
        )

    async def _ok(self, ctx, msg):
        """Config confirmation: tick the command and post a self-deleting note."""
        try:
            await ctx.tick()
        except Exception:
            pass
        await ctx.send(msg, delete_after=60)

    async def _warn(self, ctx, msg):
        """Transient validation/error feedback (self-deleting, no tick)."""
        await ctx.send(msg, delete_after=60)

    # --- commands --------------------------------------------------------- #
    @commands.guild_only()
    @checks.admin_or_permissions(manage_guild=True)
    @commands.group(name="antibot", aliases=["ab"])
    async def antibot(self, ctx):
        """AntiBot configuration."""
        pass

    @antibot.command(name="enable")
    async def ab_enable(self, ctx, detector: str = None):
        """Enable the cog, or a specific detector (spam/join/roleping/spammer/honeypot/signatures)."""
        await self._toggle(ctx, detector, True)

    @antibot.command(name="disable")
    async def ab_disable(self, ctx, detector: str = None):
        """Disable the cog, or a specific detector."""
        await self._toggle(ctx, detector, False)

    async def _toggle(self, ctx, detector, value):
        if detector is None:
            await self.config.guild(ctx.guild).enabled.set(value)
            return await self._ok(ctx, f"AntiBot {'enabled' if value else 'disabled'}.")
        detector = detector.lower()
        if detector not in (*_DETECTORS, "signatures"):
            return await self._warn(ctx, f"Unknown detector. Choose from: {', '.join((*_DETECTORS, 'signatures'))}")
        async with self.config.guild(ctx.guild).get_attr(detector)() as d:
            d["enabled"] = value
        await self._ok(ctx, f"Detector `{detector}` {'enabled' if value else 'disabled'}.")

    @antibot.command(name="action")
    async def ab_action(self, ctx, detector: str, action: str):
        """Set a detector's action: none/log/notify/timeout/kick/ban/role. (Not signatures; use tiers.)"""
        detector, action = detector.lower(), action.lower()
        if detector not in _DETECTORS:
            return await self._warn(ctx, f"Choose a detector: {', '.join(_DETECTORS)} (signatures use `tier`).")
        if action not in _ACTIONS:
            return await self._warn(ctx, f"Choose an action: {', '.join(_ACTIONS)}")
        async with self.config.guild(ctx.guild).get_attr(detector)() as d:
            d["action"]["action"] = action
        await self._ok(ctx, f"`{detector}` action set to `{action}`.")

    @antibot.command(name="deletemsgs")
    async def ab_deletemsgs(self, ctx, detector: str, on_off: bool):
        """Toggle message deletion for a detector's action (default on)."""
        detector = detector.lower()
        if detector not in _DETECTORS:
            return await self._warn(ctx, f"Choose a detector: {', '.join(_DETECTORS)}")
        async with self.config.guild(ctx.guild).get_attr(detector)() as d:
            d["action"]["delete_messages"] = on_off
        await self._ok(ctx, f"`{detector}` delete_messages set to `{on_off}`.")

    @antibot.command(name="notifychannel")
    async def ab_notifychannel(self, ctx, channel: discord.TextChannel = None):
        """Set (or clear) the alert channel."""
        await self.config.guild(ctx.guild).notify_channel.set(channel.id if channel else None)
        await self._ok(ctx, f"Notify channel set to {channel.mention}." if channel else "Notify channel cleared.")

    @antibot.command(name="notifyrole")
    async def ab_notifyrole(self, ctx, role: discord.Role = None):
        """Set (or clear) the role pinged on alerts."""
        await self.config.guild(ctx.guild).notify_role.set(role.id if role else None)
        await self._ok(ctx, f"Notify role set to {role.name}." if role else "Notify role cleared (no ping).")

    @antibot.command(name="quarantine")
    async def ab_quarantine(self, ctx, role: discord.Role = None):
        """Set (or clear) the default role for the `role` action."""
        if role and role >= ctx.guild.me.top_role:
            return await self._warn(ctx, "That role is above my top role, so I couldn't assign it.")
        await self.config.guild(ctx.guild).quarantine_role.set(role.id if role else None)
        await self._ok(ctx, f"Quarantine role set to {role.name}." if role else "Quarantine role cleared.")

    @antibot.command(name="bandm")
    async def ab_bandm(self, ctx, *, message: str = None):
        """DM sent to a user right before a **ban** action fires. Default: no DM.

        Placeholders: `{guild}`, `{member}`, `{reason}`. Run with no text to view the current
        message; pass `off`/`none`/`clear` to disable (no DM before ban)."""
        if message is None:
            curr = await self.config.guild(ctx.guild).ban_dm_message()
            if not curr:
                return await self._warn(ctx, "No ban DM set; no message is sent before a ban.")
            return await ctx.send(f"**Current ban DM:**\n{curr[:1900]}", delete_after=60)
        if message.strip().lower() in ("off", "none", "clear", "disable", "disabled"):
            await self.config.guild(ctx.guild).ban_dm_message.set(None)
            return await self._ok(ctx, "Ban DM disabled; no message is sent before a ban.")
        await self.config.guild(ctx.guild).ban_dm_message.set(message)
        await self._ok(ctx, "Ban DM message set (sent before ban actions; DM toggle still applies).")

    @antibot.group(name="whitelist")
    async def ab_whitelist(self, ctx):
        """Manage immune roles / ignored channels."""
        pass

    @ab_whitelist.command(name="role")
    async def ab_wl_role(self, ctx, action: str, role: discord.Role):
        """add/remove a whitelisted (immune) role."""
        await self._list_edit(ctx, "whitelist_roles", action, role.id, role.name)

    @ab_whitelist.command(name="channel")
    async def ab_wl_channel(
        self, ctx, action: str,
        channel: Union[discord.TextChannel, discord.VoiceChannel, discord.StageChannel, discord.Thread],
    ):
        """add/remove a whitelisted (ignored) channel for the content detectors."""
        await self._list_edit(ctx, "whitelist_channels", action, channel.id, channel.mention)

    async def _list_edit(self, ctx, key, action, item_id, label):
        action = action.lower()
        if action not in ("add", "remove"):
            return await self._warn(ctx, "Use `add` or `remove`.")
        async with self.config.guild(ctx.guild).get_attr(key)() as lst:
            if action == "add" and item_id not in lst:
                lst.append(item_id)
            elif action == "remove" and item_id in lst:
                lst.remove(item_id)
        await self._ok(ctx, f"{action.capitalize()}ed {label} {'to' if action == 'add' else 'from'} `{key}`.")

    @antibot.command(name="threshold")
    async def ab_threshold(self, ctx, channels: int, seconds: int):
        """Cross-channel spam trip: same message in N channels within T seconds."""
        async with self.config.guild(ctx.guild).spam() as s:
            s["channels"], s["window"] = max(2, channels), max(1, seconds)
        await self._ok(ctx, f"Spam threshold: {max(2, channels)} channels within {max(1, seconds)}s.")

    @antibot.command(name="distance")
    async def ab_distance(self, ctx, value: int):
        """Cross-channel near-duplicate tolerance (SimHash Hamming distance, default 8)."""
        async with self.config.guild(ctx.guild).spam() as s:
            s["simhash_distance"] = max(0, value)
        await self._ok(ctx, f"Spam SimHash distance set to {max(0, value)}.")

    @antibot.command(name="timeout")
    async def ab_timeout(self, ctx, detector: str, *, duration: str):
        """Set the timeout length used when a detector's action is `timeout` (e.g. 1h)."""
        detector = detector.lower()
        if detector not in _DETECTORS:
            return await self._warn(ctx, f"Choose a detector: {', '.join(_DETECTORS)}")
        secs = max(1, _dur(duration))
        async with self.config.guild(ctx.guild).get_attr(detector)() as d:
            d["action"]["timeout_seconds"] = secs
        await self._ok(ctx, f"`{detector}` timeout length set to {secs}s.")

    @antibot.command(name="dm")
    async def ab_dm(self, ctx, detector: str, on_off: bool):
        """Toggle DMing the user before a detector acts."""
        detector = detector.lower()
        if detector not in _DETECTORS:
            return await self._warn(ctx, f"Choose a detector: {', '.join(_DETECTORS)}")
        async with self.config.guild(ctx.guild).get_attr(detector)() as d:
            d["action"]["dm"] = on_off
        await self._ok(ctx, f"`{detector}` DM-before-action set to `{on_off}`.")

    @antibot.command(name="modlog")
    async def ab_modlog(self, ctx, detector: str, on_off: bool):
        """Toggle creating a modlog case for a detector's action."""
        detector = detector.lower()
        if detector not in _DETECTORS:
            return await self._warn(ctx, f"Choose a detector: {', '.join(_DETECTORS)}")
        async with self.config.guild(ctx.guild).get_attr(detector)() as d:
            d["action"]["modlog"] = on_off
        await self._ok(ctx, f"`{detector}` modlog case set to `{on_off}`.")

    @antibot.command(name="age")
    async def ab_age(self, ctx, which: str, *, duration: str):
        """Join detector age settings: `age new <dur>` (verified boundary) / `age kick <dur|0>`."""
        which = which.lower()
        if which not in ("new", "kick"):
            return await self._warn(ctx, "Use `new` or `kick` (e.g. `age kick 1d`, `age kick 0` to disable).")
        secs = _dur(duration)
        key = "age_new_seconds" if which == "new" else "age_kick_seconds"
        async with self.config.guild(ctx.guild).join() as j:
            j[key] = secs
        state = "disabled" if (which == "kick" and secs == 0) else f"{secs}s"
        await self._ok(ctx, f"join `{key}` set to {state}.")

    # --- role-ping subgroup --- #
    @antibot.group(name="roleping")
    async def ab_rp(self, ctx):
        """Role-ping abuse detector settings."""
        pass

    @ab_rp.command(name="watch")
    async def ab_rp_watch(self, ctx, action: str, role: discord.Role):
        """add/remove a watched role (empty list => all mentionable roles)."""
        await self._list_edit_nested(ctx, "roleping", "watched_roles", action, role.id, role.name)

    @ab_rp.command(name="threshold")
    async def ab_rp_threshold(self, ctx, count: int):
        """Pings of a watched role by one user before tripping (default 2)."""
        async with self.config.guild(ctx.guild).roleping() as r:
            r["threshold"] = max(1, count)
        await self._ok(ctx, f"Role-ping threshold set to {max(1, count)}.")

    @ab_rp.command(name="window")
    async def ab_rp_window(self, ctx, seconds: int):
        """Time window for counting role pings."""
        async with self.config.guild(ctx.guild).roleping() as r:
            r["window"] = max(1, seconds)
        await self._ok(ctx, f"Role-ping window set to {max(1, seconds)}s.")

    @ab_rp.command(name="lockdown")
    async def ab_rp_lockdown(self, ctx, on_off: bool):
        """Toggle auto-lockdown (flip the abused role non-mentionable)."""
        async with self.config.guild(ctx.guild).roleping() as r:
            r["lockdown"] = on_off
        await self._ok(ctx, f"Role-ping auto-lockdown: {on_off}.")

    @ab_rp.command(name="newaccount")
    async def ab_rp_newaccount(self, ctx, *, duration: str):
        """Gate: accounts *created* more recently than this count as new (e.g. 7d, 0 to disable).

        The new-member gate turns on automatically once either this or `newmember` is set;
        established members are then ignored. Set both to 0 to act on everyone."""
        secs = _dur(duration)
        async with self.config.guild(ctx.guild).roleping() as r:
            r["new_account_seconds"] = secs
        await self._ok(ctx, f"Role-ping new-account window: {'disabled' if not secs else humanize_timedelta(seconds=secs)}.")

    @ab_rp.command(name="newmember")
    async def ab_rp_newmember(self, ctx, *, duration: str):
        """Gate: members who *joined* more recently than this count as new (e.g. 1h, 0 to disable).

        This is the one that catches bots which immediately join and ping. The gate turns on
        automatically once this or `newaccount` is set."""
        secs = _dur(duration)
        async with self.config.guild(ctx.guild).roleping() as r:
            r["new_member_seconds"] = secs
        await self._ok(ctx, f"Role-ping new-member window: {'disabled' if not secs else humanize_timedelta(seconds=secs)}.")

    @ab_rp.command(name="minmembers")
    async def ab_rp_minmembers(self, ctx, count: int):
        """Only act on pings of roles with at least this many members (0 = any). Bots target
        the biggest pingable role, so this ignores legit pings of small roles."""
        async with self.config.guild(ctx.guild).roleping() as r:
            r["min_role_members"] = max(0, count)
        await self._ok(ctx, f"Role-ping minimum role size: {max(0, count) or 'any'}.")

    @ab_rp.command(name="noticemsg")
    async def ab_rp_noticemsg(self, ctx, *, message: str):
        """Set the public 'that ping was a bot, it's handled' notice text (use `{role}` for the
        pinged role's name). Pass `off`/`none`/`clear` to disable the notice entirely."""
        blank = message.strip().lower() in ("off", "none", "clear", "disable", "disabled")
        async with self.config.guild(ctx.guild).roleping() as r:
            r["notice_message"] = "" if blank else message
        await self._ok(ctx, "Role-ping notice disabled." if blank else "Role-ping notice message updated.")

    @ab_rp.command(name="duration")
    async def ab_rp_duration(self, ctx, *, duration: str):
        """How long a role stays locked (e.g. 5m, 1h)."""
        secs = _dur(duration)
        async with self.config.guild(ctx.guild).roleping() as r:
            r["lockdown_seconds"] = max(30, secs)
        await self._ok(ctx, f"Lockdown duration set to {max(30, secs)}s.")

    @ab_rp.command(name="lock")
    async def ab_rp_lock(self, ctx, role: discord.Role):
        """Manually make a role non-mentionable now (indefinitely)."""
        try:
            await role.edit(mentionable=False, reason=f"AntiBot manual lock by {ctx.author}")
        except (discord.Forbidden, discord.HTTPException):
            return await self._warn(ctx, "Couldn't edit that role; check my permissions/hierarchy.")
        async with self.config.guild(ctx.guild).locked_roles() as lk:
            lk[str(role.id)] = time.time() + 10 * 365 * 86400  # effectively until unlocked
        await self._ok(ctx, f"Locked pings for {role.name}. Use `roleping unlock` to restore.")

    @ab_rp.command(name="unlock")
    async def ab_rp_unlock(self, ctx, role: discord.Role):
        """Restore a role's mentionable flag immediately."""
        try:
            await role.edit(mentionable=True, reason=f"AntiBot manual unlock by {ctx.author}")
        except (discord.Forbidden, discord.HTTPException):
            return await self._warn(ctx, "Couldn't edit that role; check my permissions/hierarchy.")
        async with self.config.guild(ctx.guild).locked_roles() as lk:
            lk.pop(str(role.id), None)
        await self._ok(ctx, f"Unlocked pings for {role.name}.")

    # --- unusual-DM subgroup --- #
    @antibot.group(name="dmflag", aliases=["dmactivity"])
    async def ab_dmflag(self, ctx):
        """Unusual DM activity detector (a new/just-joined account DMing the bot)."""
        pass

    @ab_dmflag.command(name="account")
    async def ab_dmflag_account(self, ctx, *, duration: str):
        """Gate: accounts *created* more recently than this count as new (e.g. 7d, 0 to disable).

        The gate is 'either window': set this and/or `member`. If both are 0 the detector
        never fires (a DM to the bot alone is not grounds to act on every member)."""
        secs = _dur(duration)
        async with self.config.guild(ctx.guild).dmflag() as d:
            d["new_account_seconds"] = secs
        await self._ok(ctx, f"DM new-account window: {'disabled' if not secs else humanize_timedelta(seconds=secs)}.")

    @ab_dmflag.command(name="member")
    async def ab_dmflag_member(self, ctx, *, duration: str):
        """Gate: members who *joined* more recently than this count as new (e.g. 1d, 0 to disable)."""
        secs = _dur(duration)
        async with self.config.guild(ctx.guild).dmflag() as d:
            d["new_member_seconds"] = secs
        await self._ok(ctx, f"DM new-member window: {'disabled' if not secs else humanize_timedelta(seconds=secs)}.")

    @ab_dmflag.command(name="minmsgs")
    async def ab_dmflag_minmsgs(self, ctx, count: int):
        """DMs to the bot before it fires (default 1 = first DM). Raise to cut false positives."""
        async with self.config.guild(ctx.guild).dmflag() as d:
            d["min_messages"] = max(1, count)
        await self._ok(ctx, f"DM min messages set to {max(1, count)}.")

    @ab_dmflag.command(name="ignorecommands")
    async def ab_dmflag_ignorecommands(self, ctx, on_off: bool):
        """Skip DMs that are bot command invocations (legit new users often DM `help`)."""
        async with self.config.guild(ctx.guild).dmflag() as d:
            d["ignore_commands"] = on_off
        await self._ok(ctx, f"DM ignore-commands: {on_off}.")

    # --- spammer subgroup --- #
    @antibot.group(name="spammer")
    async def ab_spammer(self, ctx):
        """Discord suspected-spammer badge detector."""
        pass

    @ab_spammer.command(name="onmessage")
    async def ab_spammer_onmsg(self, ctx, on_off: bool):
        """Re-check the badge on messages from new members (catches post-join flagging)."""
        async with self.config.guild(ctx.guild).spammer() as s:
            s["check_on_message"] = on_off
        await self._ok(ctx, f"Spammer on-message check: {on_off}.")

    # --- honeypot subgroup --- #
    @antibot.group(name="honeypot")
    async def ab_hp(self, ctx):
        """Honeypot trap channel settings."""
        pass

    @ab_hp.command(name="channel")
    async def ab_hp_channel(
        self, ctx, action: str,
        channel: Union[discord.TextChannel, discord.VoiceChannel, discord.StageChannel],
    ):
        """add/remove a honeypot channel (text OR voice/stage chat)."""
        await self._list_edit_nested(ctx, "honeypot", "channels", action, channel.id, getattr(channel, "mention", str(channel)))

    @ab_hp.command(name="exemptafter")
    async def ab_hp_exemptafter(self, ctx, *, duration: str):
        """Members in the server longer than this are exempt (e.g. 7d)."""
        secs = _dur(duration)
        async with self.config.guild(ctx.guild).honeypot() as h:
            h["exempt_after_seconds"] = max(0, secs)
        await self._ok(ctx, f"Honeypot exempts members here longer than {max(0, secs)}s.")

    @ab_hp.command(name="exemptrole")
    async def ab_hp_exemptrole(self, ctx, action: str, role: discord.Role):
        """add/remove a role exempt from the honeypot."""
        await self._list_edit_nested(ctx, "honeypot", "exempt_roles", action, role.id, role.name)

    @ab_hp.command(name="reportexempt")
    async def ab_hp_reportexempt(self, ctx, on_off: bool):
        """Whether exempt members posting in the honeypot are reported (no punishment)."""
        async with self.config.guild(ctx.guild).honeypot() as h:
            h["report_exempt"] = on_off
        await self._ok(ctx, f"Honeypot report-exempt: {on_off}.")

    @ab_hp.command(name="reportimmune")
    async def ab_hp_reportimmune(self, ctx, on_off: bool):
        """Also report (never action) immune members (owner/admin/bot-owner/whitelisted)
        who post in a honeypot. Off by default; a tripwire for compromised staff accounts."""
        async with self.config.guild(ctx.guild).honeypot() as h:
            h["report_immune"] = on_off
        await self._ok(ctx, f"Honeypot report-immune: {on_off}.")

    async def _list_edit_nested(self, ctx, section, key, action, item_id, label):
        action = action.lower()
        if action not in ("add", "remove"):
            return await self._warn(ctx, "Use `add` or `remove`.")
        async with self.config.guild(ctx.guild).get_attr(section)() as d:
            lst = d.setdefault(key, [])
            if action == "add" and item_id not in lst:
                lst.append(item_id)
            elif action == "remove" and item_id in lst:
                lst.remove(item_id)
        await self._ok(ctx, f"{action.capitalize()}ed {label} {'to' if action == 'add' else 'from'} `{section}.{key}`.")

    # --- signatures subgroup --- #
    @antibot.group(name="sig", aliases=["signature", "signatures"])
    async def ab_sig(self, ctx):
        """Learned bot signatures."""
        pass

    @ab_sig.command(name="learn")
    async def ab_sig_learn(self, ctx, member: discord.Member, *, label: str = ""):
        """Capture a signature from a confirmed bot (uses their recent messages across channels)."""
        # Prefer the cross-channel text cache (messages seen since load); fall back to
        # scanning this channel's history if the cache has nothing for them yet.
        texts = list(self._recent_texts.get((ctx.guild.id, member.id), []))
        if not texts:
            async for msg in ctx.channel.history(limit=200):
                if msg.author.id == member.id and msg.content:
                    texts.append(msg.content)
                    if len(texts) >= 5:
                        break
        sig = await self.capture_signature(
            member, trust="confirmed", label=label or str(member),
            created_by=ctx.author.id, message_texts=texts,
        )
        await self._ok(ctx, f"Captured signature `{sig['id']}` for {member} ({len(texts)} sample message(s) across channels).")

    @ab_sig.command(name="seed")
    async def ab_sig_seed(self, ctx, *, text: str):
        """Seed a signature from an EXACT message, for bots already banned/deleted.

        Paste the exact spam text. Then add more messages with `sig addtext <id> <text>`
        and attach the account (even a banned/gone ID) with `sig account <id> <user_id>`."""
        sig = signatures.build_manual(
            message_texts=[text], label=f"seed by {ctx.author.display_name}", created_by=ctx.author.id,
        )
        await self._store_add(ctx.guild, sig)
        p = ctx.clean_prefix
        await ctx.send(
            f"Seeded confirmed signature `{sig['id']}` from 1 message.\n"
            f"• more messages: `{p}antibot sig addtext {sig['id']} <text>`\n"
            f"• attach account: `{p}antibot sig account {sig['id']} <user_id>`\n"
            f"• roles they grabbed: `{p}antibot sig role {sig['id']} add <role>`\n"
            f"• rename: `{p}antibot sig relabel {sig['id']} <label>`"
        )

    @ab_sig.command(name="addtext")
    async def ab_sig_addtext(self, ctx, sig_id: str, *, text: str):
        """Add another exact message to an existing signature."""
        nh, sh = signatures.fingerprint_text(text)
        async with self.config.guild(ctx.guild).signature_store() as store:
            s = next((x for x in store if x.get("id") == sig_id), None)
            if s is None:
                return await ctx.send("No such signature.")
            s.setdefault("msg_nhashes", [])
            s.setdefault("msg_simhashes", [])
            if nh not in s["msg_nhashes"]:
                s["msg_nhashes"].append(nh)
            s["msg_simhashes"].append(sh)
            count = len(s["msg_nhashes"])
        await self._ok(ctx, f"Added a message to `{sig_id}` ({count} unique message(s)).")

    @ab_sig.command(name="account")
    async def ab_sig_account(self, ctx, sig_id: str, user: discord.User):
        """Attach a (possibly banned/deleted) account to a signature by ID.

        The account is fetched from Discord, so a user ID works even if they've left
        or been banned. Sets avatar, username and account-age band on the signature."""
        avatar = user.avatar.key if user.avatar else None
        band = signatures.age_band((discord.utils.utcnow() - user.created_at).total_seconds())
        async with self.config.guild(ctx.guild).signature_store() as store:
            s = next((x for x in store if x.get("id") == sig_id), None)
            if s is None:
                return await ctx.send("No such signature.")
            if avatar:
                s["avatar_hash"] = avatar
            s["username_sample"] = user.name
            s["age_band"] = band
        await self._ok(
            ctx,
            f"Attached **{user}** to `{sig_id}` (avatar: {'yes' if avatar else 'default/none'}, "
            f"age band {band}). Note: the band is computed now, so it may differ from when the "
            f"account was active.",
        )

    @ab_sig.command(name="role")
    async def ab_sig_role(self, ctx, sig_id: str, action: str, role: discord.Role):
        """add/remove a role the bot grabbed, on a signature (for manual seeding)."""
        action = action.lower()
        if action not in ("add", "remove"):
            return await self._warn(ctx, "Use `add` or `remove`.")
        async with self.config.guild(ctx.guild).signature_store() as store:
            s = next((x for x in store if x.get("id") == sig_id), None)
            if s is None:
                return await ctx.send("No such signature.")
            ids = set(s.get("role_ids", []))
            ids.add(role.id) if action == "add" else ids.discard(role.id)
            s["role_ids"] = sorted(ids)
            count = len(s["role_ids"])
        await self._ok(ctx, f"Signature `{sig_id}` now has {count} role(s).")

    @ab_sig.command(name="relabel")
    async def ab_sig_relabel(self, ctx, sig_id: str, *, label: str):
        """Rename a signature."""
        async with self.config.guild(ctx.guild).signature_store() as store:
            s = next((x for x in store if x.get("id") == sig_id), None)
            if s is None:
                return await ctx.send("No such signature.")
            s["label"] = label
        await self._ok(ctx, f"Renamed `{sig_id}` to `{label}`.")

    @ab_sig.command(name="list")
    async def ab_sig_list(self, ctx):
        """List saved signatures."""
        store = await self.config.guild(ctx.guild).signature_store()
        if not store:
            return await ctx.send("No signatures saved.")
        lines = [
            f"`{s['id']}` [{s.get('trust', '?')}] {s.get('label') or '(no label)'} "
            f"· roles:{len(s.get('role_ids', []))} msgs:{len(s.get('msg_nhashes', []))} "
            f"avatar:{'y' if s.get('avatar_hash') else 'n'}"
            for s in store
        ]
        await ctx.send("**Signatures:**\n" + "\n".join(lines)[:1900])

    @ab_sig.command(name="show")
    async def ab_sig_show(self, ctx, sig_id: str):
        """Show one signature."""
        s = await self._find_sig(ctx.guild, sig_id)
        if not s:
            return await ctx.send("No such signature.")
        body = str(s)
        if len(body) > 1900:  # truncate the content, not the closing code fence
            body = body[:1900] + " …(truncated)"
        await ctx.send(f"```py\n{body}\n```")

    @ab_sig.command(name="delete")
    async def ab_sig_delete(self, ctx, sig_id: str):
        """Delete a signature."""
        async with self.config.guild(ctx.guild).signature_store() as store:
            before = len(store)
            store[:] = [s for s in store if s.get("id") != sig_id]
            removed = before - len(store)
        await self._ok(ctx, f"Removed {removed} signature(s).")

    @ab_sig.command(name="confirm")
    async def ab_sig_confirm(self, ctx, sig_id: str):
        """Promote an auto-learned signature to confirmed (lets it drive punitive tiers)."""
        async with self.config.guild(ctx.guild).signature_store() as store:
            found = False
            for s in store:
                if s.get("id") == sig_id:
                    s["trust"] = "confirmed"
                    found = True
        await self._ok(ctx, "Confirmed." if found else "No such signature.")

    @ab_sig.command(name="test")
    async def ab_sig_test(self, ctx, member: discord.Member):
        """Score a member against saved signatures (no action)."""
        conf_cfg = await self.config.guild(ctx.guild).all()
        feats = signatures.extract_member_features(
            member, recent_roles=self._recent_roles.get((ctx.guild.id, member.id))
        )
        await self._report_match(ctx, conf_cfg, feats)

    @ab_sig.command(name="simulate")
    async def ab_sig_simulate(self, ctx, *, text: str):
        """Score arbitrary text against saved signatures (text only, no member features)."""
        conf_cfg = await self.config.guild(ctx.guild).all()
        feats = signatures.extract_text_features(text)
        await self._report_match(ctx, conf_cfg, feats)

    @ab_sig.command(name="distance")
    async def ab_sig_distance(self, ctx, value: int):
        """Near-duplicate tolerance for message-based signature matching (SimHash Hamming).

        Separate from the cross-channel spam `distance`. Short messages need a larger
        value to match minor edits; identical text always matches regardless."""
        async with self.config.guild(ctx.guild).signatures() as s:
            s["simhash_distance"] = max(0, value)
        await self._ok(ctx, f"Signature SimHash distance set to {max(0, value)}.")

    @ab_sig.command(name="tier")
    async def ab_sig_tier(self, ctx, min_confidence: float, action: str):
        """Add/replace a confidence tier: at >= min_confidence, run <action>."""
        action = action.lower()
        if action not in _ACTIONS:
            return await self._warn(ctx, f"Choose an action: {', '.join(_ACTIONS)}")
        if not 0.0 <= min_confidence <= 1.0:
            return await self._warn(ctx, "min_confidence must be between 0.0 and 1.0.")
        async with self.config.guild(ctx.guild).signatures() as s:
            tiers = [t for t in s.get("tiers", []) if abs(t["min"] - min_confidence) > 1e-9]
            tiers.append({"min": min_confidence, "action": _action_cfg(action)})
            s["tiers"] = sorted(tiers, key=lambda t: t["min"], reverse=True)
        await self._ok(ctx, f"Tier set: >= {min_confidence:.2f} -> {action}.")

    @ab_sig.command(name="tierremove")
    async def ab_sig_tierremove(self, ctx, min_confidence: float):
        """Remove the tier at the given min_confidence."""
        async with self.config.guild(ctx.guild).signatures() as s:
            before = len(s.get("tiers", []))
            s["tiers"] = [t for t in s.get("tiers", []) if abs(t["min"] - min_confidence) > 1e-9]
            removed = before - len(s["tiers"])
        await self._ok(ctx, f"Removed {removed} tier(s).")

    @ab_sig.command(name="weight")
    async def ab_sig_weight(self, ctx, signal: str, value: float):
        """Set a signal weight (msg_simhash/role_jaccard/username_fuzzy/age_band)."""
        if signal not in signatures.DEFAULT_WEIGHTS:
            return await self._warn(ctx, f"Choose a signal: {', '.join(signatures.DEFAULT_WEIGHTS)}")
        async with self.config.guild(ctx.guild).signatures() as s:
            s.setdefault("weights", {})[signal] = max(0.0, value)
        await self._ok(ctx, f"Weight `{signal}` set to {max(0.0, value)}.")

    async def _report_match(self, ctx, conf_cfg, feats):
        sig_cfg = conf_cfg["signatures"]
        conf, matched, why = signatures.compare_store(
            feats, conf_cfg["signature_store"], sig_cfg.get("weights"),
            simhash_dist=sig_cfg.get("simhash_distance", 8),
        )
        if matched is None:
            return await ctx.send("No match (score 0).")
        tiers = sorted(sig_cfg.get("tiers", []), key=lambda t: t["min"], reverse=True)
        tier = next((t for t in tiers if conf >= t["min"]), None)
        act = tier["action"]["action"] if tier else "none"
        if matched.get("trust") == "auto" and act in _PUNITIVE:
            act = "notify (auto-learned, unconfirmed)"
        await ctx.send(
            f"Best match `{matched['id']}` ({matched.get('label') or '-'}): "
            f"confidence **{conf:.2f}** → action **{act}**\nSignals: {', '.join(why) or '-'}"
        )

    async def _find_sig(self, guild, sig_id):
        store = await self.config.guild(guild).signature_store()
        return next((s for s in store if s.get("id") == sig_id), None)

    @antibot.command(name="settings", aliases=["config", "show"])
    async def ab_settings(self, ctx):
        """Show the full current configuration."""
        c = await self.config.guild(ctx.guild).all()
        embed = build_settings_embed(ctx.guild, c, await ctx.embed_colour())
        await ctx.send(embed=embed)

    @antibot.command(name="panel", aliases=["setup", "ui"])
    @checks.bot_has_permissions(embed_links=True)
    async def ab_panel(self, ctx):
        """Open the interactive point-and-click configuration panel."""
        from .views import AntiBotPanel

        view = AntiBotPanel(self, ctx.guild, ctx.author)
        await view.build()
        view.message = await ctx.send(embed=await view.render_embed(), view=view)

    # --- shared config writers (used by the panel; commands write inline) --- #
    async def _set_top(self, guild, key, value):
        """Set a top-level guild-config scalar."""
        await self.config.guild(guild).set_raw(key, value=value)

    async def _set_section_fields(self, guild, section, **fields):
        """Merge scalar fields into a nested detector section."""
        async with self.config.guild(guild).get_attr(section)() as d:
            d.update(fields)

    async def _set_action_field(self, guild, detector, field, value):
        """Set one key of a detector's `action` sub-dict."""
        async with self.config.guild(guild).get_attr(detector)() as d:
            d.setdefault("action", {})[field] = value

    async def _set_list(self, guild, path, ids):
        """Replace a whole id-list. `path` is a top-level key or (section, key)."""
        ids = list(dict.fromkeys(ids))  # de-dupe, keep order
        if isinstance(path, tuple):
            section, key = path
            async with self.config.guild(guild).get_attr(section)() as d:
                d[key] = ids
        else:
            await self.config.guild(guild).set_raw(path, value=ids)


def build_settings_embed(guild, c, colour):
    """Render the full guild config as an embed. Shared by the `settings` command
    and the interactive panel's overview page (`c` = `config.guild(guild).all()`)."""
    def ch(i):
        x = guild.get_channel_or_thread(i) if i else None
        return x.mention if x else (f"`{i}`" if i else "none")

    def rl(i):
        x = guild.get_role(i) if i else None
        return x.mention if x else (f"`{i}`" if i else "none")

    def _capped(ids, render):
        # Cap the rendered list so no single embed field/description line can blow past
        # Discord's 1024/4096 limits on a guild with a huge whitelist or channel set.
        if not ids:
            return "none"
        out, total = [], 0
        for idx, item in enumerate(ids):
            piece = render(item)
            if out and total + len(piece) > 900:
                return ", ".join(out) + f" (+{len(ids) - idx} more)"
            out.append(piece)
            total += len(piece) + 2
        return ", ".join(out)

    def rls(ids):
        return _capped(ids, rl)

    def chs(ids):
        return _capped(ids, ch)

    def dur(s):
        return humanize_timedelta(seconds=int(s)) or "0s"

    def act(d):  # summarize an action_cfg
        a = d.get("action", {})
        s = a.get("action", "none")
        if s == "timeout":
            s += f" {dur(a.get('timeout_seconds', 3600))}"
        flags = []
        if not a.get("dm", True):
            flags.append("no-dm")
        if not a.get("modlog", True):
            flags.append("no-modlog")
        if not a.get("delete_messages", True):
            flags.append("keep-msgs")
        return s + (f" ({', '.join(flags)})" if flags else "")

    e = discord.Embed(title=f"AntiBot settings · {guild.name}", colour=colour)
    e.description = (
        f"**Enabled:** {c['enabled']}\n"
        f"**Notify channel:** {ch(c['notify_channel'])} · **Notify role:** {rl(c['notify_role'])}\n"
        f"**Quarantine role:** {rl(c['quarantine_role'])} · **Auto-learn on ban:** {c['auto_learn_on_ban']}\n"
        f"**Ban DM:** {'set' if c.get('ban_dm_message') else 'none'}\n"
        f"**Whitelist roles:** {rls(c['whitelist_roles'])}\n"
        f"**Whitelist channels:** {chs(c['whitelist_channels'])}"
    )
    sp = c["spam"]
    e.add_field(name="🔥 Cross-channel spam", inline=False, value=(
        f"enabled={sp['enabled']} · action={act(sp)}\n"
        f"{sp['channels']} channels / {dur(sp['window'])} · distance={sp['simhash_distance']} · cooldown={dur(sp['cooldown'])}"))
    jn = c["join"]
    e.add_field(name="👤 Suspicious join", inline=False, value=(
        f"enabled={jn['enabled']} · action={act(jn)}\n"
        f"new≤{dur(jn['age_new_seconds'])} · kick={'off' if not jn['age_kick_seconds'] else dur(jn['age_kick_seconds'])}"))
    rp = c["roleping"]
    gate_parts = []
    if rp.get("new_account_seconds"):
        gate_parts.append(f"acct<{dur(rp['new_account_seconds'])}")
    if rp.get("new_member_seconds"):
        gate_parts.append(f"joined<{dur(rp['new_member_seconds'])}")
    gate = " or ".join(gate_parts) if gate_parts else "off (all members)"
    e.add_field(name="🔔 Role-ping abuse", inline=False, value=(
        f"enabled={rp['enabled']} · action={act(rp)} · new-only: {gate}\n"
        f"threshold={rp['threshold']} / {dur(rp['window'])} · min role size={rp.get('min_role_members', 0) or 'any'}\n"
        f"lockdown={rp['lockdown']} {dur(rp['lockdown_seconds'])} · notice={'on' if rp.get('notice_message') else 'off'}\n"
        f"watched: {rls(rp['watched_roles']) if rp['watched_roles'] else 'all mentionable'}"))
    sm = c["spammer"]
    e.add_field(name="⚠️ Spammer badge", inline=False, value=(
        f"enabled={sm['enabled']} · action={act(sm)} · on-message={sm['check_on_message']}"))
    dm = c.get("dmflag", {})
    dm_gate = []
    if dm.get("new_account_seconds"):
        dm_gate.append(f"acct<{dur(dm['new_account_seconds'])}")
    if dm.get("new_member_seconds"):
        dm_gate.append(f"joined<{dur(dm['new_member_seconds'])}")
    dm_gate = " or ".join(dm_gate) if dm_gate else "off (never fires)"
    e.add_field(name="📨 Unusual DM activity", inline=False, value=(
        f"enabled={dm.get('enabled', False)} · action={act(dm)} · new: {dm_gate}\n"
        f"min messages={dm.get('min_messages', 1)} · ignore commands={dm.get('ignore_commands', True)}"))
    hp = c["honeypot"]
    e.add_field(name="🍯 Honeypot", inline=False, value=(
        f"enabled={hp['enabled']} · action={act(hp)} · report_exempt={hp['report_exempt']} · "
        f"report_immune={hp.get('report_immune', False)}\n"
        f"channels: {chs(hp['channels'])}\n"
        f"exempt ≥ {dur(hp['exempt_after_seconds'])} in server · exempt roles: {rls(hp['exempt_roles'])}"))
    sg = c["signatures"]
    tiers = " · ".join(f"≥{t['min']:.2f}→{t['action']['action']}"
                       for t in sorted(sg["tiers"], key=lambda t: t["min"], reverse=True))
    weights = ", ".join(f"{k}={v}" for k, v in sg.get("weights", {}).items())
    e.add_field(name="🤖 Signatures", inline=False, value=(
        f"enabled={sg['enabled']} · distance={sg.get('simhash_distance', 8)} · saved={len(c['signature_store'])}\n"
        f"tiers: {tiers}\nweights: {weights}"))
    if c["locked_roles"]:
        e.add_field(name="🔒 Currently locked roles", inline=False,
                    value=rls([int(r) for r in c["locked_roles"]]))
    return e


def _dur(s):
    """Parse a duration string to seconds; accept 0/off/none to mean disabled.

    Raises BadArgument (rendered nicely by Red) instead of crashing when the
    input can't be parsed; parse_timedelta returns None for garbage input."""
    if str(s).strip().lower() in ("0", "off", "none", "disable", "disabled"):
        return 0
    td = parse_timedelta(s)
    if td is None:
        raise commands.BadArgument(f"Couldn't read a duration from `{s}`; try e.g. `30s`, `5m`, `1h`, `7d`.")
    return max(0, int(td.total_seconds()))


# Module-level text helpers (thin wrappers so on_message stays readable).
def _normalize(text):
    return signatures.normalize(text)


def _norm_hash(text):
    return signatures.norm_hash(text)


def _simhash(norm):
    return signatures.simhash64(signatures.tokenize(norm))
