from __future__ import annotations

import contextlib
import asyncio
import re
import time
from abc import ABCMeta
from typing import AsyncIterator, Tuple, Optional, Union, List, Dict

import discord
from discord.ext.commands import CogMeta as DPYCogMeta
from redbot.core import checks, commands, bank
from redbot.core.config import Config
from redbot.core.utils.chat_formatting import box, pagify, warning, humanize_list

from .events import EventMixin
from .exceptions import (
    RoleManagementException,
    PermissionOrHierarchyException,
    MissingRequirementsException,
    ConflictingRoleException,
)
from .massmanager import MassManagementMixin
from .utils import UtilMixin, variation_stripper_re, parse_timedelta, parse_seconds

try:
    from redbot.core.commands import GuildContext
except ImportError:
    from redbot.core.commands import Context as GuildContext  # type: ignore

# This previously used ``(type(commands.Cog), type(ABC))``
# This was changed to be explicit so that mypy
# would be slightly happier about it.
# This does introduce a potential place this
# can break in the future, but this would be an
# Upstream breaking change announced in advance
class CompositeMetaClass(DPYCogMeta, ABCMeta):
    """
    This really only exists because of mypy
    wanting mixins to be individually valid classes.
    """

    pass  # MRO is fine on __new__ with super() use
    # no need to manually ensure both get handled here.


MIN_SUB_TIME = 3600
SLEEP_TIME = 300
MAX_EMBED = 25


