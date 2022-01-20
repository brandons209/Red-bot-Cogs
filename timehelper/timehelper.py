# redbot/discord
from redbot.core.utils.chat_formatting import *
from redbot.core import Config, checks, commands
from redbot.core.commands import Converter, BadArgument
import discord

import dateparser

from zoneinfo import ZoneInfo
from datetime import datetime
from typing import Literal, Union


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

    async def get_date(self, user: Union[discord.Member, discord.User], date: str, timezone: str = None) -> datetime:
        """
        Returns the date in the user's timezone, if set

        Args:
            user (discord.Member, discord.User): The user calling the function
            date (str): Date as a string
            timezone (str, Optional): Convert date to this timezone
        """
        user_timezone = await self.config.user(user).timezone()

        # since the settings timezone overwrites the timezone in the string, need to change this so timezone in string overrides it
        # its not a solid approach but it allows us to use the features of dateparser
        # first, find if there is a timezone in the date
        date_timezone = None
        for possible_timezone in date.split(" "):
            try:
                date_timezone = str(ZoneInfo(possible_timezone))
            except:
                pass

        date_timezone = user_timezone if date_timezone is None else date_timezone

        if timezone is not None:
            parsed = dateparser.parse(
                date, settings={"TIMEZONE": date_timezone, "TO_TIMEZONE": timezone, "RETURN_AS_TIMEZONE_AWARE": True}
            )
        else:
            parsed = dateparser.parse(date, settings={"TIMEZONE": date_timezone, "RETURN_AS_TIMEZONE_AWARE": True})

        return parsed

    @commands.group(aliases=["ti"])
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
            - `[p]time stamp 20 hours ago EST`
            - `[p]time stamp in 50 minutes`
            - `[p]time stamp 01/10/2021`
            - `[p]time stamp now`

        See timezone names here: https://en.wikipedia.org/wiki/List_of_tz_database_time_zones
        """
        # convert timezone to local zone, otherwise timestamp will be off since discord timestamp will convert from local timezone automatically
        parsed = await self.get_date(ctx.author, date, timezone=str(datetime.now().astimezone().tzinfo))

        if not parsed:
            return ctx.send(error("Unrecognized date/time!"), delete_after=30)

        timestamp = int(parsed.timestamp())

        msg = f"**Timestamp formats for <t:{timestamp}:F>**:\n"
        for frmt in "fdtFDTR":
            msg += f"\t- `<t:{timestamp}:{frmt}>` = <t:{timestamp}:{frmt}>\n"

        await ctx.send(msg)

    @time.command(name="zone", usage="<comma seperated list of zones> <date_or_time_interval>")
    async def time_zone(self, ctx, zones: TimezoneConverter, *, date: str):
        """
        Convert time to specific timezones

        See timezone names here: https://en.wikipedia.org/wiki/List_of_tz_database_time_zones
        """
        parsed = await self.get_date(ctx.author, date)
        if not parsed:
            return ctx.send(error("Unrecognized date/time!"), delete_after=30)

        msg = f"**Timezones for `{self.format_datetime(parsed)}`:**\n"
        for zone in zones:
            new_date = await self.get_date(ctx.author, date, timezone=str(zone))

            msg += f"\t- `{zone}` = `{self.format_datetime(new_date)}`\n"

        msgs = pagify(msg)

        for m in msgs:
            await ctx.send(m)
