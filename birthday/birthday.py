from redbot.core import commands, Config, checks
from redbot.core.commands import Context, Cog
from redbot.core.utils.chat_formatting import *
from redbot.core.utils.predicates import MessagePredicate
from redbot.core.utils.menus import menu, DEFAULT_CONTROLS

from tabulate import tabulate
from dateutil import parser
import asyncio
import datetime
import discord
from typing import Literal


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

        default_member = {"birthday": None, "birthday_handeled": False, "anniversary": False, "anni_handled": False}

        self.config.register_guild(**default_guild)
        self.config.register_member(**default_member)

        self.bday_task = asyncio.create_task(self.initialise())

    @staticmethod
    def parse_date(date: str):
        return parser.parse(date)

    @staticmethod
    def get_date_and_age(date: datetime):
        today = datetime.datetime.utcnow()
        if date.year != today.year:
            age = today.year - date.year
            date = date.strftime("%b %d, %Y")
        else:
            date = date.strftime("%b %d")
            age = None

        return date, age

    @staticmethod
    def get_years_in_guild(member: discord.Member):
        joined = member.joined_at.date()
        now = datetime.datetime.utcnow()

        return now.year - joined.year

    def cog_unload(self):
        self.bday_task.cancel()

    async def initialise(self):
        await self.bot.wait_until_ready()
        while True:
            now = datetime.datetime.utcnow()
            tomorrow = (now + datetime.timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
            # check bdays once a day, at utc midnight
            await self.check_bdays()
            await asyncio.sleep((tomorrow - now).total_seconds())
            ### TESTING:
            # await asyncio.sleep(5)

    async def check_bdays(self):
        for guild in self.bot.guilds:
            if await self.bot.cog_disabled_in_guild(self, guild):
                continue
            for member in guild.members:
                await self.check_member_bday(member)
                await self.check_member_anni(member)

    async def check_member_anni(self, member: discord.Member):
        today = datetime.datetime.utcnow().date()
        anni = member.joined_at.date()

        if not (await self.config.member(member).anniversary()):
            return

        anni = anni.replace(year=today.year)

        handled = await self.config.member(member).anni_handled()
        if anni == today:
            if not handled:
                # dm user
                dm = await self.config.guild(member.guild).anni_message()
                y = self.get_years_in_guild(member)
                s = "s" if y > 1 else ""
                dm = dm.format(years=y, s=s)
                try:
                    await member.send(dm)
                except:
                    pass
                # send anni in channel
                channel = await self.config.guild(member.guild).channel()
                channel = self.bot.get_channel(channel)
                if channel:
                    embed = discord.Embed(color=discord.Colour.gold())
                    embed.description = f"{member.mention} has been in {member.guild} for **{y} year{s}!**"
                    # embed.set_footer("Add your birthday using the `bday` command!")
                    try:
                        content = f"Congratulations {member.mention}!"
                        await channel.send(content=content, embed=embed, allowed_mentions=discord.AllowedMentions.all())
                    except:
                        pass

                # add role, if available
                role = await self.config.guild(member.guild).anni_role()
                role = member.guild.get_role(role)
                if role:
                    try:
                        await member.add_roles(role, reason="Birthday cog")
                    except:
                        pass

                await self.config.member(member).anni_handled.set(True)
        else:
            if handled:
                # remove anni role
                role = await self.config.guild(member.guild).anni_role()
                role = member.guild.get_role(role)
                if role:
                    try:
                        await member.remove_roles(role, reason="Birthday cog")
                    except:
                        pass
                # unhandled their anniversary, cya next year!
                await self.config.member(member).anni_handled.set(False)

    async def check_member_bday(self, member: discord.Member):
        today = datetime.datetime.utcnow().date()
        bday = await self.config.member(member).birthday()
        try:
            bday = self.parse_date(bday).date()
        except:
            # no bday for user
            return
        year = bday.year
        bday = bday.replace(year=today.year)

        handled = await self.config.member(member).birthday_handeled()
        if bday == today:
            if not handled:
                # dm user
                dm = await self.config.guild(member.guild).dm_message()
                try:
                    await member.send(dm)
                except:
                    pass
                # send bday in channel
                channel = await self.config.guild(member.guild).channel()
                channel = self.bot.get_channel(channel)
                if channel:
                    embed = discord.Embed(color=discord.Colour.gold())
                    if year != today.year:
                        age = today.year - year
                        embed.description = f"{member.mention} is now **{age} years old!**"
                    else:
                        embed.description = f"Happy Birthday to {member.mention}!"
                    # embed.set_footer("Add your birthday using the `bday` command!")
                    try:
                        content = f"Congratulations {member.mention}!"
                        await channel.send(content=content, embed=embed, allowed_mentions=discord.AllowedMentions.all())
                    except:
                        pass

                # add role, if available
                role = await self.config.guild(member.guild).role()
                role = member.guild.get_role(role)
                if role:
                    try:
                        await member.add_roles(role, reason="Birthday cog")
                    except:
                        pass

                await self.config.member(member).birthday_handeled.set(True)
        else:
            if handled:
                # remove bday role
                role = await self.config.guild(member.guild).role()
                role = member.guild.get_role(role)
                if role:
                    try:
                        await member.remove_roles(role, reason="Birthday cog")
                    except:
                        pass
                # unhandled their birthday, cya next year!
                await self.config.member(member).birthday_handeled.set(False)

    # @commands.command()
    # async def test(self, ctx, *, member: discord.Member):
    # await self.check_bdays()
    #    await self.check_member_bday(member)

    @commands.group(name="anniset")
    @commands.guild_only()
    @checks.admin_or_permissions(administrator=True)
    async def anniset(self, ctx):
        """
        Manage anniversary settings
        """
        pass

    @anniset.command(name="dmmessage")
    async def anniset_dmmessage(self, ctx, *, message: str = None):
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
    async def anniset_role(self, ctx, *, role: discord.Role = None):
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
    async def bdayset_dm_message(self, ctx, *, message: str = None):
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
    async def bdayset_channel(self, ctx, *, channel: discord.TextChannel = None):
        """Set channel to send birthday annoucements"""
        if not channel:
            await self.config.guild(ctx.guild).channel.clear()
        else:
            await self.config.guild(ctx.guild).channel.set(channel.id)

        await ctx.tick()

    @bdayset.command(name="role")
    @checks.bot_has_permissions(manage_roles=True)
    async def bdayset_role(self, ctx, *, role: discord.Role = None):
        """Set role to give users on their birthday"""
        if not role:
            await self.config.guild(ctx.guild).role.clear()
        else:
            await self.config.guild(ctx.guild).role.set(role.id)

        await ctx.tick()

    @commands.group(name="anni")
    @commands.guild_only()
    async def anni(self, ctx):
        """Manage your server anniversary"""
        pass

    @anni.command(name="set")
    async def anni_set(self, ctx, toggle: bool = None):
        """
        Opt in to anniversary announcements
        """
        current = await self.config.member(ctx.author).anniversary()

        if toggle is None:
            if current:
                await ctx.send("You are currently opted in for anniversary messages.")
                return
            else:
                await ctx.send("You are currently NOT opted in for anniversary messages.")
                return

        await self.config.member(ctx.author).anniversary.set(toggle)

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
            await ctx.send("No one has their anniversary set in your server!")
        else:
            await menu(ctx, pages, DEFAULT_CONTROLS)

    @commands.group(name="bday")
    @commands.guild_only()
    async def bday(self, ctx):
        """Manage your birthday"""
        pass

    @bday.command(name="set")
    async def bday_set(self, ctx, *, date: str = None):
        """Set your birthday. Year not required.
        Date can be any valid date format, like:
        05/20/99
        05-20-99
        May 5, 1999
        20/05/99
        05-20
        etc..
        """
        current = await self.config.member(ctx.author).birthday()
        if not date and not current:
            await self.bot.send_help_for(ctx, "bday set")
            return

        if not date:
            await ctx.send("Would you like to remove your birthday?")
            pred = MessagePredicate.yes_or_no(ctx)
            try:
                await self.bot.wait_for("message", check=pred, timeout=30)
            except asyncio.TimeoutError:
                await ctx.send("Took too long.")
                return
            if pred.result:
                await self.config.member(ctx.author).birthday.clear()
                await ctx.tick()
            else:
                await ctx.send("Nothing Changed.")

            return

        today = datetime.datetime.utcnow()
        try:
            date = self.parse_date(date).date()
            if date.year > today.year:
                await ctx.send(error("Year is in the future!"))
                return
            elif date.year < (today.year - 110):
                await ctx.send(error("You can't be that old..."))
                return
        except:
            await ctx.send(error("Invalid Date!"))
            return

        if date.year == today.year:
            date = date.strftime("%m/%d")
        else:
            date = date.strftime("%m/%d/%Y")

        await self.config.member(ctx.author).birthday.set(date)
        await ctx.tick()

    @bday.command(name="list")
    async def bday_list(self, ctx):
        """List birthdays in the server"""
        members = []
        birthdays = []
        for member in ctx.guild.members:
            bday = await self.config.member(member).birthday()
            if bday:
                bday_datetime = self.parse_date(bday)
                bday, age = self.get_date_and_age(bday_datetime)
                members.append(member.display_name)
                birthdays.append(bday)
                if age:
                    now = datetime.datetime.utcnow()
                    bday_datetime = bday_datetime.replace(year=now.year)
                    if now > bday_datetime:
                        birthdays[-1] += f", Turned {age}"
                    else:
                        birthdays[-1] += f", Turning {age}"

        pages = []
        raw = list(
            pagify(
                tabulate({"Member": members, "Birthday": birthdays}, tablefmt="github", headers="keys"),
                page_length=1700,
                delims=["\n"],
                priority=True,
            )
        )
        for i, page in enumerate(raw):
            pages.append(box(f"{page}\n\n-----------------\nPage {i+1} of {len(raw)}"))

        if not pages:
            await ctx.send("No one has their birthday set in your server!")
        else:
            await menu(ctx, pages, DEFAULT_CONTROLS)

    async def red_delete_data_for_user(
        self,
        *,
        requester: Literal["discord_deleted_user", "owner", "user", "user_strict"],
        user_id: int,
    ):
        pass
