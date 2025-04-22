from zoneinfo import ZoneInfo
from redbot.core import commands, Config, checks
from redbot.core.commands.converter import parse_timedelta
from redbot.core.utils.chat_formatting import *
from redbot.core.utils.menus import menu, DEFAULT_CONTROLS
from redbot.core.utils.predicates import MessagePredicate
import discord

import asyncio
from dateutil.tz import tzlocal
from typing import Literal, Optional, List


class Subscriber(commands.Cog):
    """
    Automates subscriptions to roles to make donators and other roles easier to manage.
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

        self.task = asyncio.create_task(self.watch_loop())

    def cog_unload(self):
        self.task.cancel()

    async def watch_loop(self):
        await self.bot.wait_until_ready()
        while True:
            try:
                await self.subscriber_loop()
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[Subscriber] Internal loop crashed, restarting in 10s... {e}")
                await asyncio.sleep(10)

    async def subscriber_loop(self):
        while True:
            now = discord.utils.utcnow()
            for guild in self.bot.guilds:
                members = await self.config.guild(guild).subscribers()
                remind_time = parse_timedelta(await self.config.guild(guild).reminder_time())
                dm = await self.config.guild(guild).dm_message()
                rm_members: List[int] = []
                for member_id in members:
                    member = guild.get_member(member_id)
                    if not member:
                        rm_members.append(member_id)
                        continue

                    roles = await self.config.member(member).roles()
                    reminders = await self.config.member(member).reminded()

                    to_remove: List[str] = []
                    for role, end_date in roles.items():
                        role = guild.get_role(int(role))
                        end_date = discord.utils.utcnow().fromtimestamp(end_date).astimezone(ZoneInfo("UTC"))
                        if not role:
                            continue

                        if now > end_date:
                            try:
                                await member.remove_roles(role)
                            except:
                                continue  # TODO: send error to guild owner?

                            try:
                                await member.send(
                                    info(
                                        f"Subscription Notice\nYour subscription to the role `{role}` in `{guild}` has expired and been removed."
                                    )
                                )
                            except:
                                pass
                            to_remove.append(str(role.id))
                            del reminders[str(role.id)]
                        elif remind_time is not None and (now + remind_time) > end_date and not reminders[str(role.id)]:
                            dm = dm.format(
                                role=role,
                                end_date=f"<t:{int(end_date.astimezone(tzlocal()).timestamp())}>",
                                member=member.mention,
                                guild=guild,
                            )
                            try:
                                await member.send(f"# **Role Expiration Notice for {guild}**\n\n{dm}")
                                reminders[str(role.id)] = True
                            except:
                                pass
                        elif remind_time is not None and (now + remind_time) < end_date:
                            reminders[str(role.id)] = False

                    await self.config.member(member).reminded.set(reminders)
                    if to_remove:
                        for role in to_remove:
                            del roles[role]
                        await self.config.member(member).roles.set(roles)
                    # if they are subscribed to no more roles, remove them from the list
                    if not roles:
                        rm_members.append(member_id)

                if rm_members:
                    for mem in rm_members:
                        members.remove(mem)
                    await self.config.guild(guild).subscribers.set(members)

            # sleep for 5 minutes
            await asyncio.sleep(300)
            # await asyncio.sleep(15)

    @commands.hybrid_group(name="subscriber")
    @commands.guild_only()
    async def subscriber(self, ctx: commands.Context):
        """
        Manage your server role subscriptions.
        """
        pass

    @subscriber.command(name="message")
    @checks.admin_or_permissions(administrator=True)
    async def subset_message(self, ctx, *, msg: Optional[str] = None):
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

    @subscriber.command(name="reminder")
    @checks.admin_or_permissions(administrator=True)
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
        if not parse_timedelta(interval):
            await ctx.reply(error("The interval is invalid, please try again."), delete_after=30, mention_author=False)
            return

        await self.config.guild(ctx.guild).reminder_time.set(interval)
        await ctx.tick()

    @subscriber.command(name="add")
    @checks.admin_or_permissions(administrator=True)
    @checks.bot_has_permissions(manage_roles=True)
    async def subadd(self, ctx: commands.Context, role: discord.Role, member: discord.Member, *, duration: str):
        """
        Add or renew a role subscription to a member for the specified duration.
        """
        now = discord.utils.utcnow()
        parsed_duration = parse_timedelta(duration)
        if not parsed_duration:
            await ctx.reply(error("The duration is invalid, please try again."), delete_after=30, mention_author=False)
            return

        end_time = now + parsed_duration
        msg = ""
        async with self.config.member(member).roles() as roles:
            if str(role.id) not in roles:
                try:
                    await member.add_roles(role)
                except discord.Forbidden:
                    await ctx.reply(
                        error(
                            "I do not have permission to add this role, make sure the role is lower in the hierarchy then my top role."
                        ),
                        delete_after=30,
                        mention_author=False,
                    )
                    return
                # role is converted to string since redbot will do it, so make it explict its a string
                roles[str(role.id)] = end_time.timestamp()
                msg = info(
                    f"Subscription Notice\nYou have been subscribed to the role `{role}` in `{ctx.guild}`.\nThe subscription will end on <t:{int(end_time.astimezone(tzlocal()).timestamp())}>."
                )
            else:
                # already subscribed, ask to renew
                await ctx.send(
                    info(
                        f"{member.mention} is already subscribed to `{role.name}`, would you like to renew this subscription?"
                    )
                )
                pred = MessagePredicate.yes_or_no(ctx)
                try:
                    await self.bot.wait_for("message", check=pred, timeout=60)
                except asyncio.TimeoutError:
                    await ctx.reply(warning("Timed out, cancelling renewal."), mention_author=False)
                    return
                if not pred.result:
                    await ctx.reply(info("Cancelling renewal"), mention_author=False)
                    return
                # renew role
                roles[str(role.id)] = end_time.timestamp()
                msg = info(
                    f"Subscription Notice\nYour subscription to `{role.name}` in `{ctx.guild}` has been renewed.\nThe subscription will now end on <t:{int(end_time.astimezone(tzlocal()).timestamp())}>."
                )

        async with self.config.guild(ctx.guild).subscribers() as subs:
            # user's first subscription
            if member.id not in subs:
                subs.append(member.id)

        async with self.config.member(member).reminded() as reminded:
            reminded[str(role.id)] = False

        try:
            await member.send(msg)
        except:
            await ctx.reply(
                warning(f"I could not DM the user, make sure to tell them they have acquired `{role.name}`."),
                mention_author=False,
            )

        await ctx.tick()

    @subscriber.command(name="rem", alias="del")
    @checks.admin_or_permissions(administrator=True)
    @checks.bot_has_permissions(manage_roles=True)
    async def subrem(self, ctx: commands.Context, role: discord.Role, member: discord.Member):
        """
        Manually remove a subscribed role from a member.
        """

        async with self.config.member(member).roles() as roles:
            if str(role.id) in roles:
                try:
                    await member.remove_roles(role)
                except discord.Forbidden:
                    await ctx.reply(
                        error(
                            "I do not have permission to remove this role, make sure the role is lower in the hierarchy then my top role."
                        ),
                        delete_after=30,
                        mention_author=False,
                    )
                    return
                del roles[str(role.id)]
            else:
                await ctx.reply(
                    error("The user is not subscribed to this role."), delete_after=30, mention_author=False
                )
                return

            # if they have no other subscriptions, remove them from the subscriber list
            if not roles:
                async with self.config.guild(ctx.guild).subscribers() as subs:
                    subs.remove(member.id)
                    subs = list(set(subs))

        async with self.config.member(member).reminded() as reminded:
            del reminded[str(role.id)]

        try:
            await member.send(
                info(
                    f"Subscription Notice\nYour subscription to the role `{role}` in `{ctx.guild}` has been manually removed. If you believe this is an error, please contact a staff member in the server."
                )
            )
        except:
            await ctx.reply(
                warning(f"I could not DM the user, make sure to tell them they have lost `{role.name}`."),
                mention_author=False,
            )

        await ctx.tick()

    @subscriber.command(name="viewall")
    @checks.admin_or_permissions(administrator=True)
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

            roles = await self.config.member(member).roles()
            if not roles:
                continue
            msg += f"{member.mention}:\n"
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

    @subscriber.command(name="view")
    async def subview(self, ctx):
        """
        View your current subscriptions
        """
        member = ctx.author
        roles = await self.config.member(member).roles()

        if not roles:
            await ctx.reply(info("You are not subscribed to any roles!"), delete_after=60, mention_author=False)
            return

        embeds = []
        embed = discord.Embed(title=f"Subscribed Roles", colour=member.colour)
        cnt = 0
        for role, end_date in roles.items():
            end_date = discord.utils.utcnow().fromtimestamp(end_date)
            embed.add_field(
                name=str(ctx.guild.get_role(int(role))),
                value=f"Ends on <t:{int(end_date.astimezone(tzlocal()).timestamp())}>",
            )
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
        self,
        *,
        requester: Literal["discord_deleted_user", "owner", "user", "user_strict"],
        user_id: int,
    ):
        pass
