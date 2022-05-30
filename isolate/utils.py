import re
import discord

UNIT_TABLE = (
    (("weeks", "wks", "w"), 60 * 60 * 24 * 7),
    (("days", "dys", "d"), 60 * 60 * 24),
    (("hours", "hrs", "h"), 60 * 60),
    (("minutes", "mins", "m"), 60),
    (("seconds", "secs", "s"), 1),
)


class BadTimeExpr(Exception):
    pass


def _find_unit(unit):
    for names, length in UNIT_TABLE:
        if any(n.startswith(unit) for n in names):
            return names, length
    raise BadTimeExpr("Invalid unit: %s" % unit)


def parse_time(time):
    time = time.lower()
    if not time.isdigit():
        time = re.split(r"\s*([\d.]+\s*[^\d\s,;]*)(?:[,;\s]|and)*", time)
        time = sum(map(_timespec_sec, filter(None, time)))
    return int(time)


def _timespec_sec(expr):
    atoms = re.split(r"([\d.]+)\s*([^\d\s]*)", expr)
    atoms = list(filter(None, atoms))

    if len(atoms) > 2:  # This shouldn't ever happen
        raise BadTimeExpr("invalid expression: '%s'" % expr)
    elif len(atoms) == 2:
        names, length = _find_unit(atoms[1])
        if atoms[0].count(".") > 1 or not atoms[0].replace(".", "").isdigit():
            raise BadTimeExpr("Not a number: '%s'" % atoms[0])
    else:
        names, length = _find_unit("seconds")

    try:
        return float(atoms[0]) * length
    except ValueError:
        raise BadTimeExpr("invalid value: '%s'" % atoms[0])


def generate_timespec(sec: int, short=False, micro=False) -> str:
    timespec = []
    sec = int(sec)
    neg = sec < 0
    sec = abs(sec)

    for names, length in UNIT_TABLE:
        n, sec = divmod(sec, length)

        if n:
            if micro:
                s = "%d%s" % (n, names[2])
            elif short:
                s = "%d%s" % (n, names[1])
            else:
                s = "%d %s" % (n, names[0])

            if n <= 1 and not (micro and names[2] == "s"):
                s = s.rstrip("s")

            timespec.append(s)

    if len(timespec) > 1:
        if micro:
            spec = "".join(timespec)

        segments = timespec[:-1], timespec[-1:]
        spec = " and ".join(", ".join(x) for x in segments)
    elif timespec:
        spec = timespec[0]
    else:
        return "0"

    if neg:
        spec += " ago"

    return spec


def format_list(*items, join="and", delim=", "):
    if len(items) > 1:
        return (" %s " % join).join((delim.join(items[:-1]), items[-1]))
    elif items:
        return items[0]
    else:
        return ""


def overwrite_to_dict(overwrite):
    allow, deny = overwrite.pair()
    return {"allow": allow.value, "deny": deny.value}


def format_permissions(permissions, include_null=False):
    entries = []

    for perm, value in sorted(permissions, key=lambda t: t[0]):
        if value is True:
            symbol = "\N{WHITE HEAVY CHECK MARK}"
        elif value is False:
            symbol = "\N{NO ENTRY SIGN}"
        elif include_null:
            symbol = "\N{RADIO BUTTON}"
        else:
            continue

        entries.append(symbol + " " + perm.replace("_", " ").title().replace("Tts", "TTS"))

    if entries:
        return "\n".join(entries)
    else:
        return "No permission entries."


def getmname(mid, guild):
    member = discord.utils.get(guild.members, id=int(mid))

    if member:
        return str(member)
    else:
        return "(absent user #%s)" % mid


def role_from_string(guild, rolename, roles=None):
    if rolename is None:
        return None

    if roles is None:
        roles = guild.roles
    else:
        roles = [r for r in roles if isinstance(r, discord.Role)]

    if type(rolename) == int:
        role = discord.utils.get(roles, id=rolename)

        if role:
            return role
    else:
        rolename = rolename.lower()
        role = discord.utils.find(lambda r: r.name.lower() == rolename, roles)

    return role


def resolve_role_list(guild: discord.guild, roles: list) -> list:
    gen = (role_from_string(guild, name) for name in roles)
    return list(filter(None, gen))


def permissions_for_roles(channel, *roles):
    """
    Calculates the effective permissions for a role or combination of roles.
    Naturally, if no roles are given, the default role's permissions are used
    """
    default = channel.guild.default_role
    base = discord.Permissions(default.permissions.value)

    # Apply all role values
    for role in roles:
        base.value |= role.permissions.value

    # guild-wide Administrator -> True for everything
    # Bypass all channel-specific overrides
    if base.administrator:
        return discord.Permissions.all()

    role_ids = set(map(lambda r: r.id, roles))
    denies = 0
    allows = 0

    # Apply channel specific role permission overwrites
    for target, overwrite in channel.overwrites.items():
        # Handle default role first, if present
        allow, deny = overwrite.pair()
        allow, deny = allow.value, deny.value
        if overwrite == default:
            base.handle_overwrite(allow=allow, deny=deny)

        if isinstance(target, discord.Role) and target.id in role_ids:
            denies |= deny
            allows |= allow

    base.handle_overwrite(allow=allows, deny=denies)

    # if you can't send a message in a channel then you can't have certain
    # permissions as well
    if not base.send_messages:
        base.send_tts_messages = False
        base.mention_everyone = False
        base.embed_links = False
        base.attach_files = False

    # if you can't read a channel then you have no permissions there
    if not base.read_messages:
        denied = discord.Permissions.all_channel()
        base.value &= ~denied.value

    # text channels do not have voice related permissions
    if channel.type is discord.ChannelType.text:
        denied = discord.Permissions.voice()
        base.value &= ~denied.value

    return base


def overwrite_from_dict(data):
    allow = discord.Permissions(data.get("allow", 0))
    deny = discord.Permissions(data.get("deny", 0))
    return discord.PermissionOverwrite.from_pair(allow, deny)
