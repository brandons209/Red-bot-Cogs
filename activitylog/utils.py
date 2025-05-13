from datetime import datetime as dt
import discord
import pytz
import uuid
import json
from dateutil import parser
from dateutil.tz import gettz
from typing import Dict, Union


def generate_unique_id() -> int:
    # Generate a UUID, use only the lowest 50 bits
    return uuid.uuid4().int & ((1 << 50) - 1)


def gen_tzinfos():
    for zone in pytz.common_timezones:
        try:
            tzdate = pytz.timezone(zone).localize(dt.utcnow(), is_dst=None)
        except pytz.NonExistentTimeError:
            pass
        else:
            tzinfo = gettz(zone)

            if tzinfo:
                yield tzdate.tzname(), tzinfo


def parse_time(datetimestring: str):
    tzinfo = dict(gen_tzinfos())
    ret = parser.parse(datetimestring, tzinfos=tzinfo)
    if ret.tzinfo is not None:
        ret = ret.astimezone(pytz.utc)
    else:  # assume utc
        ret = pytz.utc.localize(ret)
    return ret


def get_voice_flags(old: discord.VoiceState, new: discord.VoiceState):
    """
    Compares before and after voice states to find what has changed

    Args:
        old (discord.VoiceState): The old voice state.
        new (discord.VoiceState): The new voice state.

    Returns:
        Tuple[str, bool]: The updated flag. There should only be one updated flag from a change in voice state
    """
    attrs = {
        "afk",
        "deaf",
        "mute",
        "self_deaf",
        "self_mute",
        "self_stream",
        "self_video",
        "suppress",
    }
    old_flags = {k: getattr(old, k) for k in attrs}
    new_flags = {k: getattr(new, k) for k in attrs}
    updated = {key: new_flags[key] for key in new_flags if key in old_flags and new_flags[key] != old_flags[key]}

    return next(iter(updated.items()))


def compare_permissions(before_po: discord.PermissionOverwrite, after_po: discord.PermissionOverwrite):
    before_allow, before_deny = before_po.pair()
    after_allow, after_deny = after_po.pair()

    changes = []

    for perm_name in discord.Permissions.VALID_FLAGS.keys():
        before_allowed = getattr(before_allow, perm_name)
        before_denied = getattr(before_deny, perm_name)
        after_allowed = getattr(after_allow, perm_name)
        after_denied = getattr(after_deny, perm_name)

        if (before_allowed != after_allowed) or (before_denied != after_denied):
            changes.append(
                {
                    "permission": perm_name,
                    "before": ("allow" if before_allowed else "deny" if before_denied else "unset"),
                    "after": ("allow" if after_allowed else "deny" if after_denied else "unset"),
                }
            )

    return changes


def build_overwrite_change_log(added_perms: dict, removed_perms: dict, changed_perms: dict):
    def key_name(entity):
        return str(entity.id)

    def key_type(entity):
        return "Role" if isinstance(entity, discord.Role) else "Member"

    data = {}

    for entity, perms in added_perms.items():
        data[key_name(entity)] = {"type": key_type(entity), "added": perms}

    for entity, perms in removed_perms.items():
        data[key_name(entity)] = {"type": key_type(entity), "removed": perms}

    for entity, changes in changed_perms.items():
        entry = data.setdefault(key_name(entity), {"type": key_type(entity), "changes": {}})
        entry.setdefault("changes", {})
        for change in changes:
            entry["changes"][change["permission"]] = {"before": change["before"], "after": change["after"]}

    return data


