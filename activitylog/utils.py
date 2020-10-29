# thanks to @Sinbad for time parsing!
from __future__ import annotations

import re
from datetime import datetime as dt
from typing import Optional
import os
import asyncio

import pytz
from dateutil import parser
from dateutil.tz import gettz
from dateutil.relativedelta import relativedelta

TIME_RE_STRING = r"\s?".join(
    [
        r"((?P<years>\d+?)\s?(years?|y))?",
        r"((?P<months>\d+?)\s?(months?|mt))?",
        r"((?P<weeks>\d+?)\s?(weeks?|w))?",
        r"((?P<days>\d+?)\s?(days?|d))?",
        r"((?P<hours>\d+?)\s?(hours?|hrs|hr?))?",
        r"((?P<minutes>\d+?)\s?(minutes?|mins?|m(?!o)))?",  # prevent matching "months"
        r"((?P<seconds>\d+?)\s?(seconds?|secs?|s))?",
    ]
)

TIME_RE = re.compile(TIME_RE_STRING, re.I)


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
    return ret


def parse_time_naive(datetimestring: str):
    return parser.parse(datetimestring)


def parse_timedelta(argument: str) -> Optional[relativedelta]:
    matches = TIME_RE.match(argument)
    if matches:
        params = {k: int(v) for k, v in matches.groupdict().items() if v}
        if params:
            return relativedelta(**params)
    return None


def get_all_names(guild_files, user):
    names = [str(user)]
    for log in guild_files:
        if not os.path.exists(log):
            continue
        with open(log, "r") as f:
            for line in f:
                if str(user.id) in line:
                    # user change their name
                    if "Member username:" in line:
                        username = line.strip().split('"')
                        discrim = username[1].split("#")[-1]
                        username = username[-2] + "#" + discrim
                        names.append(username)
                    # user changed their 4 digit discriminator
                    elif "Member discriminator:" in line:
                        username = line.strip().split('"')[-2]
                        names.append(username)
                    # starting name
                    elif "Member join:" in line:
                        username = line.strip().split("@")[-1].split("#")
                        username = username[0] + "#" + username[1].split(" ")[0]
                        if username is not str(user):
                            names.append(username)
    return set(names)


class LogHandle:
    """basic wrapper for logfile handles, used to keep track of stale handles"""

    def __init__(self, path, time=None, mode="a", buf=1):
        self.handle = open(path, mode, buf, errors="backslashreplace")
        self.lock = asyncio.Lock()

        if time:
            self.time = time
        else:
            self.time = dt.fromtimestamp(os.path.getmtime(path))

    async def write(self, value):
        async with self.lock:
            self._write(value)

    def close(self):
        self.handle.close()

    def _write(self, value):
        self.time = dt.utcnow()
        self.handle.write(value)
