from redbot.core import commands, Config, checks
from redbot.core.commands import Converter
from redbot.core.utils.chat_formatting import *
from redbot.core.utils.predicates import MessagePredicate
from redbot.core.utils.menus import menu, DEFAULT_CONTROLS

from tabulate import tabulate
from dateutil import parser
import discord

import asyncio
from zoneinfo import ZoneInfo
from datetime import datetime
from typing import Literal, Optional, Tuple, List


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


class Birthday(commands.Cog):
    """Track birthdays, add birthday role, and annouce birthdays for users."""

    def __init__(self, bot):
        self.bot = bot

        self.config = Config.get_conf(self, identifier=1561656787974966131, force_registration=True)

        default_guild = {
            "channel": None,
            "role": None,
            "dm_message": ":tada: Aurelia wishes you a very happy birthday! :tada:",
            "anni_role": None,
            "anni_message": ":tada: Aurelia is excited to wish you for {years} year{s} in CoE! :tada:",
        }

        default_member = {
            "birthday": None,
            "birthday_handeled": False,
            "anniversary": False,
            "anni_handled": False,
            "timezone": "UTC",
        }

        self.config.register_guild(**default_guild)
        self.config.register_member(**default_member)

        self.watcher_loop_task = asyncio.create_task(self.watcher_loop())

    @staticmethod
    def parse_with_timezone(
        date_str: str,
    ) -> Tuple[Optional[datetime], Optional[ZoneInfo]]:
        # 1) Detect any IANA zone name in the string tokens
        found_zone = None
        found_index = 0
        date_str_split = date_str.split()
        for i, tok in enumerate(date_str_split):
            try:
                found_zone = ZoneInfo(tok)
                found_index = i
                break
            except Exception:
                if tok.upper() == "PDT" or tok.upper() == "PST":
                    found_zone = ZoneInfo("PST8PDT")
                    found_index = i
                    break
                elif tok.upper() == "CST" or tok.upper() == "CDT":
                    found_zone = ZoneInfo("CST6CDT")
                    found_index = i
                    break
                elif tok.upper() == "EDT":
                    found_zone = ZoneInfo("America/New_York")
                    found_index = i
                    break
                continue

        if found_zone:
            date_str = " ".join(date_str_split[:found_index])

        try:
            dt = parser.parse(date_str)
            # if no zone, assume UTC
            found_zone = found_zone if found_zone is not None else ZoneInfo("UTC")
            return dt, found_zone
        except parser.ParserError:
            return None, None

    @staticmethod
    def get_date_midnight(date_str: str, timezone: ZoneInfo) -> datetime:
        """
        Parse a date string into a timezone-aware datetime at midnight in
        the specified timezone.
        """
        # parse naïve or aware datetime
        dt = parser.parse(date_str)
        # if it came back naïve, assume it was meant in that timezone
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone)
        else:
            dt = dt.astimezone(timezone)
        # normalize to midnight (keep tzinfo)
        return dt.replace(hour=0, minute=0, second=0, microsecond=0)

    @staticmethod
    def get_date_and_age(date: datetime):
        today = discord.utils.utcnow()
        if date.year != today.year:
            age: int = today.year - date.year
            date_str = date.strftime("%b %d, %Y")
        else:
            date_str = date.strftime("%b %d")
            age = None

        return date_str, age

    @staticmethod
    def get_years_in_guild(member: discord.Member):
        joined = member.joined_at.date()
        now = discord.utils.utcnow()

        return now.year - joined.year

    def cog_unload(self):
        self.watcher_loop_task.cancel()

    async def watcher_loop(self):
        await self.bot.wait_until_ready()
        while True:
            try:
                await self.bday_loop()
            except Exception as e:
                print(f"[Birthday] Internal loop crashed, restarting in 10s... {e}")
                await asyncio.sleep(10)

    async def bday_loop(self):
        while True:
            await self.check_bdays()
            await asyncio.sleep(120)

    async def check_bdays(self):
        for guild in self.bot.guilds:
            if await self.bot.cog_disabled_in_guild(self, guild):
                continue
            for member in guild.members:
                await self.check_member_bday(member)
                await self.check_member_anni(member)

    async def check_member_anni(self, member: discord.Member):
        # Only if they've opted in
        if not await self.config.member(member).anniversary():
            return

        # Load their timezone (fall back to UTC)
        tz_name = await self.config.member(member).timezone()
        try:
            timezone = ZoneInfo(tz_name)
        except Exception:
            timezone = ZoneInfo("UTC")

        # “Now” in their zone, and local date
        now_local = discord.utils.utcnow().astimezone(timezone)
        today_local = now_local.date()

        # Convert their join timestamp into that same zone
        joined_local = member.joined_at.astimezone(timezone)
        join_date_local = joined_local.date()

        # Build this year’s anniversary date
        try:
            anni_this_year = join_date_local.replace(year=today_local.year)
        except ValueError:
            # e.g. Feb 29 on non‐leap year
            return

        handled = await self.config.member(member).anni_handled()

        # If it’s their anniversary today…
        if anni_this_year == today_local:
            if not handled:
                # — DM the user
                dm = await self.config.guild(member.guild).anni_message()
                years = today_local.year - join_date_local.year
                s = "s" if years != 1 else ""
                dm = dm.format(years=years, s=s)
                try:
                    await member.send(dm)
                except:
                    pass

                # — Announce in the guild channel
                channel_id = await self.config.guild(member.guild).channel()
                channel = self.bot.get_channel(channel_id)
                if channel:
                    embed = discord.Embed(color=discord.Colour.gold())
                    embed.description = f"{member.mention} has been in {member.guild} for **{years} year{s}!**"
                    prefix = (await self.bot.get_valid_prefixes(member.guild))[0]
                    embed.set_footer(text=f"Use {prefix}anni set to opt into anniversary announcements!")
                    try:
                        await channel.send(
                            content=f"Congratulations {member.mention}!",
                            embed=embed,
                            allowed_mentions=discord.AllowedMentions.all(),
                        )
                    except:
                        pass

                # — Give them the anniversary role
                role_id = await self.config.guild(member.guild).anni_role()
                role = member.guild.get_role(role_id)
                if role:
                    try:
                        await member.add_roles(role, reason="Birthday cog")
                    except:
                        pass

                # Mark it done for today
                await self.config.member(member).anni_handled.set(True)

        # Once the day has passed, clear the flag (and remove the role)
        # cya next year!
        else:
            if handled:
                role_id = await self.config.guild(member.guild).anni_role()
                role = member.guild.get_role(role_id)
                if role:
                    try:
                        await member.remove_roles(role, reason="Birthday cog")
                    except:
                        pass
                await self.config.member(member).anni_handled.set(False)

    async def check_member_bday(self, member: discord.Member):
        # grab their saved birthday string (e.g. "05/20" or "05/20/1999")
        bday_str = await self.config.member(member).birthday()
        if not bday_str:
            return

        # load their timezone, default to UTC if theres an error
        tz_name = await self.config.member(member).timezone()
        try:
            timezone = ZoneInfo(tz_name)
        except Exception:
            timezone = ZoneInfo("UTC")

        # current moment in their zone
        now_local = discord.utils.utcnow().astimezone(timezone)
        today_local = now_local.date()

        # turn the saved string into a midnight datetime in that zone
        try:
            birth_midnight = self.get_date_midnight(bday_str, timezone)
        except (parser.ParserError, ValueError):
            return

        # remember original year for age calc
        birth_year = birth_midnight.year
        # map month/day onto this year
        bday_this_year = birth_midnight.replace(year=today_local.year).date()

        handled = await self.config.member(member).birthday_handeled()

        if bday_this_year == today_local:
            if not handled:
                # — DM the user
                dm = await self.config.guild(member.guild).dm_message()
                try:
                    await member.send(dm)
                except:
                    pass

                # — Announce in the guild channel
                channel_id = await self.config.guild(member.guild).channel()
                channel = self.bot.get_channel(channel_id)
                if channel:
                    embed = discord.Embed(color=discord.Colour.gold())
                    if birth_year != today_local.year:
                        age = today_local.year - birth_year
                        embed.description = f"{member.mention} is now **{age} years old!**"
                    else:
                        embed.description = f"Happy Birthday to {member.mention}!"

                    prefix = (await self.bot.get_valid_prefixes(member.guild))[0]
                    embed.set_footer(text=f"Use the {prefix}bday set command to set your own birthday!")
                    try:
                        await channel.send(
                            content=f"Congratulations {member.mention}!",
                            embed=embed,
                            allowed_mentions=discord.AllowedMentions.all(),
                        )
                    except:
                        pass

                # — Give them the birthday role
                role_id = await self.config.guild(member.guild).role()
                role = member.guild.get_role(role_id)
                if role:
                    try:
                        await member.add_roles(role, reason="Birthday cog")
                    except:
                        pass

                # mark done for today
                await self.config.member(member).birthday_handeled.set(True)

        else:
            # if we've rolled past their day, clear the handled flag and remove role
            if handled:
                role_id = await self.config.guild(member.guild).role()
                role = member.guild.get_role(role_id)
                if role:
                    try:
                        await member.remove_roles(role, reason="Birthday cog")
                    except:
                        pass
                await self.config.member(member).birthday_handeled.set(False)

    @commands.group(name="anniset")
    @commands.guild_only()
    @checks.admin_or_permissions(administrator=True)
    async def anniset(self, ctx):
        """
        Manage anniversary settings
        """
        pass

    @anniset.command(name="dmmessage")
    async def anniset_dmmessage(self, ctx, *, message: Optional[str] = None):
        """Set message DMed to users when its their anniversary!
        Leave empty to get/clear current message

        In your message, you can use `{years}` which will be replaced with the number of years in the server,
        With this, to make it grammatically correct use {s} which will be a `s` if years > 1
        """
        if not message:
            current = await self.config.guild(ctx.guild).anni_message()
            await ctx.send(f"Current message is `{current}`\nDo you want to reset it to default?")
            pred = MessagePredicate.yes_or_no(ctx)
            try:
                await self.bot.wait_for("message", check=pred, timeout=30)
            except asyncio.TimeoutError:
                await ctx.send("Took too long.")
                return
            if pred.result:
                await self.config.guild(ctx.guild).anni_message.clear()
                await ctx.send("DM message reset to default.")
            else:
                await ctx.send("Nothing changed.")
            return

        await self.config.guild(ctx.guild).anni_message.set(message)
        await ctx.tick()

    @anniset.command(name="role")
    @checks.bot_has_permissions(manage_roles=True)
    async def anniset_role(self, ctx, *, role: Optional[discord.Role] = None):
        """Set role to give users on their anniversary"""
        if not role:
            await self.config.guild(ctx.guild).anni_role.clear()
        else:
            await self.config.guild(ctx.guild).anni_role.set(role.id)

        await ctx.tick()

    @commands.group(name="bdayset")
    @commands.guild_only()
    @checks.admin_or_permissions(administrator=True)
    async def bdayset(self, ctx):
        """Manage birthday cog settings"""
        pass

    @bdayset.command(name="dmmessage")
    async def bdayset_dm_message(self, ctx, *, message: Optional[str] = None):
        """Set message DMed to users when its their birthday!
        Leave empty to get/clear current message
        """
        if not message:
            current = await self.config.guild(ctx.guild).dm_message()
            await ctx.send(f"Current message is `{current}`\nDo you want to reset it to default?")
            pred = MessagePredicate.yes_or_no(ctx)
            try:
                await self.bot.wait_for("message", check=pred, timeout=30)
            except asyncio.TimeoutError:
                await ctx.send("Took too long.")
                return
            if pred.result:
                await self.config.guild(ctx.guild).dm_message.clear()
                await ctx.send("DM message reset to default.")
            else:
                await ctx.send("Nothing changed.")
            return

        await self.config.guild(ctx.guild).dm_message.set(message)
        await ctx.tick()

    @bdayset.command(name="channel")
    async def bdayset_channel(self, ctx, *, channel: Optional[discord.TextChannel] = None):
        """Set channel to send birthday annoucements"""
        if not channel:
            await self.config.guild(ctx.guild).channel.clear()
        else:
            await self.config.guild(ctx.guild).channel.set(channel.id)

        await ctx.tick()

    @bdayset.command(name="role")
    @checks.bot_has_permissions(manage_roles=True)
    async def bdayset_role(self, ctx, *, role: Optional[discord.Role] = None):
        """Set role to give users on their birthday"""
        if not role:
            await self.config.guild(ctx.guild).role.clear()
        else:
            await self.config.guild(ctx.guild).role.set(role.id)

        await ctx.tick()

    @commands.hybrid_command(name="mytimezone")
    @commands.guild_only()
    async def mytimezone(self, ctx: commands.Context, timezone: TimezoneConverter):
        """
        Manually set your timezone for birthday and anniversary announcements

        Timezone formats:
        - Timezone code: EST, EDT, UTC, etc
        - Timezone name: America/New_York, America/Bogota, Asia/Rangoon, etc

        See timezone names here: https://en.wikipedia.org/wiki/List_of_tz_database_time_zones
        """
        await self.config.member(ctx.author).timezone.set(str(timezone[0]))
        await ctx.tick()

    @commands.hybrid_group(name="anni")
    @commands.guild_only()
    async def anni(self, ctx):
        """Manage your server anniversary"""
        pass

    @anni.command(name="set")
    async def anni_set(self, ctx: commands.Context, toggle: Optional[bool] = None):
        """
        Opt in to anniversary announcements

        Use [p]mytimezone if you want announcements made in your timezone
        """
        current = await self.config.member(ctx.author).anniversary()

        if toggle is None:
            if current:
                await ctx.reply(
                    info("You are currently opted in for anniversary messages."), delete_after=30, mention_author=False
                )
                return
            else:
                await ctx.reply(
                    info("You are currently NOT opted in for anniversary messages."),
                    delete_after=30,
                    mention_author=False,
                )
                return

        await self.config.member(ctx.author).anniversary.set(toggle)
        await ctx.reply(
            info("Use the `mytimezone` command if you want announcements made in your timezone!"), mention_author=False
        )
        await ctx.tick()

    @anni.command(name="list")
    async def anni_list(self, ctx):
        """List anniversaries in the server"""
        members = []
        anniversaries = []
        for member in ctx.guild.members:
            if not (await self.config.member(member).anniversary()):
                continue
            anni = member.joined_at.date()
            members.append(member.display_name)
            anniversaries.append(anni.strftime("%b %d, %Y"))

        pages = []
        raw = list(
            pagify(
                tabulate({"Member": members, "Anniversary": anniversaries}, tablefmt="github", headers="keys"),
                page_length=1700,
                delims=["\n"],
                priority=True,
            )
        )
        for i, page in enumerate(raw):
            pages.append(box(f"{page}\n\n-----------------\nPage {i+1} of {len(raw)}"))

        if not pages:
            await ctx.reply(
                info("No one has their anniversary set in your server!"), delete_after=30, mention_author=False
            )
        else:
            await menu(ctx, pages, DEFAULT_CONTROLS)

    @commands.hybrid_group(name="bday")
    @commands.guild_only()
    async def bday(self, ctx):
        """Manage your birthday"""
        pass

    @bday.command(name="set")
    async def bday_set(self, ctx, *, date_str: Optional[str] = None):
        """Set your birthday. Year not required.
        Date can be any valid date format, but **I may get confused if you use DD/MM/YYYY!**

        **Include your timezone if you want the announcement to start at midnight for you!**
        *If you do not include your timezone, birthday will be announced at UTC midnight*
        Example Timezones: EDT, PDT, America/New_York
        Here is a list of valid formats: <https://en.wikipedia.org/wiki/List_of_tz_database_time_zones>

        Examples:
        - 05/20/99 EDT
        - 05-20-99 PDT
        - May 5, 1999 America/New_York
        - 20/05/99
        - 05-20
        """
        current = await self.config.member(ctx.author).birthday()
        if not date_str and not current:
            await self.bot.send_help_for(ctx, "bday set")
            return

        if not date_str:
            await ctx.reply(info("Would you like to remove your birthday?"), delete_after=30)
            pred = MessagePredicate.yes_or_no(ctx)
            try:
                await self.bot.wait_for("message", check=pred, timeout=30)
            except asyncio.TimeoutError:
                await ctx.send(warning("Took too long."), delete_after=30)
                return
            if pred.result:
                await self.config.member(ctx.author).birthday.clear()
                await ctx.tick()
            else:
                await ctx.send(info("Nothing Changed."), delete_after=30)

            return

        today = discord.utils.utcnow()
        date, timezone = self.parse_with_timezone(date_str)
        if not date:
            await ctx.reply(error("Invalid Date!"), delete_after=30, mention_author=False)
            return

        if date.year > today.year:
            await ctx.reply(error("Are you from the future? 🤨"), delete_after=30, mention_author=False)
            return
        elif date.year < (today.year - 110):
            await ctx.reply(
                error("If you're that old you shouldn't be wasting time on the internet 🗿"),
                delete_after=30,
                mention_author=False,
            )
            return

        if date.year == today.year:
            date = date.strftime("%m/%d")
        else:
            date = date.strftime("%m/%d/%Y")

        await self.config.member(ctx.author).birthday.set(date)
        await self.config.member(ctx.author).timezone.set(str(timezone))
        await ctx.tick()

    @bday.command(name="list")
    async def bday_list(self, ctx):
        """
        List birthdays in the server, respecting each user's timezone.
        """
        members = []
        birthdays = []

        for member in ctx.guild.members:
            bday_str = await self.config.member(member).birthday()
            if not bday_str:
                continue

            # load their timezone
            tz_name = await self.config.member(member).timezone()
            try:
                timezone = ZoneInfo(tz_name)
            except Exception:
                timezone = ZoneInfo("UTC")

            # parse + normalize to midnight in their zone
            try:
                bday_midnight = self.get_date_midnight(bday_str, timezone)
            except (ValueError, parser.ParserError):
                continue

            # extract original year (for age calc) and format month/day
            birth_year = bday_midnight.year
            date_display = bday_midnight.strftime("%b %d")

            # figure out “today” in their zone
            now_local = discord.utils.utcnow().astimezone(timezone)
            today_local = now_local.date()

            # map their birth month/day onto this year
            try:
                bday_this_year = bday_midnight.replace(year=today_local.year).date()
            except ValueError:
                # e.g. Feb 29 on non‐leap year
                continue

            # compute age if we have a year
            age = None
            if birth_year != today_local.year:
                age = today_local.year - birth_year

            # build the display string
            entry = date_display
            if age is not None:
                if today_local > bday_this_year:
                    entry += f", Turned {age}"
                elif today_local < bday_this_year:
                    entry += f", Turning {age}"
                else:
                    entry += f", Turning {age} today"

            members.append(member.display_name)
            birthdays.append(entry)

        # 9) tabulate & paginate as before
        if not members:
            await ctx.send(info("No one has their birthday set in your server!"), delete_after=30)
            return

        pages = []
        raw = list(
            pagify(
                tabulate(
                    {"Member": members, "Birthday": birthdays},
                    tablefmt="github",
                    headers="keys",
                ),
                page_length=1700,
                delims=["\n"],
                priority=True,
            )
        )
        for i, page in enumerate(raw):
            pages.append(box(f"{page}\n\n-----------------\nPage {i+1} of {len(raw)}"))

        await menu(ctx, pages, DEFAULT_CONTROLS)

    async def red_delete_data_for_user(
        self,
        *,
        requester: Literal["discord_deleted_user", "owner", "user", "user_strict"],
        user_id: int,
    ):
        pass
