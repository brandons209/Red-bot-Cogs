import logging
import hashlib
import asyncio
import discord
from datetime import datetime
import time

from redbot.core import checks, commands, Config, modlog
from redbot.core.bot import Red
from redbot.core.config import Group
from redbot.core.commands import Context, Cog
from redbot.core.utils.predicates import MessagePredicate

try:
    from redbot.core.commands import GuildContext
except ImportError:
    from redbot.core.commands import Context as GuildContext


class Trotters(commands.Cog):
    __author__ = "TheBluekr#2702"

    def __init__(self, bot):
        super().__init__()
        self.bot = bot
        self.logger = logging.getLogger("aurelia.cogs.trotters")
        self.config = Config.get_conf(self, identifier=428038701, force_registration=True)

        default_role = {"addable": False, "USERS": {}}

        self.config.register_role(**default_role)

    def cog_unload(self):
        pass

    async def initialize(self):
        await self.register_casetypes()

    @staticmethod
    async def register_casetypes():
        # register mod case
        role_case = {
            "name": "Role List Update",
            "default_setting": True,
            "image": "\N{PAGE FACING UP}",
            "case_str": "roleupdate",
        }
        try:
            await modlog.register_casetype(**role_case)
        except RuntimeError:
            pass

    # Commands
    @commands.group()
    @commands.guild_only()
    async def trotters(self, ctx: Context):
        """Trotter's Pass settings"""
        pass

    @checks.admin_or_permissions(manage_roles=True)
    @trotters.command(name="set")
    async def set_role(self, ctx, role: discord.Role, enabled: bool):
        """
        Sets role to be addable/removable
        """

        if not role:
            return await ctx.maybe_send_embed("No role supplied")

        if not enabled:
            if await self.config.role(role).USERS():
                pred = MessagePredicate.yes_or_no(ctx)
            await ctx.send(f"Found logs for role {role}, do you want to erase them?")
            try:
                await self.bot.wait_for("message", check=pred, timeout=30)
            except asyncio.TimeoutError:
                return await ctx.send("Timed out.")
            if pred.result:
                await self.config.role(role).USERS.set({})
            await self.config.role(role).addable.set(False)
            await ctx.tick()
        else:
            await self.config.role(role).addable.set(True)
            await ctx.tick()

    @checks.admin_or_permissions(manage_roles=True)
    @trotters.command(name="roles")
    async def view_roles(self, ctx):
        """
        Lists all roles which can be added/removed
        """
        enabled = list()
        for role in ctx.guild.roles:
            if await self.config.role(role).addable() and not role.is_default():
                enabled.append(role.name)
        await ctx.maybe_send_embed(f"List of addable roles: \n%s" % (", ".join(enabled)))

    @commands.bot_has_permissions(manage_roles=True)
    @trotters.command(name="add")
    async def add_role(self, ctx: GuildContext, user_id: int, role: discord.Role, *, reason: str = "Added by command."):
        """
        Adds specified role to given user
        """

        if not await self.config.role(role).addable():
            return await ctx.maybe_send_embed("Role isn't set as addable.")
        try:
            member = ctx.guild.get_member(user_id)
            if role in member.roles:
                return await ctx.maybe_send_embed("Member already has that role.")

            data = await self.config.role(role).USERS()
            if len(ctx.message.attachments):
                attachment = ctx.message.attachments[0]
                case = await modlog.create_case(
                    self.bot,
                    member.guild,
                    ctx.message.created_at,
                    "Role List Update",
                    member,
                    moderator=ctx.author,
                    reason=(f"{reason}. {attachment.url}"),
                )
            else:
                pred = MessagePredicate.yes_or_no(ctx)
                await ctx.send(f"Couldn't find attachment, do you want to continue without adding attachment?")
                try:
                    await self.bot.wait_for("message", check=pred, timeout=30)
                except asyncio.TimeoutError:
                    return await ctx.send("Timed out.")
                if pred.result:
                    case = await modlog.create_case(
                        self.bot,
                        member.guild,
                        ctx.message.created_at,
                        "Role List Update",
                        member,
                        moderator=ctx.author,
                        reason=(f"{reason}. Missing attachment."),
                    )
                else:
                    return await ctx.maybe_send_embed("Cancelling command.")
            caseno = case.case_number
            await member.add_roles(role)
            data[member] = caseno
            await self.config.role(role).USERS.set(data)
            await ctx.tick()
        except discord.Forbidden:
            return await ctx.maybe_send_embed("Can't do that. Discord role heirarchy applies here.")

    @commands.bot_has_permissions(manage_roles=True)
    @trotters.command(name="remove")
    async def remove_role(
        self, ctx: GuildContext, user_id: int, role: discord.Role, *, reason: str = "Removed by command."
    ):
        """
        Removes specified role from given user
        """

        if not await self.config.role(role).addable():
            return await ctx.maybe_send_embed("Role isn't set as addable.")
        guild = ctx.guild
        member = guild.get_member(user_id)
        try:
            if role not in member.roles:
                return await ctx.maybe_send_embed("Member doesn't have that role.")

            data = await self.config.role(role).USERS()
            caseno = data.pop(user_id, None)

            if caseno:
                try:
                    case = await modlog.get_case(caseno, guild, self.bot)
                except RuntimeError:
                    self.logger.error(f"Failed to find case for {member}, case number: {case}")
                    case = None

                if case:
                    edits = {"reason": reason}

                    if ctx.message.author.id != case.moderator.id:
                        edits["amended_by"] = ctx.message.author

                    edits["modified_at"] = ctx.message.created_at.timestamp()

                    await case.edit(edits)

            await member.remove_role(role)
            await self.config.role(role).USERS.set(data)
            await ctx.tick()
        except discord.Forbidden:
            return await ctx.maybe_send_embed("Can't do that. Discord role heirarchy applies here.")

    # Listeners
    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        """
        Listens for role updates and more
        """

        if before.roles != after.roles:
            user = self.bot.user
            try:
                async for entry in after.guild.audit_logs(limit=3, action=discord.AuditLogAction.member_role_update):
                    if entry.target.id == before.id:
                        user = entry.user
                        break
            except discord.Forbidden:
                self.logger.warning("Failed to retrieve the moderator from audit logs, please check the permissions")

            broles = set(before.roles)
            aroles = set(after.roles)
            added = aroles - broles
            removed = broles - aroles

            now_date = datetime.utcfromtimestamp(time.time())

            for role in added:
                if await self.config.role(role).addable():
                    data = await self.config.role(role).USERS()

                    case = await modlog.create_case(
                        self.bot,
                        before.guild,
                        now_date,
                        "Role List Update",
                        before,
                        moderator=user,
                        reason="Role manually added",
                    )
                    caseno = case.case_number

                    data[before.id] = caseno
                    await self.config.role(role).USERS.set(data)

            for role in removed:
                if await self.config.role(role).addable():
                    data = await self.config.role(role).USERS()

                    caseno = data.pop(before.id, None)

                    if caseno:
                        try:
                            case = await modlog.get_case(caseno, before.guild, self.bot)
                        except RuntimeError:
                            self.logger.error(f"Failed to find case for {before.user}, case number: {case}")
                            case = None

                        if case:
                            edits = {"reason": "Role manually removed"}

                            if user.id != case.moderator.id:
                                edits["amended_by"] = user

                            edits["modified_at"] = now_date

                            await case.edit(edits)

                    await self.config.role(role).USERS.set(data)