class RoleManagement(
    UtilMixin, MassManagementMixin, EventMixin, commands.Cog, metaclass=CompositeMetaClass,
):
    """
    Cog for role management
    """

    __author__ = "mikeshardmind(Sinbad), DiscordLiz"
    __version__ = "323.1.4"

    def format_help_for_context(self, ctx):
        pre_processed = super().format_help_for_context(ctx)
        return f"{pre_processed}\nCog Version: {self.__version__}"

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=78631113035100160, force_registration=True)
        self.config.register_global(handled_variation=False, handled_full_str_emoji=False)
        self.config.register_role(
            exclusive_to={},
            requires_any=[],
            requires_all=[],
            sticky=False,
            self_removable=False,
            self_role=False,
            protected=False,
            cost=0,
            subscription=0,
            subscribed_users={},
            dm_msg=None,
        )  # subscribed_users maps str(user.id)-> end time in unix timestamp
        self.config.register_member(roles=[], forbidden=[])
        self.config.init_custom("REACTROLE", 2)
        self.config.register_custom(
            "REACTROLE", roleid=None, channelid=None, guildid=None
        )  # ID : Message.id, str(React)
        self.config.register_guild(notify_channel=None, s_roles=[], free_roles=[], join_roles=[])
        self._ready = asyncio.Event()
        self._start_task: Optional[asyncio.Task] = None
        self.loop = asyncio.get_event_loop()
        self._sub_task = self.loop.create_task(self.sub_checker())
        # remove selfrole commands since we are going to override them
        self.bot.remove_command("selfrole")
        super().__init__()

    def cog_unload(self):
        if self._start_task:
            self._start_task.cancel()
        if self._sub_task:
            self._sub_task.cancel()

    def init(self):
        self._start_task = asyncio.create_task(self.initialization())
        self._start_task.add_done_callback(lambda f: f.result())

    async def initialization(self):
        data: Dict[str, Dict[str, Dict[str, Union[int, bool, List[int]]]]]
        await self.bot.wait_until_red_ready()
        if not await self.config.handled_variation():
            data = await self.config.custom("REACTROLE").all()
            to_adjust = {}
            for message_id, emojis_to_data in data.items():
                for emoji_key in emojis_to_data:
                    new_key, c = variation_stripper_re.subn("", emoji_key)
                    if c:
                        to_adjust[(message_id, emoji_key)] = new_key

            for (message_id, emoji_key), new_key in to_adjust.items():
                data[message_id][new_key] = data[message_id][emoji_key]
                data[message_id].pop(emoji_key, None)

            await self.config.custom("REACTROLE").set(data)
            await self.config.handled_variation.set(True)

        if not await self.config.handled_full_str_emoji():
            data = await self.config.custom("REACTROLE").all()
            to_adjust = {}
            pattern = re.compile(r"^(<?a?:)?([A-Za-z0-9_]+):([0-9]+)(\:?>?)$")
            # Am not a fan....
            for message_id, emojis_to_data in data.items():
                for emoji_key in emojis_to_data:
                    new_key, c = pattern.subn(r"\3", emoji_key)
                    if c:
                        to_adjust[(message_id, emoji_key)] = new_key

            for (message_id, emoji_key), new_key in to_adjust.items():
                data[message_id][new_key] = data[message_id][emoji_key]
                data[message_id].pop(emoji_key, None)

            await self.config.custom("REACTROLE").set(data)
            await self.config.handled_full_str_emoji.set(True)

        self._ready.set()

    async def wait_for_ready(self):
        await self._ready.wait()

    async def cog_before_invoke(self, ctx):
        await self.wait_for_ready()
        if ctx.guild:
            await self.maybe_update_guilds(ctx.guild)

    # makes it a bit more readable
    async def sub_helper(self, guild, role, role_data):
        for user_id in list(role_data["subscribed_users"].keys()):
            end_time = role_data["subscribed_users"][user_id]
            now_time = time.time()
            if end_time <= now_time:
                member = guild.get_member(int(user_id))
                if not member:  # clean absent members
                    del role_data["subscribed_users"][user_id]
                    continue
                # make sure they still have the role
                if role not in member.roles:
                    del role_data["subscribed_users"][user_id]
                    continue
                # charge user
                cost = await self.config.role(role).cost()
                currency_name = await bank.get_currency_name(guild)
                curr_sub = await self.config.role(role).subscription()
                if cost == 0 or curr_sub == 0:
                    # role is free now or sub is removed, remove stale sub
                    del role_data["subscribed_users"][user_id]
                    continue

                msg = f"Hello! You are being charged {cost} {currency_name} for your subscription to the {role.name} role in {guild.name}."
                try:
                    await bank.withdraw_credits(member, cost)
                    msg += f"\n\nNo further action is required! You'll be charged again in {parse_seconds(curr_sub)}."
                    role_data["subscribed_users"][user_id] = now_time + curr_sub
                except ValueError:  # user is poor
                    msg += f"\n\nHowever, you do not have enough {currency_name} to cover the subscription. The role will be removed."
                    await self.update_roles_atomically(who=member, remove=[role])
                    del role_data["subscribed_users"][user_id]

                try:
                    await member.send(msg)
                except:
                    # trys to send in system channel, if that fails then
                    # send message in first channel bot can speak in
                    channel = guild.system_channel
                    msg += f"\n\n{member.mention} make sure to allow receiving DM's from server members so I can DM you this message!"
                    if channel.permissions_for(channel.guild.me).send_messages:
                        await channel.send(msg)
                    else:
                        for channel in guild.text_channels:
                            if channel.permissions_for(channel.guild.me).send_messages:
                                await channel.send(msg)
                                break

        return role_data

    async def sub_checker(self):
        await self.wait_for_ready()
        while True:
            await asyncio.sleep(SLEEP_TIME)
            for guild in self.bot.guilds:
                async with self.config.guild(guild).s_roles() as s_roles:
                    for role_id in reversed(s_roles):
                        role = guild.get_role(role_id)
                        if not role:  # clean stale subs if role is deleted
                            s_roles.remove(role_id)
                            continue

                        role_data = await self.config.role(role).all()

                        role_data = await self.sub_helper(guild, role, role_data)

                        await self.config.role(role).subscribed_users.set(role_data["subscribed_users"])
                        if len(role_data["subscribed_users"]) == 0:
                            s_roles.remove(role_id)

    @commands.guild_only()
    @commands.bot_has_permissions(manage_roles=True)
    @checks.admin_or_permissions(manage_roles=True)
    @commands.command(name="hackrole")
    async def hackrole(self, ctx: GuildContext, user_id: int, *, role: discord.Role):
        """
        Puts a stickyrole on someone not in the server.
        """

        if not await self.all_are_valid_roles(ctx, role):
            return await ctx.maybe_send_embed("Can't do that. Discord role heirarchy applies here.")

        if not await self.config.role(role).sticky():
            return await ctx.send("This only works on sticky roles.")

        member = ctx.guild.get_member(user_id)
        if member:

            try:
                await self.update_roles_atomically(who=member, give=[role])
            except PermissionOrHierarchyException:
                await ctx.send("Can't, somehow")
            else:
                await ctx.maybe_send_embed("They are in the guild...assigned anyway.")
        else:

            async with self.config.member_from_ids(ctx.guild.id, user_id).roles() as sticky:
                if role.id not in sticky:
                    sticky.append(role.id)

            await ctx.tick()

    @checks.is_owner()
    @commands.command(name="rrcleanup", hidden=True)
    async def rolemanagementcleanup(self, ctx: GuildContext):
        """ :eyes: """
        data = await self.config.custom("REACTROLE").all()

        key_data = {}

        for maybe_message_id, maybe_data in data.items():
            try:
                message_id = int(maybe_message_id)
            except ValueError:
                continue

            ex_keys = list(maybe_data.keys())
            if not ex_keys:
                continue

            message = None
            channel_id = maybe_data[ex_keys[0]]["channelid"]
            channel = ctx.bot.get_channel(channel_id)
            if channel:
                with contextlib.suppress(discord.HTTPException):
                    assert isinstance(channel, discord.TextChannel)  # nosec
                    message = await channel.fetch_message(message_id)

            if not message:
                key_data.update({maybe_message_id: ex_keys})

        for mid, keys in key_data.items():
            for k in keys:
                await self.config.custom("REACTROLE", mid, k).clear()

        await ctx.tick()

    @commands.guild_only()
    @commands.bot_has_permissions(manage_roles=True)
    @checks.admin_or_permissions(manage_guild=True)
    @commands.command(name="rolebind")
    async def bind_role_to_reactions(
        self, ctx: GuildContext, role: discord.Role, channel: discord.TextChannel, msgid: int, emoji: str,
    ):
        """
        Binds a role to a reaction on a message...

        The role is only given if the criteria for it are met.
        Make sure you configure the other settings for a role in [p]roleset
        """

        if not await self.all_are_valid_roles(ctx, role):
            return await ctx.maybe_send_embed("Can't do that. Discord role heirarchy applies here.")

        try:
            message = await channel.fetch_message(msgid)
        except discord.HTTPException:
            return await ctx.maybe_send_embed("No such message")

        _emoji: Optional[Union[discord.Emoji, str]]

        _emoji = discord.utils.find(lambda e: str(e) == emoji, self.bot.emojis)
        if _emoji is None:
            try:
                await ctx.message.add_reaction(emoji)
            except discord.HTTPException:
                return await ctx.maybe_send_embed("No such emoji")
            else:
                _emoji = emoji
                eid = self.strip_variations(emoji)
        else:
            eid = str(_emoji.id)

        if not any(str(r) == emoji for r in message.reactions):
            try:
                await message.add_reaction(_emoji)
            except discord.HTTPException:
                return await ctx.maybe_send_embed("Hmm, that message couldn't be reacted to")

        cfg = self.config.custom("REACTROLE", str(message.id), eid)
        await cfg.set(
            {"roleid": role.id, "channelid": message.channel.id, "guildid": role.guild.id,}
        )
        await ctx.send(
            f"Remember, the reactions only function according to "
            f"the rules set for the roles using `{ctx.prefix}roleset`",
            delete_after=30,
        )

    @commands.guild_only()
    @commands.bot_has_permissions(manage_roles=True)
    @checks.admin_or_permissions(manage_guild=True)
    @commands.command(name="roleunbind")
    async def unbind_role_from_reactions(self, ctx: commands.Context, role: discord.Role, msgid: int, emoji: str):
        """
        unbinds a role from a reaction on a message
        """

        if not await self.all_are_valid_roles(ctx, role):
            return await ctx.maybe_send_embed("Can't do that. Discord role heirarchy applies here.")

        await self.config.custom("REACTROLE", f"{msgid}", self.strip_variations(emoji)).clear()
        await ctx.tick()

    @commands.guild_only()
    @commands.bot_has_permissions(manage_roles=True)
    @checks.admin_or_permissions(manage_guild=True)
    @commands.group(name="roleset", autohelp=True)
    async def rgroup(self, ctx: GuildContext):
        """
        Settings for role requirements
        """
        pass

    @rgroup.command(name="viewreactions")
    async def rg_view_reactions(self, ctx: GuildContext):
        """
        View the reactions enabled for the server
        """
        # This design is intentional for later extention to view this per role

        use_embeds = await ctx.embed_requested()
        react_roles = "\n".join(
            [msg async for msg in self.build_messages_for_react_roles(*ctx.guild.roles, use_embeds=use_embeds)]
        )

        if not react_roles:
            return await ctx.send("No react roles bound here.")

        # ctx.send is already going to escape said mentions if any somehow get generated
        # should also not be possible to do so without willfully being done by an admin.

        color = await ctx.embed_colour() if use_embeds else None

        for page in pagify(react_roles, escape_mass_mentions=False, page_length=1800, shorten_by=0):
            # unrolling iterative calling of ctx.maybe_send_embed
            if use_embeds:
                await ctx.send(embed=discord.Embed(description=page, color=color))
            else:
                await ctx.send(page)

    @rgroup.command(name="dm-message")
    async def rg_dm_message(self, ctx: GuildContext, role: discord.Role, *, msg: str = None):
        """
        Set message to DM to user when they obtain the role.
        Will send it in the channel they ran the command if DM fails to send.

        Run with no message to get the current message of the role.
        Set message to message_clear to clear the message for the role.
        """
        if not msg:
            curr = await self.config.role(role).dm_msg()
            if not curr:
                await ctx.send("No message set for that role.")
            else:
                await ctx.send(curr)
            return
        elif msg.lower() == "message_clear":
            await self.config.role(role).dm_msg.set(None)
            await ctx.tick()
            return

        await self.config.role(role).dm_msg.set(msg)
        await ctx.tick()

    @rgroup.group(name="join")
    async def join_roles(self, ctx: GuildContext):
        """
        Set roles to add to users on join.
        """
        pass

    @join_roles.command(name="add")
    async def join_roles_add(self, ctx: GuildContext, *, role: discord.Role):
        """
        Add a role to the join list.
        """
        async with self.config.guild(ctx.guild).join_roles() as join_roles:
            if role.id not in join_roles:
                join_roles.append(role.id)

        await ctx.tick()

    @join_roles.command(name="rem")
    async def join_roles_rem(self, ctx: GuildContext, *, role: discord.Role):
        """
        Remove a role from the join list.
        """
        async with self.config.guild(ctx.guild).join_roles() as join_roles:
            try:
                join_roles.remove(role.id)
            except:
                await ctx.send("Role not in join list!")
                return

        await ctx.tick()

    @join_roles.command(name="list")
    async def join_roles_list(self, ctx: GuildContext):
        """
        List join roles.
        """
        roles = await self.config.guild(ctx.guild).join_roles()
        if not roles:
            await ctx.send("No roles defined.")
            return
        roles = [ctx.guild.get_role(role) for role in roles]
        missing = len([role for role in roles if role is None])
        roles = [f"{i+1}.{role.name}" for i, role in enumerate(roles) if role is not None]

        msg = "\n".join(sorted(roles))
        msg = pagify(msg)
        for m in msg:
            await ctx.send(box(m))

    @rgroup.command(name="viewrole")
    async def rg_view_role(self, ctx: GuildContext, *, role: discord.Role):
        """
        Views the current settings for a role
        """

        rsets = await self.config.role(role).all()

        output = (
            f"This role:\n{'is' if rsets['self_role'] else 'is not'} self assignable"
            f"\n{'is' if rsets['self_removable'] else 'is not'} self removable"
            f"\n{'is' if rsets['sticky'] else 'is not'} sticky."
        )
        if rsets["requires_any"]:
            rstring = ", ".join(r.name for r in ctx.guild.roles if r.id in rsets["requires_any"])
            output += f"\nThis role requires any of the following roles: {rstring}"
        if rsets["requires_all"]:
            rstring = ", ".join(r.name for r in ctx.guild.roles if r.id in rsets["requires_all"])
            output += f"\nThis role requires all of the following roles: {rstring}"
        if rsets["exclusive_to"]:
            rstring = ""
            for group, roles in rsets["exclusive_to"].items():
                rstring = f"`{group}`: "
                rstring += ", ".join(r.name for r in ctx.guild.roles if r.id in roles)
                rstring += "\n"
            output += f"\nThis role is mutually exclusive to the following role groups:\n{rstring}"
        if rsets["cost"]:
            curr = await bank.get_currency_name(ctx.guild)
            cost = rsets["cost"]
            output += f"\nThis role costs {cost} {curr}"
        else:
            output += "\nThis role does not have an associated cost."

        if rsets["subscription"]:
            s = rsets["subscription"]
            output += f"\nThis role has a subscription time of: {parse_seconds(s)}"

        if rsets["dm_msg"]:
            dm_msg = rsets["dm_msg"]
            output += f"\nDM Message: {box(dm_msg)}"

        for page in pagify(output):
            await ctx.send(page)

    @rgroup.command(name="cost")
    async def make_purchasable(self, ctx: GuildContext, cost: int, *, role: discord.Role):
        """
        Makes a role purchasable for a specified cost.
        Cost must be a number greater than 0.
        A cost of exactly 0 can be used to remove purchasability.

        Purchase eligibility still follows other rules including self assignable.

        Warning: If these roles are bound to a reaction,
        it will be possible to gain these without paying.
        """

        if not await self.all_are_valid_roles(ctx, role):
            return await ctx.maybe_send_embed("Can't do that. Discord role heirarchy applies here.")

        if cost < 0:
            return await ctx.send_help()

        await self.config.role(role).cost.set(cost)
        if cost == 0:
            await ctx.send(f"{role.name} is no longer purchasable.")
        else:
            await ctx.send(f"{role.name} is purchasable for {cost}")

    @rgroup.command(name="subscription")
    async def subscription(self, ctx, role: discord.Role, *, interval: str):
        """
        Sets a role to be a subscription, must set cost first.
        Will charge role's cost every interval, and remove the role if they run out of money
        Set to 0 to disable
        **__Minimum subscription duration is 1 hour__**
        Intervals look like:
           5 minutes
           1 minute 30 seconds
           1 hour
           2 days
           30 days
           5h30m
           (etc)
        """
        if not await self.all_are_valid_roles(ctx, role):
            return await ctx.maybe_send_embed("Can't do that. Discord role heirarchy applies here.")
        role_cost = await self.config.role(role).cost()

        if role_cost == 0:
            await ctx.send(waring("Please set a cost for the role first."))
            return

        time = parse_timedelta(interval)
        if int(time.total_seconds()) == 0:
            await ctx.send("Subscription removed.")
            async with self.config.guild(ctx.guild).s_roles() as s:
                s.remove(role.id)
            return
        elif int(time.total_seconds()) < MIN_SUB_TIME:
            await ctx.send("Subscriptions must be 1 hour or longer.")
            return

        await self.config.role(role).subscription.set(int(time.total_seconds()))
        async with self.config.guild(ctx.guild).s_roles() as s:
            s.append(role.id)
        await ctx.send(f"Subscription set to {parse_seconds(time.total_seconds())}.")

    @rgroup.command(name="forbid")
    async def forbid_role(self, ctx: GuildContext, role: discord.Role, *, user: discord.Member):
        """
        Forbids a user from gaining a specific role.
        """
        async with self.config.member(user).forbidden() as fb:
            if role.id not in fb:
                fb.append(role.id)
            else:
                await ctx.send("Role was already forbidden")
        await ctx.tick()

    @rgroup.command(name="unforbid")
    async def unforbid_role(self, ctx: GuildContext, role: discord.Role, *, user: discord.Member):
        """
        Unforbids a user from gaining a specific role.
        """
        async with self.config.member(user).forbidden() as fb:
            if role.id in fb:
                fb.remove(role.id)
            else:
                await ctx.send("Role was not forbidden")
        await ctx.tick()

    @rgroup.command(name="exclusive")
    async def set_exclusivity(self, ctx: GuildContext, group: str, *roles: discord.Role):
        """
        Set exclusive roles for group
        Takes 2 or more roles and sets them as exclusive to eachother

        The group can be any name, use spaces for names with spaces.
        Groups will show up in role list etc.
        """

        _roles = set(roles)

        if len(_roles) < 2:
            return await ctx.send("You need to provide at least 2 roles")

        for role in _roles:
            async with self.config.role(role).exclusive_to() as ex_list:
                if group not in ex_list.keys():
                    ex_list[group] = []
                ex_list[group].extend([r.id for r in _roles if r != role and r.id not in ex_list[group]])

        await ctx.tick()

    @rgroup.command(name="unexclusive")
    async def unset_exclusivity(self, ctx: GuildContext, group: str, *roles: discord.Role):
        """
        Remove exclusive roles for group
        Takes any number of roles, and removes their exclusivity settings

        The group can be any name, use spaces for names with spaces.
        If all roles are removed from a group then
        """

        _roles = set(roles)

        if not _roles:
            return await ctx.send("You need to provide at least a role to do this to")

        for role in _roles:
            ex_list = await self.config.role(role).exclusive_to()
            if group not in ex_list.keys():
                continue
            ex_list[group] = [idx for idx in ex_list if idx not in [r.id for r in _roles]]
            if not ex_list[group]:
                del ex_list[group]
            await self.config.role(role).exclusive_to.set(ex_list)
        await ctx.tick()

    @rgroup.command(name="sticky")
    async def setsticky(self, ctx: GuildContext, role: discord.Role, sticky: bool = None):
        """
        sets a role as sticky if used without a settings, gets the current ones
        """

        if sticky is None:
            is_sticky = await self.config.role(role).sticky()
            return await ctx.send("{role} {verb} sticky".format(role=role.name, verb=("is" if is_sticky else "is not")))

        await self.config.role(role).sticky.set(sticky)
        if sticky:
            for m in role.members:
                async with self.config.member(m).roles() as rids:
                    if role.id not in rids:
                        rids.append(role.id)

        await ctx.tick()

    @rgroup.command(name="requireall")
    async def reqall(self, ctx: GuildContext, role: discord.Role, *roles: discord.Role):
        """
        Sets the required roles to gain a role

        Takes a role plus zero or more other roles (as requirements for the first)
        """

        rids = [r.id for r in roles]
        await self.config.role(role).requires_all.set(rids)
        await ctx.tick()

    @rgroup.command(name="requireany")
    async def reqany(self, ctx: GuildContext, role: discord.Role, *roles: discord.Role):
        """
        Sets a role to require already having one of another

        Takes a role plus zero or more other roles (as requirements for the first)
        """

        rids = [r.id for r in (roles or [])]
        await self.config.role(role).requires_any.set(rids)
        await ctx.tick()

    @rgroup.command(name="selfrem")
    async def selfrem(self, ctx: GuildContext, role: discord.Role, removable: bool = None):
        """
        Sets if a role is self-removable (default False)

        use without a setting to view current
        """

        if removable is None:
            is_removable = await self.config.role(role).self_removable()
            return await ctx.send(
                "{role} {verb} self-removable".format(role=role.name, verb=("is" if is_removable else "is not"))
            )

        await self.config.role(role).self_removable.set(removable)
        await ctx.tick()

    @rgroup.command(name="selfadd")
    async def selfadd(self, ctx: GuildContext, role: discord.Role, assignable: bool = None):
        """
        Sets if a role is self-assignable via command

        (default False)

        use without a setting to view current
        """

        if assignable is None:
            is_assignable = await self.config.role(role).self_role()
            return await ctx.send(
                "{role} {verb} self-assignable".format(role=role.name, verb=("is" if is_assignable else "is not"))
            )

        await self.config.role(role).self_role.set(assignable)
        await ctx.tick()

    @rgroup.group(name="freerole")
    async def free_roles(self, ctx: GuildContext):
        """
        Sets roles that bypass costs for purchasing roles in your guild.
        """
        pass

    @free_roles.command(name="add")
    async def free_roles_add(self, ctx: GuildContext, *, role: discord.Role):
        """
        Add a role to the free list.
        """
        async with self.config.guild(ctx.guild).free_roles() as free_roles:
            if role.id not in free_roles:
                free_roles.append(role.id)

        await ctx.tick()

    @free_roles.command(name="rem")
    async def free_roles_rem(self, ctx: GuildContext, *, role: discord.Role):
        """
        Remove a role from the free list.
        """
        async with self.config.guild(ctx.guild).free_roles() as free_roles:
            try:
                free_roles.remove(role.id)
            except:
                await ctx.send("Role not in free list!")
                return

        await ctx.tick()

    @free_roles.command(name="list")
    async def free_roles_list(self, ctx: GuildContext):
        """
        List free roles.
        """
        roles = await self.config.guild(ctx.guild).free_roles()
        if not roles:
            await ctx.send("No roles defined.")
            return
        roles = [ctx.guild.get_role(role) for role in roles]
        missing = len([role for role in roles if role is None])
        roles = [f"{i+1}.{role.name}" for i, role in enumerate(roles) if role is not None]

        msg = "\n".join(sorted(roles))
        msg = pagify(msg)
        for m in msg:
            await ctx.send(box(m))

    @checks.bot_has_permissions(manage_roles=True)
    @commands.guild_only()
    @commands.group(name="selfrole", autohelp=True)
    async def selfrole(self, ctx: GuildContext):
        """
        Self assignable role commands
        """
        pass

    @selfrole.command(name="list")
    async def selfrole_list(self, ctx: GuildContext):
        """
        Lists the selfroles and any associated costs.
        """

        MYPY = False
        if MYPY:
            # remove this when mypy supports type narrowing from :=
            # It's less efficient, so not removing the actual
            # implementation below
            data: Dict[discord.Role, tuple] = {}
            for role_id, vals in (await self.config.all_roles()).items():
                role = ctx.guild.get_role(role_id)
                if role and vals["self_role"]:
                    data[role] = vals["cost"]
        else:
            data = {
                role: (vals["cost"], vals["subscription"], vals["exclusive_to"])
                for role_id, vals in (await self.config.all_roles()).items()
                if (role := ctx.guild.get_role(role_id)) and vals["self_role"]
            }

        if not data:
            return await ctx.send("There aren't any self roles here.")

        embed = discord.Embed(title="Roles", colour=ctx.guild.me.colour)
        i = 0
        for role, (cost, sub, ex_groups) in sorted(data.items(), key=lambda kv: kv[1][0]):
            if ex_groups:
                groups = humanize_list(list(ex_groups.keys()))
            else:
                groups = None
            embed.add_field(
                name=f"__**{i+1}. {role.name}**__",
                value="%s%s%s"
                % (
                    (f"Cost: {cost}" if cost else "Free"),
                    (f", every {parse_seconds(sub)}" if sub else ""),
                    (f"\nunique groups: `{groups}`" if groups else ""),
                ),
            )
            i += 1
            if i % MAX_EMBED == 0:
                await ctx.send(embed=embed)
        embed.set_footer(text="You can only have one role in the same unique group!")

        await ctx.send(embed=embed)

    @selfrole.command(name="buy")
    async def selfrole_buy(self, ctx: GuildContext, *, role: discord.Role):
        """
        Purchase a role
        """
        if role in ctx.author.roles:
            await ctx.send("You already have that role.")
            return
        try:
            remove = await self.is_self_assign_eligible(ctx.author, role)
            eligible = await self.config.role(role).self_role()
            cost = await self.config.role(role).cost()
            subscription = await self.config.role(role).subscription()
        except PermissionOrHierarchyException:
            await ctx.send("I cannot assign roles which I can not manage. (Discord Hierarchy)")
        except MissingRequirementsException as e:
            msg = ""
            if e.miss_all:
                roles = [r for r in ctx.guild.roles if r in e.miss_all]
                msg += f"You need all of these roles in order to get this role: {humanize_list(roles)}\n"
            if e.miss_any:
                roles = [r for r in ctx.guild.roles if r in e.miss_any]
                msg += f"You need one of these roles in order to get this role: {humanize_list(roles)}\n"
            await ctx.send(msg)
        except ConflictingRoleException as e:
            roles = [r for r in ctx.guild.roles if r in e.conflicts]
            plural = "are" if len(roles) > 1 else "is"
            await ctx.send(
                f"You have {humanize_list(roles)}, which you are not allowed to remove and {plural} exclusive to: {role.name}"
            )
        else:
            if not eligible:
                return await ctx.send(f"You aren't allowed to add `{role}` to yourself {ctx.author.mention}!")

            if not cost:
                return await ctx.send("This role doesn't have a cost. Please try again using `[p]selfrole add`.")

            free_roles = await self.config.guild(ctx.guild).free_roles()
            currency_name = await bank.get_currency_name(ctx.guild)
            for m_role in ctx.author.roles:
                if m_role.id in free_roles:
                    await ctx.send(f"You're special, no {currency_name} will be deducted from your account.")
                    await self.update_roles_atomically(who=ctx.author, give=[role], remove=remove)
                    await ctx.tick()
                    return

            try:
                await bank.withdraw_credits(ctx.author, cost)
            except ValueError:
                return await ctx.send(f"You don't have enough {currency_name} (Cost: {cost} {currency_name})")
            else:
                if subscription > 0:
                    await ctx.send(f"{role.name} will be renewed every {parse_seconds(subscription)}")
                    async with self.config.role(role).subscribed_users() as s:
                        s[str(ctx.author.id)] = time.time() + subscription
                    async with self.config.guild(ctx.guild).s_roles() as s:
                        if role.id not in s:
                            s.append(role.id)

                if remove:
                    plural = "s" if len(remove) > 1 else ""
                    await ctx.send(
                        f"Removed `{humanize_list([r.name for r in remove])}` role{plural} since they are exclusive to the role you added."
                    )
                await self.update_roles_atomically(who=ctx.author, give=[role], remove=remove)
                await self.dm_user(ctx, role)
                await ctx.tick()

    @selfrole.command(name="add")
    async def sadd(self, ctx: GuildContext, *, role: discord.Role):
        """
        Join a role
        """
        if role in ctx.author.roles:
            await ctx.send("You already have that role.")
            return
        try:
            remove = await self.is_self_assign_eligible(ctx.author, role)
            eligible = await self.config.role(role).self_role()
            cost = await self.config.role(role).cost()
        except PermissionOrHierarchyException:
            await ctx.send("I cannot assign roles which I can not manage. (Discord Hierarchy)")
        except MissingRequirementsException as e:
            msg = ""
            if e.miss_all:
                roles = [r for r in ctx.guild.roles if r in e.miss_all]
                msg += f"You need all of these roles in order to get this role: {humanize_list(roles)}\n"
            if e.miss_any:
                roles = [r for r in ctx.guild.roles if r in e.miss_any]
                msg += f"You need one of these roles in order to get this role: {humanize_list(roles)}\n"
            await ctx.send(msg)
        except ConflictingRoleException as e:
            print(e.conflicts)
            roles = [r for r in ctx.guild.roles if r in e.conflicts]
            plural = "are" if len(roles) > 1 else "is"
            await ctx.send(
                f"You have {humanize_list(roles)}, which you are not allowed to remove and {plural} exclusive to: {role.name}"
            )
        else:
            if not eligible:
                await ctx.send(f"You aren't allowed to add `{role}` to yourself {ctx.author.mention}!")

            elif cost:
                await ctx.send(
                    "This role is not free. " "Please use `[p]selfrole buy` if you would like to purchase it."
                )
            else:
                if remove:
                    plural = "s" if len(remove) > 1 else ""
                    await ctx.send(
                        f"Removed `{humanize_list([r.name for r in remove])}` role{plural} since they are exclusive to the role you added."
                    )
                await self.update_roles_atomically(who=ctx.author, give=[role], remove=remove)
                await self.dm_user(ctx, role)
                await ctx.tick()

    @selfrole.command(name="remove")
    async def srem(self, ctx: GuildContext, *, role: discord.Role):
        """
        leave a role
        """
        if role not in ctx.author.roles:
            await ctx.send("You do not have that role.")
            return
        if await self.config.role(role).self_removable():
            await self.update_roles_atomically(who=ctx.author, remove=[role])
            try:  # remove subscription, if any
                async with self.config.role(role).subscribed_users() as s:
                    del s[str(ctx.author.id)]
            except:
                pass
            await ctx.tick()
        else:
            await ctx.send(f"You aren't allowed to remove `{role}` from yourself {ctx.author.mention}!`")

    # Stuff for clean interaction with react role entries

    async def build_messages_for_react_roles(self, *roles: discord.Role, use_embeds=True) -> AsyncIterator[str]:
        """
        Builds info.

        Info is suitable for passing to embeds if use_embeds is True
        """

        linkfmt = (
            "[message #{message_id}](https://discordapp.com/channels/{guild_id}/{channel_id}/{message_id})"
            if use_embeds
            else "<https://discordapp.com/channels/{guild_id}/{channel_id}/{message_id}>"
        )

        for role in roles:
            # pylint: disable=E1133
            async for message_id, emoji_info, data in self.get_react_role_entries(role):

                channel_id = data.get("channelid", None)
                if channel_id:
                    link = linkfmt.format(guild_id=role.guild.id, channel_id=channel_id, message_id=message_id,)
                else:
                    link = (
                        f"unknown message with id {message_id}" f" (use `roleset fixup` to find missing data for this)"
                    )

                emoji: Union[discord.Emoji, str]
                if emoji_info.isdigit():
                    emoji = (
                        discord.utils.get(self.bot.emojis, id=int(emoji_info)) or f"A custom enoji with id {emoji_info}"
                    )
                else:
                    emoji = emoji_info

                react_m = f"{role.name} is bound to {emoji} on {link}"
                yield react_m

    async def dm_user(self, ctx: GuildContext, role: discord.Role):
        """
        DM user if dm_msg set for role.
        """
        dm_msg = await self.config.role(role).dm_msg()
        if not dm_msg:
            return

        try:
            await ctx.author.send(dm_msg)
        except:
            await ctx.send(
                f"Hey {ctx.author.mention}, please allow server members to DM you so I can send you messages! Here is the message for this role:"
            )
            await ctx.send(dm_msg)

    async def get_react_role_entries(self, role: discord.Role) -> AsyncIterator[Tuple[str, str, dict]]:
        """
        yields:
            str, str, dict

            first str: message id
            second str: emoji id or unicode codepoint
            dict: data from the corresponding:
                config.custom("REACTROLE", messageid, emojiid)
        """

        # self.config.register_custom(
        #    "REACTROLE", roleid=None, channelid=None, guildid=None
        # )  # ID : Message.id, str(React)

        data = await self.config.custom("REACTROLE").all()

        for mid, _outer in data.items():
            if not _outer or not isinstance(_outer, dict):
                continue
            for em, rdata in _outer.items():
                if rdata and rdata["roleid"] == role.id:
                    yield (mid, em, rdata)
