# redbot/discord
from redbot.core.utils.chat_formatting import *
from redbot.core import Config, commands
from redbot.core.commands import Converter, BadArgument
import discord

import dateparser
from dateutil import parser
from dateutil.utils import default_tzinfo
from dateutil.tz import tzlocal
from zoneinfo import ZoneInfo
from datetime import datetime

from typing import Union, Optional, List


def smart_parse(
    date_str: str,
    user_zone: Optional[str] = None,
    target_zone: Optional[str] = None,
) -> Optional[datetime]:
    # 1) Detect any IANA zone name in the string tokens
    found_zone = None
    for tok in date_str.split():
        try:
            found_zone = ZoneInfo(tok)
            break
        except Exception:
            if tok.upper() == "PDT" or tok.upper() == "PST":
                found_zone = ZoneInfo("PST8PDT")
                break
            elif tok.upper() == "CST" or tok.upper() == "CDT":
                found_zone = ZoneInfo("CST6CDT")
                break
            continue

    # 2) Try strict parsing first
    try:
        dt = parser.parse(date_str, ignoretz=False)
    except (ValueError, parser.ParserError):
        # 3) Fallback to dateparser for "in X" / "X ago"
        settings = {
            "RETURN_AS_TIMEZONE_AWARE": True,
            "TIMEZONE": user_zone or ZoneInfo("UTC"),
        }
        dt = dateparser.parse(date_str, settings=settings)

    if not dt:
        return None

    # 4) If still naïve, attach a default:
    #    priority → explicit in string → user_zone → system local
    if dt.tzinfo is None:
        default_zone = found_zone or (ZoneInfo(user_zone) if user_zone else ZoneInfo("UTC"))
        dt = default_tzinfo(dt, default_zone)

    # 5) Finally, convert into the user’s requested target_zone
    if target_zone:
        dt = dt.astimezone(ZoneInfo(target_zone))

    return dt


class TimezoneConverter(Converter):
    """
    Checks timezone is correct and converts it to a timezone object
    """

    async def convert(self, ctx, arg: str) -> List[ZoneInfo]:
        zones = [z.strip() for z in arg.split(",")]

        for i, z in enumerate(zones):
            # adding in my own fixes to make certain codes not in the database work
            if z.upper() == "PDT" or z.upper() == "PST":
                z = "PST8PDT"
            elif z.upper() == "CST" or z.upper() == "CDT":
                z = "CST6CDT"
            elif z.upper() == "EDT":
                z = "America/New_York"

            try:
                zones[i] = ZoneInfo(z)
            except:
                raise BadArgument(
                    error(
                        f"Unrecongized timezone `{z}`, please find your timezone name under `TZ database name` column here: <https://en.wikipedia.org/wiki/List_of_tz_database_time_zones>"
                    )
                )

        return zones


class TimeHelper(commands.Cog):
    """
    Command suite for comparing timezones and getting discord formated time stamps
    """

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=789646516315646, force_registration=True)

        default_user = {"timezone": "UTC"}
        self.config.register_user(**default_user)

    @staticmethod
    def format_datetime(date: datetime) -> str:
        """
        Formats datetime into user readable string

        Args:
            date (datetime): Datetime object representing date

        Returns:
            str: The date formatted as a string
        """
        return date.strftime("%b %d, %Y %I:%M %p %Z")

    async def get_date(
        self,
        user: Union[discord.Member, discord.User],
        date: str,
        timezone: Optional[str] = None,
    ) -> Union[datetime, None]:
        """
        Returns the date in the user's timezone, if set

        Args:
            user (discord.Member, discord.User): The user calling the function
            date (str): Date as a string
            timezone (str, Optional): Convert date to this timezone
        """
        user_timezone = await self.config.user(user).timezone()

        return smart_parse(date, user_timezone, timezone)

    @commands.hybrid_group(aliases=["ti"])
    async def time(self, ctx):
        """
        Time helper tools

        **Set your timezone with `myzone` command so you don't need to specify your timezone using `time`!**
        """
        pass

    @time.command(name="myzone", usage="<my_timezone>")
    async def myzone(self, ctx, *, timezone: TimezoneConverter):
        """
        (Optional) Set your timezone

        Other time commands will use your timezone if you don't provide a timezone when converting a time.

        Timezone formats:
        - Timezone code: EST, EDT, UTC, etc
        - Timezone name: America/New_York, America/Bogota, Asia/Rangoon, etc

        See timezone names here: https://en.wikipedia.org/wiki/List_of_tz_database_time_zones
        """
        await self.config.user(ctx.author).timezone.set(str(timezone[0]))
        await ctx.tick()

    @time.command(usage="<date_or_time_interval>")
    async def stamp(self, ctx, *, date: str):
        """
        Convert time into discord timestamp

        Discord timestamps are shown in the timezone of each user who views it

        The date can either be an exact date or an interval from now
        **Example Usage**
            - `[p]time stamp 2021-05-12 23:00:00 EST`
            - `[p]time stamp 21 July 2013 10:15 pm +0500`
            - `[p]time stamp 1st of October, 2021`
            - `[p]time stamp 20 hours ago`
            - `[p]time stamp in 50 minutes`
            - `[p]time stamp 01/10/2021`
            - `[p]time stamp now`

        See timezone names here: https://en.wikipedia.org/wiki/List_of_tz_database_time_zones
        """
        parsed = await self.get_date(ctx.author, date)
        if not parsed:
            return ctx.reply(error("Unrecognized date/time!"), delete_after=30)

        # convert to localzone for proper discord date formatting
        parsed = parsed.astimezone(tzlocal())
        timestamp = int(parsed.timestamp())

        msg = f"### **Timestamp formats for <t:{timestamp}:F>**:\n"
        for frmt in "fdtFDTR":
            msg += f"- `<t:{timestamp}:{frmt}>` = <t:{timestamp}:{frmt}>\n"

        await ctx.send(msg)

    @time.command(name="zone", usage="<comma seperated list of zones> <date_or_time_interval>")
    async def time_zone(self, ctx, zones: TimezoneConverter, *, date: str):
        """
        Convert time to specific timezones

        See timezone names here: https://en.wikipedia.org/wiki/List_of_tz_database_time_zones
        """
        parsed = await self.get_date(ctx.author, date)
        if not parsed:
            return ctx.reply(error("Unrecognized date/time!"), delete_after=30)

        msg = f"### **Timezones for `{self.format_datetime(parsed)}`:**\n"
        for zone in zones:
            new_date = await self.get_date(ctx.author, date, timezone=str(zone))

            msg += f"- `{zone}` = `{self.format_datetime(new_date)}`\n"

        msgs = pagify(msg)

        for m in msgs:
            await ctx.send(m)
