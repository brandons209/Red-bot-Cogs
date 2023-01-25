from __future__ import annotations

from datetime import datetime, timedelta
from typing import List

import discord
from redbot.core import commands

from .abc import MixinMeta
from .exceptions import RoleManagementException, PermissionOrHierarchyException


class EventMixin(MixinMeta):
    def verification_level_issue(self, member: discord.Member) -> bool:
        """
        Returns True if this would bypass verification level settings

        prevent react roles from bypassing time limits.
        It's exceptionally dumb that users can react while
        restricted by verification level, but that's Discord.
        They block reacting to blocked users, but interacting
        with entire guilds by reaction before hand? A-OK. *eyerolls*

        Can't check the email/2FA, blame discord for allowing people to react with above.
        """
        guild: discord.Guild = member.guild
        now = datetime.utcnow()
        level: int = guild.verification_level.value

        if level >= 3 and member.created_at + timedelta(minutes=5) > now:  # medium
            return True

        if level >= 4:  # high
            if not member.joined_at or member.joined_at + timedelta(minutes=10) > now:
                return True

        return False

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        """
        DEP-WARN
        Section has been optimized assuming member._roles
        remains an iterable containing snowflakes
        """
        if await self.bot.cog_disabled_in_guild(self, after.guild):
            return
        await self.wait_for_ready()
        if before._roles == after._roles:
            return

        lost, gained = set(before._roles), set(after._roles)
        lost, gained = lost - gained, gained - lost
        sym_diff = lost | gained

        # check if new member roles are exclusive to others.
        ex = []
        for r in gained:
            ex_groups = (await self.config.role_from_id(r).exclusive_to()).values()
            for ex_roles in ex_groups:
                ex.extend(ex_roles)

        to_remove = [r for r in after.roles if r.id in ex]
        if to_remove:
            await after.remove_roles(*to_remove, reason="conflict with exclusive roles")

        # add with roles for roles gained
        for r in gained:
            add_with = await self.config.role_from_id(r).add_with()
            if add_with:
                to_add = [
                    discord.utils.get(after.guild.roles, id=add) for add in add_with
                ]
                await after.add_roles(*to_add, reason=f"add with role {r}")

        for r in sym_diff:
            if not await self.config.role_from_id(r).sticky():
                lost.discard(r)
                gained.discard(r)

        async with self.config.member(after).roles() as rids:
            for r in lost:
                while r in rids:
                    rids.remove(r)
            for r in gained:
                if r not in rids:
                    rids.append(r)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        await self.wait_for_ready()
        if await self.bot.cog_disabled_in_guild(self, member.guild):
            return
        guild = member.guild
        if not guild.me.guild_permissions.manage_roles:
            return

        async with self.config.member(member).roles() as rids:
            to_add: List[discord.Role] = []
            for _id in rids:
                role = discord.utils.get(guild.roles, id=_id)
                if not role:
                    continue
                if await self.config.role(role).sticky():
                    to_add.append(role)
            if to_add:
                to_add = [r for r in to_add if r < guild.me.top_role]
                await member.add_roles(*to_add)

        # join roles
        async with self.config.guild(guild).join_roles() as join_roles:
            to_add: List[discord.Role] = []
            for role_id in join_roles:
                role = discord.utils.get(guild.roles, id=role_id)
                if role:
                    to_add.append(role)
            if to_add:
                to_add = [r for r in to_add if r < guild.me.top_role]
                await member.add_roles(*to_add)

    @commands.Cog.listener()
    async def on_raw_reaction_add(
        self, payload: discord.raw_models.RawReactionActionEvent
    ):
        await self.wait_for_ready()
        if not payload.guild_id:
            return

        emoji = payload.emoji
        if emoji.is_custom_emoji():
            eid = str(emoji.id)
        else:
            eid = self.strip_variations(str(emoji))

        cfg = self.config.custom("REACTROLE", str(payload.message_id), eid)
        rid = await cfg.roleid()
        if rid is None:
            return

        guild = self.bot.get_guild(payload.guild_id)
        if guild:
            await self.maybe_update_guilds(guild)
        else:
            return

        if await self.bot.cog_disabled_in_guild(self, guild):
            return
        member = guild.get_member(payload.user_id)

        if member is None or member.bot:
            return

        if self.verification_level_issue(member):
            return

        role = guild.get_role(rid)
        if role is None or role in member.roles:
            return

        if not await self.verify_age(role, member=member):
            try:
                await member.send(
                    f"You do not meet the minimum age requiremnt for `{role}`, if you think this is an error please contact a staff member."
                )
            except:
                pass
            return

        try:
            remove = await self.is_self_assign_eligible(member, role)
        except (RoleManagementException, PermissionOrHierarchyException):
            pass
        else:
            dm_msg = await self.config.role(role).dm_msg()
            if dm_msg:
                try:
                    await member.send(dm_msg)
                except:
                    pass
            await self.update_roles_atomically(who=member, give=[role], remove=remove)

    @commands.Cog.listener()
    async def on_raw_reaction_remove(
        self, payload: discord.raw_models.RawReactionActionEvent
    ):
        await self.wait_for_ready()
        if not payload.guild_id:
            return

        emoji = payload.emoji

        if emoji.is_custom_emoji():
            eid = str(emoji.id)
        else:
            eid = self.strip_variations(str(emoji))

        cfg = self.config.custom("REACTROLE", str(payload.message_id), eid)
        rid = await cfg.roleid()

        if rid is None:
            return

        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            # Where's it go?
            return
        if await self.bot.cog_disabled_in_guild(self, guild):
            return
        member = guild.get_member(payload.user_id)
        if not member or member.bot:
            return
        role = discord.utils.get(guild.roles, id=rid)
        if not role or role not in member.roles:
            return
        if guild.me.guild_permissions.manage_roles and guild.me.top_role > role:
            await self.update_roles_atomically(who=member, give=None, remove=[role])
