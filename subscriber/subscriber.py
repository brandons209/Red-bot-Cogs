from redbot.core import commands, Config, checks
from redbot.core.commands import Context, Cog
from redbot.core.utils.chat_formatting import *
from redbot.core.utils.menus import menu, DEFAULT_CONTROLS

import discord

import re
import asyncio
from dateutil.relativedelta import relativedelta
from datetime import datetime, timezone
from typing import Literal, Optional

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


class Subscriber(commands.Cog):
    """
    Automates subscriptions to roles to make donators and over roles easier to manage.
    """

    def __init__(self, bot):
        self.bot = bot

        self.config = Config.get_conf(self, identifier=74572674632164, force_registration=True)

        default_guild = {
            "dm_message": "Hello {member}! Just a friendly reminder your subscription to `{role}` will end on {end_date}. Please contact the staff to renew your role.",
            "subscribers": [],
            "reminder_time": "3 days",
        }

        # maps role id (str) -> end date in unix timestamp
        default_member = {"roles": {}, "reminded": {}}

        self.config.register_guild(**default_guild)
        self.config.register_member(**default_member)

        self.task = asyncio.create_task(self.initialize())

    @staticmethod
    def parse_timedelta(argument: str) -> Optional[relativedelta]:
        matches = TIME_RE.match(argument)
        if matches:
            params = {k: int(v) for k, v in matches.groupdict().items() if v}
            if params:
                return relativedelta(**params)
        return None

    def cog_unload(self):
        self.task.cancel()

    async def initialize(self):
        await self.bot.wait_until_ready()
        _guilds = [g for g in self.bot.guilds if g.large and not (g.chunked or g.unavailable)]
        await self.bot.request_offline_members(*_guilds)

        while True:
            now = datetime.now(tz=timezone.utc)
            for guild in self.bot.guilds:
                members = await self.config.guild(guild).subscribers()
                remind_time = self.parse_timedelta(await self.config.guild(guild).reminder_time())
                dm = await self.config.guild(guild).dm_message()
                rm_members = []
                for member in members:
                    member = guild.get_member(member)
                    if not member:
                        rm_members.append(member)
                        continue

                    roles = await self.config.member(member).roles()
                    reminders = await self.config.member(member).reminded()

                    to_remove = []
                    for role, end_date in roles.items():
                        role = guild.get_role(int(role))
                        end_date = datetime.fromtimestamp(end_date).astimezone(tz=timezone.utc)
                        if not role:
                            continue

                        if now > end_date:
                            try:
                                await member.remove_roles(role)
                            except discord.Forbidden:
                                continue

                            try:
                                await member.send(
                                    info(
                                        f"Your subscription to the role `{role}` in `{guild}` has expired and been removed."
                                    )
                                )
                            except:
                                pass
                            to_remove.append(str(role.id))
                            del reminders[str(role.id)]
                        elif (now + remind_time) > end_date and not reminders[str(role.id)]:
                            dm = dm.format(
                                role=role,
                                end_date=f"<t:{int(end_date.timestamp())}>",
                                member=member.mention,
                                guild=guild,
                            )
                            try:
                                await member.send(f"**Role Expiration Notice for {guild}**\n\n{dm}")
                                reminders[str(role.id)] = True
                            except:
                                pass
                        elif (now + remind_time) < end_date:
                            reminders[str(role.id)] = False

                    await self.config.member(member).reminded.set(reminders)
                    if to_remove:
                        for role in to_remove:
                            del roles[role]
                        await self.config.member(member).roles.set(roles)

                if rm_members:
                    for mem in rm_members:
                        members.remove(mem)
                    await self.config.guild(guild).subscribers.set(members)

            # sleep for 30 minutes
            await asyncio.sleep(1800)
            # await asyncio.sleep(15)

    @commands.group(name="subset")
    @checks.admin_or_permissions(administrator=True)
    @commands.guild_only()
    async def subset(self, ctx):
        """
        Set subscription settings
        """
        pass

    @subset.command(name="message")
    async def subset_message(self, ctx, *, msg: str = None):
        """
        Sets the reminder message sent to users when their subscription is about to end.

        Leave message as blank to view the current DM message.

        You can use these values below to represent the role, end date, etc automatically:
            - {role} will be replaced with the name of the role
            - {member} will be replaced with the member's username
            - {guild} will be replaced with the name of the guild
            - {end_date} will be replaced with the date and time the subscription will end
        """
        if msg is None:
            curr = await self.config.guild(ctx.guild).dm_message()
            await ctx.send(box(curr))
            return

        await self.config.guild(ctx.guild).dm_message.set(msg)
        await ctx.tick()

    @subset.command(name="reminder")
    async def subset_reminder(self, ctx, *, interval: str):
        """
        Set the time before the end of a user's subscription to remind them.

        Intervals can be:
            - 5 minutes
            - 1 minute 30 seconds
            - 1 hour
            - 2 days
            - 30 days
            - 5 months
            - 2 years
            (etc)
        """
        if not self.parse_timedelta(interval):
            await ctx.send(error("The interval is invalid, please try again."))
            return

        await self.config.guild(ctx.guild).reminder_time.set(interval)
        await ctx.tick()

    @commands.command(name="subadd")
    @checks.admin_or_permissions(administrator=True)
    @checks.bot_has_permissions(manage_roles=True)
    @commands.guild_only()
    async def subadd(self, ctx, role: discord.Role, member: discord.Member, *, duration: str):
        """
        Add a role and subscription to a member for the specified duration.
        """
        now = datetime.now(tz=timezone.utc)
        duration = self.parse_timedelta(duration)
        if not duration:
            await ctx.send(error("The duration is invalid, please try again."))
            return

        end_time = now + duration

        async with self.config.member(member).roles() as roles:
            if str(role.id) not in roles:
                try:
                    await member.add_roles(role)
                except discord.Forbidden:
                    await ctx.send(
                        error(
                            "I do not have permission to add this role, make sure the role is lower in the hierarchy then my top role."
                        )
                    )
                    return
                # role is converted to string since redbot will do it, so make it explict its a string
                roles[str(role.id)] = end_time.timestamp()
            else:
                await ctx.send(
                    error(
                        "The user is already subscribed to this role, please renew their subscription instead using `subrenew`."
                    )
                )
                return

        async with self.config.guild(ctx.guild).subscribers() as subs:
            if member.id not in subs:
                subs.append(member.id)

        async with self.config.member(member).reminded() as reminded:
            reminded[str(role.id)] = False

        try:
            await member.send(
                info(
                    f"You have been subscribed to the role `{role}` in `{ctx.guild}`.\nThe subscription will end on <t:{int(end_time.timestamp())}>"
                )
            )
        except:
            pass

        await ctx.tick()

    @commands.command(name="subrem")
    @checks.admin_or_permissions(administrator=True)
    @checks.bot_has_permissions(manage_roles=True)
    @commands.guild_only()
    async def subrem(self, ctx, role: discord.Role, member: discord.Member):
        """
        Manually remove a subscribed role from a member.
        """

        async with self.config.member(member).roles() as roles:
            if str(role.id) in roles:
                try:
                    await member.remove_roles(role)
                except discord.Forbidden:
                    await ctx.send(
                        error(
                            "I do not have permission to remove this role, make sure the role is lower in the hierarchy then my top role."
                        )
                    )
                    return
                del roles[str(role.id)]
            else:
                await ctx.send(error("The user is not subscribed to this role."))
                return

            if not roles:
                async with self.config.guild(ctx.guild).subscribers() as subs:
                    subs.remove(member.id)

        async with self.config.member(member).reminded() as reminded:
            del reminded[str(role.id)]

        try:
            await member.send(
                info(f"Your subscription to the role `{role}` in `{ctx.guild}` has been manually removed.")
            )
        except:
            pass

        await ctx.tick()

    @commands.command(name="subrenew")
    @checks.admin_or_permissions(administrator=True)
    @commands.guild_only()
    async def subrenew(self, ctx, role: discord.Role, member: discord.Member, *, duration: str):
        """
        Renew's a user's role subscription for the specified duration.
        """
        now = datetime.now(tz=timezone.utc)
        duration = self.parse_timedelta(duration)
        if not duration:
            await ctx.send(error("The duration is invalid, please try again."))
            return

        end_time = now + duration

        async with self.config.member(member).roles() as roles:
            if str(role.id) in roles:
                # role is converted to string since redbot will do it, so make it explict its a string
                roles[str(role.id)] = end_time.timestamp()
            else:
                await ctx.send(error("The user is not subscribed to this role."))
                return

        await ctx.tick()

    @commands.command(name="subviewall")
    @checks.admin_or_permissions(administrator=True)
    @commands.guild_only()
    async def subview_all(self, ctx):
        """
        View all subscriptions in the server
        """
        members = await self.config.guild(ctx.guild).subscribers()
        if not members:
            await ctx.send(error("No users have subscriptions in your server."), delete_after=60)
            return

        msg = ""
        for member in members:
            member = ctx.guild.get_member(member)
            if not member:
                continue

            msg += f"{member.mention}:\n"
            roles = await self.config.member(member).roles()
            for role, end_date in roles.items():
                role = ctx.guild.get_role(int(role))
                if not role:
                    continue
                msg += f"\t- `@{role.name}`: <t:{int(end_date)}>\n"

            msg += "\n"

        pages = list(pagify(msg, page_length=1700, delims=["\n"], priority=True))
        pages = [f"{page}\n\n-----------------\n**Page {i+1} of {len(pages)}**" for i, page in enumerate(pages)]

        if not pages:  # should never happen
            await ctx.send(
                error(
                    "There are subscribed users, but I couldn't get any of their information. Please contact the bot developer for help."
                ),
                delete_after=60,
            )
        else:
            await menu(ctx, pages, DEFAULT_CONTROLS)

    @commands.command(name="subview")
    @commands.guild_only()
    async def subview(self, ctx):
        """
        View your current subscriptions
        """
        member = ctx.author
        roles = await self.config.member(member).roles()

        if not roles:
            await ctx.send(info("You are not subscribed to any roles!"))
            return

        embeds = []
        embed = discord.Embed(title=f"Subscribed Roles", colour=member.colour)
        cnt = 0
        for role, end_date in roles.items():
            end_date = datetime.fromtimestamp(end_date).astimezone(tz=timezone.utc)
            embed.add_field(name=str(ctx.guild.get_role(int(role))), value=f"Ends on <t:{int(end_date.timestamp())}>")
            cnt += 1

            # to avoid embed limits
            if cnt > 25:
                embeds.append(embed)
                embed = discord.Embed(title=f"Subscribed Roles", colour=member.colour)
                cnt = 0

        embeds.append(embed)

        for embed in embeds:
            await ctx.send(embed=embed)

    async def red_delete_data_for_user(
        self, *, requester: Literal["discord_deleted_user", "owner", "user", "user_strict"], user_id: int,
    ):
        pass
