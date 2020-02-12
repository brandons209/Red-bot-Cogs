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
    BDAY_WITH_YEAR = _(
        "<@!{}> is now **{} years old**. <:aureliahappy:548738609763713035>"
    )
    BDAY_WITHOUT_YEAR = _(
        "Everypony say Happy Hirthday to <@!{}>! <:aureliahappy:548738609763713035>"
    )
    ROLE_SET = _(
        "<:aureliaagree:616091883013144586> The birthday role on **{g}** has been set to: **{r}**."
    )
    BDAY_INVALID = _(":x: The birthday date you entered is invalid.")
    BDAY_SET = _(
        "<:aureliaagree:616091883013144586> Your birthday has been set to: **{}**."
    )
    CHANNEL_SET = _(
        "<:aureliaagree:616091883013144586> "
        "The channel for announcing birthdays on **{g}** has been set to: **{c}**."
    )
    BDAY_REMOVED = _(":put_litter_in_its_place: Your birthday has been removed.")
    BDAY_DM = _(":tada: Aurelia wishes you a very happy birthday! :tada:")

    def __init__(self, bot):
        super().__init__()
        self.bot = bot
        self.logger = logging.getLogger("aurelia.cogs.birthdays")
        unique_id = int(
            hashlib.sha512(
                (self.__author__ + "@" + self.__class__.__name__).encode()
            ).hexdigest(),
            16,
        )
        self.config = Config.get_conf(self, identifier=unique_id)
        self.config.init_custom(self.DATE_GROUP, 1)
        self.config.init_custom(self.GUILD_DATE_GROUP, 2)
        self.config.register_guild(channel=None, role=None, yesterdays=[])
        self.bday_loop = asyncio.ensure_future(self.initialise())
        asyncio.ensure_future(self.check_breaking_change())

    # Events
    async def initialise(self):
        await self.bot.wait_until_ready()
        with contextlib.suppress(RuntimeError):
            while self == self.bot.get_cog(self.__class__.__name__):
                now = datetime.datetime.utcnow()
                tomorrow = (now + datetime.timedelta(days=1)).replace(
                    hour=0, minute=0, second=0, microsecond=0
                )
                await self.clean_yesterday_bdays()
                await self.do_today_bdays()
                await asyncio.sleep((tomorrow - now).total_seconds())

    def cog_unload(self):
        self.bday_loop.cancel()

    # Commands
    @commands.group()
    @commands.guild_only()
    async def bday(self, ctx: Context):
        """Birthday settings"""
        pass

    @bday.command(name="channel")
    @checks.mod_or_permissions(manage_roles=True)
    async def bday_channel(self, ctx: Context, channel: discord.TextChannel):
        """Sets the birthday announcement channel"""
        message = ctx.message
        guild = message.guild
        await self.config.guild(channel.guild).channel.set(channel.id)
        await message.channel.send(self.CHANNEL_SET(g=guild.name, c=channel.name))

    @bday.command(name="role")
    @checks.mod_or_permissions(manage_roles=True)
    async def bday_role(self, ctx: Context, *, role: discord.Role):
        """Sets the birthday role"""
        message = ctx.message
        guild = message.guild
        await self.config.guild(role.guild).role.set(role.id)
        await message.channel.send(self.ROLE_SET(g=guild.name, r=role.name))

    @bday.command(name="remove", aliases=["del", "clear", "rm"])
    async def bday_remove(self, ctx: Context):
        """Unsets your birthday date"""
        message = ctx.message
        await self.remove_user_bday(message.guild.id, message.author.id)
        await message.channel.send(self.BDAY_REMOVED())

    @bday.command(name="set")
    async def bday_set(self, ctx: Context, *, date: str):
        """Sets your birthday date

        The given date can either be month day, or day month
        Year is optional. If not given, the age won't be displayed."""
        message = ctx.message
        channel = message.channel
        author = message.author
        year = None
        birthday = self.parse_date(date)
        # An Invalid date was entered.
        if birthday is None:
            print(self.BDAY_INVALID())
            await channel.send(self.BDAY_INVALID())
        else:
            print(type(birthday))
            if datetime.datetime.utcnow().year != birthday.year:
                year = birthday.year
            birthday = datetime.date(1, birthday.month, birthday.day)
            await self.remove_user_bday(message.guild.id, author.id)
            await self.get_date_config(message.guild.id, birthday.toordinal()).get_attr(
                author.id
            ).set(year)
            bday_month_str = birthday.strftime("%B")
            bday_day_str = birthday.strftime("%d").lstrip("0")

            await channel.send(self.BDAY_SET(bday_month_str + " " + bday_day_str))

    @bday.command(name="list")
    async def bday_list(self, ctx: Context):
        """Lists birthdays

        If a user has their year set, it will display the age they'll get after their birthday this year"""
        message = ctx.message
        await self.clean_bdays()
        bdays = await self.get_guild_date_configs(message.guild.id)
        this_year = datetime.date.today().year
        embed = discord.Embed(
            title=self.BDAY_LIST_TITLE(), color=discord.Colour.lighter_grey()
        )
        for k, g in itertools.groupby(
            sorted(datetime.datetime.fromordinal(int(o)) for o in bdays.keys()),
            lambda i: i.month,
        ):

            value = "\n".join(
                date.strftime("%d").lstrip("0")
                + ": "
                + ", ".join(
                    "<@!{}>".format(u_id)
                    + ("" if year is None else " ({})".format(this_year - int(year)))
                    for u_id, year in bdays.get(str(date.toordinal()), {}).items()
                )
                for date in g
                if len(bdays.get(str(date.toordinal()))) > 0
            )
            if not value.isspace():
                embed.add_field(
                    name=datetime.datetime(year=1, month=k, day=1).strftime("%B"),
                    value=value,
                )
        await message.channel.send(embed=embed)

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
        if year is not None:
            age = datetime.date.today().year - int(year)
            embed.description = self.BDAY_WITH_YEAR(user_id, age)
        else:
            embed.description = self.BDAY_WITHOUT_YEAR(user_id)
        all_guild_configs = await self.config.all_guilds()
        for guild_id, guild_config in all_guild_configs.items():
            guild = self.bot.get_guild(guild_id)
            if guild is not None:
                member = guild.get_member(user_id)
                if member is not None:
                    role_id = guild_config.get("role")
                    if role_id is not None:
                        role = discord.utils.get(guild.roles, id=role_id)
                        if role is not None:
                            try:
                                await member.add_roles(role)
                            except (discord.Forbidden, discord.HTTPException):
                                pass
                            else:
                                async with self.config.guild(
                                    guild
                                ).yesterdays() as yesterdays:
                                    yesterdays.append(member.id)
                    channel = guild.get_channel(guild_config.get("channel"))
                    if channel is not None:
                        await channel.send(embed=embed)
                        await member.send(self.BDAY_DM())

    async def clean_bdays(self):
        birthdays = await self.get_all_date_configs()
        for guild_id, guild_bdays in birthdays.items():
            for date, bdays in guild_bdays.items():
                for user_id, year in bdays.items():
                    if not any(
                        g.get_member(int(user_id)) is not None for g in self.bot.guilds
                    ):
                        async with self.get_date_config(
                            guild_id, date
                        )() as config_bdays:
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

    async def clean_yesterday_bdays(self):
        all_guild_configs = await self.config.all_guilds()
        for guild_id, guild_config in all_guild_configs.items():
            for user_id in guild_config.get("yesterdays", []):
                asyncio.ensure_future(self.clean_bday(guild_id, guild_config, user_id))
            await self.config.guild(
                discord.Guild(data={"id": guild_id}, state=None)
            ).yesterdays.clear()

    async def do_today_bdays(self):
        guild_configs = await self.get_all_date_configs()
        for guild_id, guild_config in guild_configs.items():
            this_date = datetime.datetime.utcnow().date().replace(year=1)
            todays_bday_config = guild_config.get(str(this_date.toordinal()), {})
            for user_id, year in todays_bday_config.items():
                asyncio.ensure_future(self.handle_bday(int(user_id), year))

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

    async def check_breaking_change(self):
        await self.bot.wait_until_ready()
        previous = await self.config.custom(self.DATE_GROUP).all()
        if len(previous) > 0:
            await self.config.custom(self.DATE_GROUP).clear()
            owner = self.bot.get_user(self.bot.owner_id)
            if len(self.bot.guilds) == 1:
                await self.get_guild_date_config(self.bot.guilds[0].id).set_raw(
                    value=previous
                )
                self.logger.info(
                    "Birthdays are now per-guild. Previous birthdays have been copied."
                )
            else:
                await self.config.custom(self.GUILD_DATE_GROUP, "backup").set_raw(
                    value=previous
                )
                self.logger.info(
                    "Previous birthdays have been backed up in the config file."
                )

    def get_date_config(self, guild_id: int, date: int):
        return self.config.custom(self.GUILD_DATE_GROUP, str(guild_id), str(date))

    def get_guild_date_config(self, guild_id: int):
        return self.config.custom(self.GUILD_DATE_GROUP, str(guild_id))

    async def get_guild_date_configs(
        self, guild_id: int
    ) -> _ValueCtxManager[Dict[str, Any]]:
        return await self.get_guild_date_config(guild_id).all()

    def get_all_date_configs(self):
        return self.config.custom(self.GUILD_DATE_GROUP).all()
