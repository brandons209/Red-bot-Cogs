import logging
import hashlib
import asyncio
import contextlib
from dateutil import parser
import datetime
import discord
import itertools
from typing import (
    Any,
    Dict,
)


from redbot.core import commands, Config, checks
from redbot.core.bot import Red
from redbot.core.config import _ValueCtxManager, Group, Value
from redbot.core.i18n import Translator, cog_i18n
from redbot.core.commands import Context, Cog

T_ = Translator("Birthdays", __file__)


def _(s):
    def func(*args, **kwargs):
        real_args = list(args)
        real_args.pop(0)
        return T_(s).format(*real_args, **kwargs)

    return func


@cog_i18n(T_)
class Birthdays(Cog):
    """Announces people's birthdays and gives them a birthday role for the whole day"""

    __author__ = "PancakeSparkle#8243"

    # Just some constants
    DATE_GROUP = "DATE"
    GUILD_DATE_GROUP = "GUILD_DATE"

    # More constants
    BDAY_LIST_TITLE = _("Birthday List")

    # Even more constants
    BDAY_WITH_YEAR = _("{} is now **{} years old**. <:aureliahappy:548738609763713035>")
    BDAY_WITHOUT_YEAR = _("Everypony say Happy Birthday to {}! <:aureliahappy:548738609763713035>")
    ROLE_SET = _("<:aureliaagree:616091883013144586> The birthday role on **{g}** has been set to: **{r}**.")
    BDAY_INVALID = _(":x: The birthday date you entered is invalid.")
    BDAY_SET = _("<:aureliaagree:616091883013144586> Your birthday has been set to: **{}**.")
    CHANNEL_SET = _(
        "<:aureliaagree:616091883013144586> "
        "The channel for announcing birthdays on **{g}** has been set to: **{c}**."
    )
    BDAY_REMOVED = _(":put_litter_in_its_place: Your birthday has been removed.")

    def __init__(self, bot):
        super().__init__()
        self.bot = bot
        self.logger = logging.getLogger("aurelia.cogs.birthdays")
        self.config = Config.get_conf(self, identifier=76846583746584, force_registration=True)

        self.config.init_custom(self.DATE_GROUP, 1)
        self.config.init_custom(self.GUILD_DATE_GROUP, 2)
        self.config.register_guild(
            channel=None, role=None, dmmessage=":tada: Aurelia wishes you a very happy birthday! :tada:", yesterdays=[]
        )
        self.config.register_member(birthday_sent=False)
        self.bday_task = asyncio.create_task(self.initialise())
        asyncio.create_task(self.check_breaking_change())

    # Events
    async def initialise(self):
        await self.bot.wait_until_ready()
        with contextlib.suppress(RuntimeError):
            while self == self.bot.get_cog(self.__class__.__name__):
                now = datetime.datetime.utcnow()
                tomorrow = (now + datetime.timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
                await self.clean_yesterday_bdays()
                await self.do_today_bdays()
                # await asyncio.sleep((tomorrow - now).total_seconds())
                await asyncio.sleep(20)
                await self.clean_sent()

    def cog_unload(self):
        self.bday_task.cancel()

    # Commands
    @commands.group()
    @commands.guild_only()
    async def bday(self, ctx: Context):
        """Birthday settings"""
        pass

    @bday.command(name="remove", aliases=["del", "clear", "rm"])
    async def bday_remove(self, ctx: Context):
        """Unsets your birthday date"""
        message = ctx.message
        await self.remove_user_bday(message.guild.id, message.author.id)
        await ctx.send(self.BDAY_REMOVED())

    @bday.command(name="set")
    async def bday_set_birthday(self, ctx: Context, *, date: str):
        """Set your birthday!

           The given date can either be month day, or day month
           Year is optional. If not given, the age won't be displayed.
        """
        message = ctx.message
        author = message.author
        year = None
        birthday = self.parse_date(date)
        today = datetime.datetime.utcnow().date()
        current_birthday = await self.get_birthday(ctx.guild.id, author.id)
        # An Invalid date was entered.
        if birthday is None:
            print(self.BDAY_INVALID())
            await ctx.send(self.BDAY_INVALID())
            return
        if today.year != birthday.year:
            if birthday.year > today.year:
                await ctx.send("You weren't born in the future, silly!")
                return
            if birthday.year < (today.year - 100):
                await ctx.send("No way you're that old, silly!")
                return
            year = birthday.year
        birthday = datetime.date(1, birthday.month, birthday.day)
        if current_birthday != None and birthday.toordinal() == current_birthday.toordinal():
            await ctx.send("Your birthday is already set to {}!".format(self.get_human_birthday(birthday)))
            return
        await self.remove_user_bday(ctx.guild.id, author.id)
        await self.get_date_config(ctx.guild.id, birthday.toordinal()).get_attr(author.id).set(year)
        await ctx.send(self.BDAY_SET(self.get_human_birthday(birthday)))
        # Check if today is their birthday
        today_ordinal = today.replace(year=1).toordinal()
        birthday_ordinal = birthday.replace(year=1).toordinal()
        if today_ordinal == birthday_ordinal:
            await self.handle_bday(author.id, year)

    @bday.command(name="list")
    async def bday_list(self, ctx: Context):
        """Lists birthdays

        If a user has their year set, it will display the age they'll get after their birthday this year"""
        message = ctx.message
        await self.clean_bdays()
        bdays = await self.get_guild_date_configs(message.guild.id)
        this_year = datetime.date.today().year
        embed = discord.Embed(title=self.BDAY_LIST_TITLE(), color=discord.Colour.lighter_grey())
        for k, g in itertools.groupby(
            sorted(datetime.datetime.fromordinal(int(o)) for o in bdays.keys()), lambda i: i.month,
        ):

            value = "\n".join(
                date.strftime("%d").lstrip("0")
                + ": "
                + ", ".join(
                    "{}".format(ctx.guild.get_member(int(u_id)).mention)
                    + ("" if year is None else " ({})".format(this_year - int(year)))
                    for u_id, year in bdays.get(str(date.toordinal()), {}).items()
                )
                for date in g
                if len(bdays.get(str(date.toordinal()))) > 0
            )
            if not value.isspace():
                embed.add_field(
                    name=datetime.datetime(year=1, month=k, day=1).strftime("%B"), value=value,
                )
        await ctx.send(embed=embed)

    @commands.group(name="bdayset")
    @checks.admin()
    async def bday_set(self, ctx: Context):
        """
        Manage birthday settings.
        """
        pass

    @bday_set.command(name="dmmessage")
    @checks.mod_or_permissions(manage_roles=True)
    async def bday_set_dmmessage(self, ctx: Context, *, bday_message: str = ""):
        """Sets the birthday message for DMs."""
        message = ctx.message
        author = message.author
        if bday_message == "":
            await self.config.guild(ctx.guild).dmmessage.set(":tada: Aurelia wishes you a very happy birthday! :tada:")
            await ctx.send(
                "Birthday DM message set to (default): :tada: Aurelia wishes you a very happy birthday! :tada:"
            )
        else:
            await self.config.guild(ctx.guild).dmmessage.set(bday_message)
            await ctx.send("Birthday DM message set to: " + str(bday_message))

    @bday_set.command(name="channel")
    @checks.mod_or_permissions(manage_roles=True)
    async def bday_set_channel(self, ctx: Context, channel: discord.TextChannel):
        """Sets the birthday announcement channel"""
        guild = ctx.guild
        await self.config.guild(channel.guild).channel.set(channel.id)
        await ctx.send(self.CHANNEL_SET(g=guild.name, c=channel.name))

    @bday_set.command(name="role")
    @checks.mod_or_permissions(manage_roles=True)
    async def bday_set_role(self, ctx: Context, *, role: discord.Role):
        """Sets the birthday role"""
        guild = ctx.message.guild
        await self.config.guild(role.guild).role.set(role.id)
        await ctx.send(self.ROLE_SET(g=guild.name, r=role.name))

    async def clean_bday(self, guild_id: int, guild_config: dict, user_id: int):
        guild = self.bot.get_guild(guild_id)
        if guild is not None:
            role = discord.utils.get(guild.roles, id=guild_config.get("role"))

            await self.maybe_update_guild(guild)
            member = guild.get_member(user_id)
            if member is not None and role is not None and role in member.roles:

                await member.remove_roles(role)

    async def handle_bday(self, user_id: int, year: str):
        embed = discord.Embed(color=discord.Colour.gold())
        all_guild_configs = await self.config.all_guilds()
        for guild_id, guild_config in all_guild_configs.items():
            guild = self.bot.get_guild(guild_id)
            if guild is not None:
                member = guild.get_member(user_id)
                sent = await self.config.member(member).birthday_sent()
                if member is not None and not sent:
                    role_id = guild_config.get("role")
                    if year is not None:
                        age = datetime.date.today().year - int(year)
                        embed.description = self.BDAY_WITH_YEAR(member.mention, age)
                    else:
                        embed.description = self.BDAY_WITHOUT_YEAR(member.mention)
                    if role_id is not None:
                        role = discord.utils.get(guild.roles, id=role_id)
                        if role is not None:
                            try:
                                await member.add_roles(role)
                            except (discord.Forbidden, discord.HTTPException):
                                pass
                            else:
                                async with self.config.guild(guild).yesterdays() as yesterdays:
                                    yesterdays.append(member.id)
                    channel = guild.get_channel(guild_config.get("channel"))
                    if channel is not None:
                        await channel.send(embed=embed)
                        message = guild_config.get("dmmessage")
                        await member.send(message)

                    await self.config.member(member).birthday_sent.set(True)

    async def clean_sent(self):
        all_members = await self.config.all_members()
        for guild_id, member_data in all_members.items():
            for member_id, _ in member_data.items():
                await self.config.member_from_id(guild_id, member_id).birthday_sent.set(False)

    async def clean_bdays(self):
        birthdays = await self.get_all_date_configs()
        for guild_id, guild_bdays in birthdays.items():
            for date, bdays in guild_bdays.items():
                for user_id, year in bdays.items():
                    if not any(g.get_member(int(user_id)) is not None for g in self.bot.guilds):
                        async with self.get_date_config(guild_id, date)() as config_bdays:
                            del config_bdays[user_id]

                config_bdays = await self.get_date_config(guild_id, date)()
                if len(config_bdays) == 0:
                    await self.get_date_config(guild_id, date).clear()

    async def remove_user_bday(self, guild_id: int, user_id: int):
        user_id = str(user_id)
        birthdays = await self.get_guild_date_configs(guild_id)
        for date, user_ids in birthdays.items():
            if user_id in user_ids:
                await self.get_date_config(guild_id, date).get_attr(user_id).clear()
                guild = self.bot.get_guild(guild_id)
                if not guild:
                    continue
                role_id = await self.config.guild(guild).role()
                role = guild.get_role(role_id)
                member = guild.get_member(int(user_id))
                # remove role if they have it
                if role and member and role in member.roles:
                    await member.remove_roles(role)

    async def clean_yesterday_bdays(self):
        all_guild_configs = await self.config.all_guilds()
        for guild_id, guild_config in all_guild_configs.items():
            for user_id in guild_config.get("yesterdays", []):
                asyncio.create_task(self.clean_bday(guild_id, guild_config, user_id))
                guild = self.bot.get_guild(int(guild_id))
                if not guild:
                    continue
                role_id = await self.config.guild(guild).role()
                role = guild.get_role(role_id)
                member = guild.get_member(int(user_id))
                # remove role if they have it
                if role and member and role in member.roles:
                    await member.remove_roles(role)
                    await self.config.member(member).birthday_sent.set(False)

            await self.config.guild(discord.Guild(data={"id": int(guild_id)}, state=None)).yesterdays.clear()

    async def do_today_bdays(self):
        guild_configs = await self.get_all_date_configs()
        for guild_id, guild_config in guild_configs.items():
            this_date = datetime.datetime.utcnow().date().replace(year=1)
            todays_bday_config = guild_config.get(str(this_date.toordinal()), {})
            for user_id, year in todays_bday_config.items():
                asyncio.create_task(self.handle_bday(int(user_id), year))

    async def maybe_update_guild(self, guild: discord.Guild):
        if not guild.unavailable and guild.large:
            if not guild.chunked or any(m.joined_at is None for m in guild.members):
                await self.bot.request_offline_members(guild)

    def parse_date(self, date: str):
        result = None
        try:
            result = parser.parse(date)
        except ValueError:
            pass
        return result

    def get_human_birthday(self, birthday: datetime):
        return str(birthday.strftime("%B")) + " " + str(birthday.strftime("%d").lstrip("0"))

    async def get_birthday(self, guild_id: int, user_id: int):
        birthdays = await self.get_guild_date_configs(guild_id)
        for bday_ordinal, bdays in birthdays.items():
            for user_id_config, year in bdays.items():
                if int(user_id_config) == user_id:
                    return datetime.datetime.fromordinal(int(bday_ordinal))
        return None

    async def check_breaking_change(self):
        await self.bot.wait_until_ready()
        previous = await self.config.custom(self.DATE_GROUP).all()
        if len(previous) > 0:
            await self.config.custom(self.DATE_GROUP).clear()
            owner = self.bot.get_user(self.bot.owner_id)
            if len(self.bot.guilds) == 1:
                await self.get_guild_date_config(self.bot.guilds[0].id).set_raw(value=previous)
                self.logger.info("Birthdays are now per-guild. Previous birthdays have been copied.")
            else:
                await self.config.custom(self.GUILD_DATE_GROUP, "backup").set_raw(value=previous)
                self.logger.info("Previous birthdays have been backed up in the config file.")

    def get_date_config(self, guild_id: int, date: int):
        return self.config.custom(self.GUILD_DATE_GROUP, str(guild_id), str(date))

    def get_guild_date_config(self, guild_id: int):
        return self.config.custom(self.GUILD_DATE_GROUP, str(guild_id))

    async def get_guild_date_configs(self, guild_id: int) -> _ValueCtxManager[Dict[str, Any]]:
        return await self.get_guild_date_config(guild_id).all()

    def get_all_date_configs(self):
        return self.config.custom(self.GUILD_DATE_GROUP).all()
