# redbot/discord
from locale import currency
from textwrap import shorten
from redbot.core.utils.chat_formatting import *
from redbot.core import Config, checks, commands, bank
from redbot.core.utils.predicates import ReactionPredicate
from redbot.core.utils.menus import start_adding_reactions
import discord

import re
import asyncio
from datetime import datetime
from dateutil.relativedelta import relativedelta
from typing import Optional

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


def parse_timedelta(argument: str) -> Optional[relativedelta]:
    matches = TIME_RE.match(argument)
    if matches:
        params = {k: int(v) for k, v in matches.groupdict().items() if v}
        if params:
            return relativedelta(**params)
    return None


NO_NICKNAME = "#" * 40


class NameChange(commands.Cog):
    """
    Allow users to pay currency to change someone's name for a time period.
    """

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=574243463248323838, force_registration=True)

        default_guild = {
            "allowed_roles": [],
            "allowed_users": [],
            "cost_per_minute": 0,
            "current_changes": {},
        }
        self.config.register_guild(**default_guild)

        self.task = asyncio.create_task(self.init())

    async def init(self):
        await self.bot.wait_until_ready()

        while True:
            await self.update_namechanges()
            print("big update")
            await asyncio.sleep(60)

    def cog_unload(self):
        if self.task is not None:
            self.task.cancel()

    async def update_namechanges(self):
        for guild in self.bot.guilds:
            to_remove = []
            to_change = {}
            for member_id, data in (await self.config.guild(guild).current_changes()).items():
                now = datetime.now()
                end_time = datetime.fromtimestamp(data["end_time"])
                member = guild.get_member(int(member_id))

                if member is None:
                    to_remove.append(member_id)
                    continue

                if now > end_time:
                    # name change is past due
                    to_change[member] = data
                    to_remove.append(member_id)

            async with self.config.guild(guild).current_changes() as current_changes:
                for id in to_remove:
                    del current_changes[id]

            # have to change usernames back after current_changes gets updated
            for member, data in to_change.items():
                if data["old_nick"] == NO_NICKNAME:
                    await self.change_nickname(member, None)
                else:
                    await self.change_nickname(member, data["old_nick"])

    async def check_can_change(self, member: discord.Member):
        roles = await self.config.guild(member.guild).allowed_roles()
        members = await self.config.guild(member.guild).allowed_users()

        for role in member.roles:
            if role.id in roles:
                return True

        if member.id in members:
            return True

        return False

    @staticmethod
    async def change_nickname(member: discord.Member, nick: str):
        try:
            await member.edit(nick=nick)
            return True
        except discord.Forbidden:
            return False
        except discord.HTTPException:
            return False

    @commands.command()
    async def test(self, ctx):
        await self.update_namechanges()

    @commands.group(name="name", invoke_without_command=True)
    @commands.guild_only()
    @checks.bot_has_permissions(manage_nicknames=True)
    async def namechange(self, ctx, member: discord.Member, time: str, *, new_name: str):
        """
        Set someone's Nickname using bot currency

        Time should be a combination of s, m, h, d, w in this format:
            `5m30s` = 5 minutes 30 seconds
            `1w3d` = 1 week 3 days
            `10m` = 10 minutes
            etc...
        """
        if ctx.invoked_subcommand:
            return
        elif member is not None:
            time = parse_timedelta(time)
            if time is None:
                await ctx.send(error("Invalid time interval!"), delete_after=30)
                return

            if len(new_name) > 32 or len(new_name) < 2:
                await ctx.send(error("Nickname must be 2 to 32 characters in length!"), delete_after=30)
                return

            if not (await self.check_can_change(member)):
                await ctx.send(error("That user cannot have their name changed!"), delete_after=30)
                return

            now = datetime.now()
            time = (now + time) - now  # convert from relative delta to time delta

            cost = await self.config.guild(ctx.guild).cost_per_minute()
            currency_name = await bank.get_currency_name(ctx.guild)
            total_cost = int(time.total_seconds() / 60 * cost)
            current = await self.config.guild(ctx.guild).current_changes()

            if str(member.id) in current:
                end_time = current[str(member.id)]["end_time"]
                await ctx.send(
                    error(
                        f"{member} already has their name changed! Please wait until <t:{end_time}> to change their name again."
                    )
                )
                return

            msg = await ctx.send(
                f"The total cost to change {member}'s name will be {total_cost} {currency_name}, continue?",
                delete_after=31,
            )
            start_adding_reactions(msg, ReactionPredicate.YES_OR_NO_EMOJIS)
            pred = ReactionPredicate.yes_or_no(msg, ctx.author)

            try:
                await self.bot.wait_for("reaction_add", check=pred, timeout=30)
            except asyncio.TimeoutError:
                await ctx.send(error("Took too long, name change is cancelled!"), delete_after=30)
                return

            if not pred.result:
                await ctx.send("Name change cancelled, you were not charged.")
                return

            try:
                await bank.withdraw_credits(ctx.author, total_cost)
            except ValueError:
                await ctx.send(
                    f"You do not have enough {currency_name}! Cost: {total_cost}, balance: {await bank.get_balance(ctx.author)}"
                )
                return

            now = datetime.now()
            data = {
                "old_nick": member.nick if member.nick is not None else NO_NICKNAME,
                "new_nick": new_name,
                "end_time": int((now + time).astimezone(now.astimezone().tzinfo).timestamp()),
                "author": ctx.author.id,
            }

            async with self.config.guild(ctx.guild).current_changes() as current_changes:
                current_changes[str(member.id)] = data

            await self.change_nickname(member, new_name)
            await ctx.send(f"{member}'s nickname changed to {new_name} until <t:{data['end_time']}>.")

            try:
                await member.send(
                    info(
                        f"**Name changed in {ctx.guild}**\n\nYour name was changed to `{new_name}` by {ctx.author.mention} until <t:{data['end_time']}>."
                    )
                )
            except:
                pass

    @namechange.command(name="setcost")
    @checks.admin()
    async def namechange_setcost(self, ctx, cost: int = None):
        """
        Set the cost **per minute** to change someone's name
        """
        if cost is None:
            currency_name = await bank.get_currency_name(ctx.guild)
            current = await self.config.guild(ctx.guild).cost_per_minute()
            await ctx.send(f"Current cost per minute to change someone's name: {current} {currency_name}")
            return

        if cost < 0:
            await ctx.send(error("Cost must be greater than or equal to 0."), delete_after=30)
            return

        await self.config.guild(ctx.guild).cost_per_minute.set(cost)
        await ctx.tick()

    @namechange.group(name="roles")
    @checks.admin()
    async def namechange_roles(self, ctx):
        """
        Set the roles that allow name changing
        """
        pass

    @namechange_roles.command(name="add")
    async def namechange_roles_add(self, ctx, *, role: discord.Role):
        """
        Add a role for name changing
        """
        async with self.config.guild(ctx.guild).allowed_roles() as allowed_roles:
            if role.id not in allowed_roles:
                allowed_roles.append(role.id)
                await ctx.tick()
            else:
                await ctx.send(error(f"`{role}` is already added!"), delete_after=30)

    @namechange_roles.command(name="del")
    async def namechange_roles_del(self, ctx, *, role: discord.Role):
        """
        Remove a role from name changing
        """
        async with self.config.guild(ctx.guild).allowed_roles() as allowed_roles:
            if role.id in allowed_roles:
                allowed_roles.remove(role.id)
                await ctx.tick()
            else:
                await ctx.send(error(f"`{role}` is not in the allowed list!"), delete_after=30)

    @namechange_roles.command(name="list")
    async def namechange_roles_list(self, ctx):
        """
        View all roles that allow name changing.
        """
        roles = await self.config.guild(ctx.guild).allowed_roles()
        roles = [ctx.guild.get_role(r) for r in roles]

        msg = [f"{r.mention}\n" for r in roles if r is not None]
        msg = "Current roles:\n" + "".join(msg)

        for page in pagify(msg, page_length=1800, shorten_by=22):
            await ctx.send(page)

    @namechange.group(name="user")
    @checks.admin()
    async def namechange_user(self, ctx):
        """
        Set specific users that allow name changing
        """
        pass

    @namechange_user.command(name="add")
    async def namechange_user_add(self, ctx, *, member: discord.Member):
        """
        Add a member for name changing
        """
        async with self.config.guild(ctx.guild).allowed_users() as allowed_users:
            if member.id not in allowed_users:
                allowed_users.append(member.id)
                await ctx.tick()
            else:
                await ctx.send(error(f"`{member}` is already added!"), delete_after=30)

    @namechange_user.command(name="del")
    async def namechange_user_del(self, ctx, *, member: discord.Member):
        """
        Remove a member from name changing
        """
        async with self.config.guild(ctx.guild).allowed_users() as allowed_users:
            if member.id in allowed_users:
                allowed_users.remove(member.id)
                await ctx.tick()
            else:
                await ctx.send(error(f"`{member}` is not in the allowed list!"), delete_after=30)

    @namechange_user.command(name="list")
    async def namechange_user_list(self, ctx):
        """
        View all members that allow name changing.
        """
        members = await self.config.guild(ctx.guild).allowed_users()
        members = [ctx.guild.get_member(m) for m in members]

        msg = [f"{m.mention}\n" for m in members if m is not None]
        msg = "Current members:\n" + "".join(msg)

        for page in pagify(msg, page_length=1800, shorten_by=22):
            await ctx.send(page)

    @namechange.command(name="cost")
    async def namechange_cost(self, ctx):
        """
        Get the cost of changing someone's name
        """
        current_cost = await self.config.guild(ctx.guild).cost_per_minute()
        currency_name = await bank.get_currency_name(ctx.guild)

        await ctx.send(
            info(f"It costs {current_cost} {currency_name} **per minute** to change someone's name."), delete_after=30,
        )

    @namechange.command(name="remove")
    @checks.admin()
    async def namechange_remove(self, ctx, *, member: discord.Member):
        """
        Manually remove someone's name change.
        """
        data = None
        async with self.config.guild(ctx.guild).current_changes() as current_changes:
            if str(member.id) in current_changes:
                data = current_changes[str(member.id)]
                del current_changes[str(member.id)]

        if data is not None:
            if data["old_nick"] == NO_NICKNAME:
                await self.change_nickname(member, None)
            else:
                await self.change_nickname(member, data["old_nick"])

        await ctx.tick()

    @namechange.command(name="list")
    @checks.admin()
    async def namechange_list(self, ctx):
        """
        List all users who have their name changed.
        """
        current = await self.config.guild(ctx.guild).current_changes()

        msg = ""
        for member_id, data in current.items():
            member = ctx.guild.get_member(int(member_id))
            if not member:
                continue

            author = ctx.guild.get_member(data["author"])
            author = "Unknown User" if author is None else author.mention
            msg += f"{member.mention}:\n\t-Changed by {author}\n\t-Ends on <t:{data['end_time']}>\n\n"

        if len(msg) == 0:
            msg = "No users currently have their name changed!"

        for page in pagify(msg):
            await ctx.send(page)

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        # check if nickname changed
        if before.nick != after.nick:
            current = await self.config.guild(before.guild).current_changes()
            if str(before.id) in current and current[str(before.id)]["new_nick"] != after.nick:
                await self.change_nickname(after, current[str(before.id)]["new_nick"])

