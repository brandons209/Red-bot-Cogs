import pytz
import re
from datetime import datetime, timedelta
from typing import Optional
from dateutil import parser
from dateutil.tz import gettz

TIME_RE_STRING = r"\s?".join(
    [
        r"((?P<years>\d+?)\s?(years?|y))?",
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
            tzdate = pytz.timezone(zone).localize(datetime.utcnow(), is_dst=None)
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
        ret = ret.astimezone(str(datetime.now().astimezone().tzinfo))
    return ret


def parse_time_naive(datetimestring: str):
    return parser.parse(datetimestring)


def parse_timedelta(argument: str) -> Optional[timedelta]:
    matches = TIME_RE.match(argument)
    if matches:
        params = {k: int(v) for k, v in matches.groupdict().items() if v}
        if params:
            return timedelta(**params)
    return None
