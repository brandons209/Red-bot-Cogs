from __future__ import annotations

import re
from typing import List
from datetime import timedelta
import discord

from .abc import MixinMeta
from .exceptions import (
    ConflictingRoleException,
    MissingRequirementsException,
    PermissionOrHierarchyException,
)

variation_stripper_re = re.compile(r"[\ufe00-\ufe0f]")

TIME_RE_STRING = r"\s?".join(
    [
        r"((?P<weeks>\d+?)\s?(weeks?|w))?",
        r"((?P<days>\d+?)\s?(days?|d))?",
        r"((?P<hours>\d+?)\s?(hours?|hrs|hr?))?",
        r"((?P<minutes>\d+?)\s?(minutes?|mins?|m(?!o)))?",  # prevent matching "months"
        r"((?P<seconds>\d+?)\s?(seconds?|secs?|s))?",
    ]
)

TIME_RE = re.compile(TIME_RE_STRING, re.I)


def parse_timedelta(argument: str) -> timedelta:
    """
    Parses a string that contains a time interval and converts it to a timedelta object.
    """
    matches = TIME_RE.match(argument)
    if matches:
        params = {k: int(v) for k, v in matches.groupdict().items() if v}
        if params:
            return timedelta(**params)
    return None


def parse_seconds(seconds) -> str:
    """
    Take seconds and converts it to larger units
    Returns parsed message string
    """
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    days, hours = divmod(hours, 24)
    weeks, days = divmod(days, 7)
    months, weeks = divmod(weeks, 4)
    msg = []

    if months:
        msg.append(f"{int(months)} {'months' if months > 1 else 'month'}")
    if weeks:
        msg.append(f"{int(weeks)} {'weeks' if weeks > 1 else 'week'}")
    if days:
        msg.append(f"{int(days)} {'days' if days > 1 else 'day'}")
    if hours:
        msg.append(f"{int(hours)} {'hours' if hours > 1 else 'hour'}")
    if minutes:
        msg.append(f"{int(minutes)} {'minutes' if minutes > 1 else 'minute'}")
    if seconds:
        msg.append(f"{int(seconds)} {'seconds' if seconds > 1 else 'second'}")

    return ", ".join(msg)


class UtilMixin(MixinMeta):
    """
    Mixin for utils, some of which need things stored in the class
    """

    def strip_variations(self, s: str) -> str:
        """
        Normalizes emoji, removing variation selectors
        """
        return variation_stripper_re.sub("", s)

    async def update_roles_atomically(
        self,
        *,
        who: discord.Member,
        give: List[discord.Role] = None,
        remove: List[discord.Role] = None,
    ):
        """
        Give and remove roles as a single op with some slight sanity
        wrapping
        """
        me = who.guild.me
        give = give or []
        remove = remove or []
        heirarchy_testing = give + remove
        roles = [r for r in who.roles if r not in remove]
        roles.extend([r for r in give if r not in roles])
        if sorted(roles) == sorted(who.roles):
            return
        if any(r >= me.top_role for r in heirarchy_testing) or not me.guild_permissions.manage_roles:
            raise PermissionOrHierarchyException("Can't do that.")
        await who.edit(roles=roles)

    async def all_are_valid_roles(self, ctx, *roles: discord.Role) -> bool:
        """
        Quick heirarchy check on a role set in syntax returned
        """
        author = ctx.author
        guild = ctx.guild

        # Author allowed
        if not (
            (guild.owner == author)
            or all(author.top_role > role for role in roles)
            or await ctx.bot.is_owner(ctx.author)
        ):
            return False

        # Bot allowed
        if not (
            guild.me.guild_permissions.manage_roles
            and (guild.me == guild.owner or all(guild.me.top_role > role for role in roles))
        ):
            return False

        # Sanity check on managed roles
        if any(role.managed for role in roles):
            return False

        return True

    async def is_self_assign_eligible(self, who: discord.Member, role: discord.Role) -> List[discord.Role]:
        """
        Returns a list of roles to be removed if this one is added, or raises an
        exception
        """
        await self.check_required(who, role)

        ret: List[discord.Role] = await self.check_exclusivity(who, role)

        forbidden = await self.config.member(who).forbidden()
        if role.id in forbidden:
            raise PermissionOrHierarchyException()

        guild = who.guild
        if not guild.me.guild_permissions.manage_roles or role > guild.me.top_role:
            raise PermissionOrHierarchyException()

        return ret

    async def check_required(self, who: discord.Member, role: discord.Role) -> None:
        """
        Raises an error on missing reqs
        """

        req_any = await self.config.role(role).requires_any()
        req_any_fail = req_any[:]
        if req_any:
            for idx in req_any:
                if who._roles.has(idx):
                    req_any_fail = []
                    break

        req_all_fail = [idx for idx in await self.config.role(role).requires_all() if not who._roles.has(idx)]

        if req_any_fail or req_all_fail:
            raise MissingRequirementsException(miss_all=req_all_fail, miss_any=req_any_fail)

        return None

    async def check_exclusivity(self, who: discord.Member, role: discord.Role) -> List[discord.Role]:
        """
        Returns a list of roles to remove, or raises an error
        """

        data = await self.config.all_roles()
        ex_data = data.get(role.id, {}).get("exclusive_to", {}).values()
        ex = []
        for ex_roles in ex_data:
            ex.extend(ex_roles)
        conflicts: List[discord.Role] = [r for r in who.roles if r.id in ex]

        for r in conflicts:
            if not data.get(r.id, {}).get("self_removable", False):
                raise ConflictingRoleException(conflicts=conflicts)
        return conflicts

    async def maybe_update_guilds(self, *guilds: discord.Guild):
        _guilds = [g for g in guilds if not g.unavailable and g.large and not g.chunked]
        if _guilds:
            await self.bot.request_offline_members(*_guilds)
