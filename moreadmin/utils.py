import re
import discord
from datetime import timedelta

TIME_RE_STRING = r"\s?".join(
    [
        r"((?P<weeks>\d+?)\s?(weeks?|w))?",
        r"((?P<days>\d+?)\s?(days?|d))?",
        r"((?P<hours>\d+?)\s?(hours?|hrs|hr?))?",
        r"((?P<minutes>\d+?)\s?(minutes?|mins?|m(?!o)))?",  # prevent matching "months"
        r"((?P<seconds>\d+?)\s?(seconds?|secs?|s))?",
    ]
)

TIME_RE = re.compile(TIME_RE_STRING, re.I)


def parse_timedelta(argument: str) -> timedelta:
    """
    Parses a string that contains a time interval and converts it to a timedelta object.
    """
    matches = TIME_RE.match(argument)
    if matches:
        params = {k: int(v) for k, v in matches.groupdict().items() if v}
        if params:
            return timedelta(**params)
    return None


def parse_seconds(seconds: int) -> str:
    """
    Take seconds and converts it to larger units
    Returns parsed message string
    """
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    days, hours = divmod(hours, 24)
    weeks, days = divmod(days, 7)
    months, weeks = divmod(weeks, 4)
    msg = []

    if months:
        msg.append(f"{int(months)} {'months' if months > 1 else 'month'}")
    if weeks:
        msg.append(f"{int(weeks)} {'weeks' if weeks > 1 else 'week'}")
    if days:
        msg.append(f"{int(days)} {'days' if days > 1 else 'day'}")
    if hours:
        msg.append(f"{int(hours)} {'hours' if hours > 1 else 'hour'}")
    if minutes:
        msg.append(f"{int(minutes)} {'minutes' if minutes > 1 else 'minute'}")
    if seconds:
        msg.append(f"{int(seconds)} {'seconds' if seconds > 1 else 'second'}")

    return ", ".join(msg)


def role_from_string(guild, role_name):

    role = discord.utils.find(lambda r: r.name == role_name, guild.roles)
    # if couldnt find by role name, try to find by role id
    if role is None:
        role = discord.utils.find(lambda r: r.id == role_name, guild.roles)

    return role