def build_permission_overwrite(overwrite_data: str) -> Dict[str, discord.PermissionOverwrite]:
    """
    Reconstructs PermissionOverwrite objects from logged JSON string or dict.

    Parameters:
    - overwrite_data (str): The JSON string from log

    Returns:
    - Dict[str, PermissionOverwrite]: Mapping of entity_id to PermissionOverwrite object.
    """
    try:
        loaded_data = json.loads(overwrite_data)
    except json.JSONDecodeError:
        raise ValueError("Invalid JSON format for overwrite_data")

    result = {}

    for entity_id, entry in loaded_data.items():
        allow = discord.Permissions()
        deny = discord.Permissions()

        if "added" in entry:
            for perm in entry["added"]:
                setattr(allow, perm, True)

        elif "removed" in entry:
            # No permissions allowed or denied = default empty overwrite
            result[entity_id] = discord.PermissionOverwrite()
            continue

        elif "changes" in entry:
            for perm, change in entry["changes"].items():
                new_state = change.get("after")
                if new_state == "allow":
                    setattr(allow, perm, True)
                elif new_state == "deny":
                    setattr(deny, perm, True)
                # else: leave unset

        result[entity_id] = discord.PermissionOverwrite.from_pair(allow, deny)

    return result


def serialize_overwrites(overwrite_dict: dict) -> dict[str, dict]:
    """
    Serializes a full PermissionOverwrite mapping into a dict:
    {
        "entity_id": {
            "type": "Role" or "Member",
            "allow": [...],
            "deny": [...]
        },
        ...
    }
    """
    result = {}

    for entity, po in overwrite_dict.items():
        allow, deny = po.pair()
        allow_perms = [perm for perm in discord.Permissions.VALID_FLAGS if getattr(allow, perm)]
        deny_perms = [perm for perm in discord.Permissions.VALID_FLAGS if getattr(deny, perm)]

        result[str(entity.id)] = {
            "type": "Role" if isinstance(entity, discord.Role) else "Member",
            "allow": allow_perms,
            "deny": deny_perms,
        }

    return result


def deserialize_overwrites(
    overwrite_data: str,
    guild: discord.Guild,
) -> Dict[Union[discord.Role, discord.Member, int], discord.PermissionOverwrite]:
    try:
        loaded_data = json.loads(overwrite_data)
    except json.JSONDecodeError:
        raise ValueError("Invalid JSON format for overwrite_data")

    result = {}

    for entity_id, data in loaded_data.items():
        allow = discord.Permissions()
        deny = discord.Permissions()

        for perm in data.get("allow", []):
            setattr(allow, perm, True)
        for perm in data.get("deny", []):
            setattr(deny, perm, True)

        if data["type"] == "Role":
            entity = guild.get_role(int(entity_id))
        else:
            entity = guild.get_member(int(entity_id))

        if entity:
            result[entity] = discord.PermissionOverwrite.from_pair(allow, deny)
        else:
            result[int(entity_id)] = discord.PermissionOverwrite.from_pair(allow, deny)

    return result


# resolve helpers for audit logs
async def resolve_user(bot, user_id):
    try:
        user = await bot.fetch_user(int(user_id))
        return f"{user.name}"
    except:
        return str(user_id)


async def resolve_role(guild, role_id):
    if role_id is None:
        return None
    try:
        role = guild.get_role(int(role_id))
    except:
        role = None
    return role.name if role else str(role_id)


def resolve_channel(guild, channel_id):
    if channel_id is None:
        return None
    try:
        channel = guild.get_channel_or_thread(int(channel_id))
    except:
        channel = None
    return channel.name if channel else str(channel_id)


def resolve_emoji(bot, emoji_id):
    try:
        emoji = discord.utils.get(bot.emojis, id=int(emoji_id)) if emoji_id else None
    except:
        emoji = None
    return f"{emoji.name} ({emoji.url})" if emoji else str(emoji_id)


def resolve_sticker(guild, sticker_id):
    if sticker_id is None:
        return None
    try:
        sticker = discord.utils.get(guild.stickers, id=int(sticker_id))
    except:
        sticker = None
    return sticker.name if sticker else str(sticker_id)


def resolve_event(guild, event_id):
    if event_id is None:
        return None
    try:
        event = discord.utils.get(guild.scheduled_events, id=int(event_id))
    except:
        event = None
    return event.name if event else str(event_id)


def resolve_sound(guild, sound_id):
    if not hasattr(guild, "soundboard_sounds"):
        return str(sound_id)
    try:
        sound = discord.utils.get(guild.soundboard_sounds, id=int(sound_id))
    except:
        sound = None
    return sound.name if sound else str(sound_id)
