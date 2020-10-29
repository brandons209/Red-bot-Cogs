from textwrap import shorten

import discord
from redbot.core import checks
from redbot.core import commands
from redbot.core.config import Config
from redbot.core.i18n import Translator, cog_i18n
from redbot.core.utils import chat_formatting as chat
from redbot.core.utils.menus import menu, DEFAULT_CONTROLS
from redbot.core.utils.mod import get_audit_reason
from tabulate import tabulate
import asyncio

_ = Translator("PersonalRoles", __file__)


async def has_assigned_role(ctx):
    auto_roles = set(await ctx.cog.config.guild(ctx.guild).auto_roles())
    user_roles = {r.id for r in ctx.author.roles}
    user_roles &= auto_roles

    return len(user_roles) > 0 or ctx.guild.get_role(await ctx.cog.config.member(ctx.author).role())


@cog_i18n(_)
class PersonalRoles(commands.Cog):
    """Assign and edit personal roles"""

    __version__ = "2.0.4"

    # noinspection PyMissingConstructor
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=0x3D86BBD3E2B744AE8AA8B5D986EB4DD8, force_registration=True)
        default_member = {"role": None, "auto_role": False}
        default_guild = {"blacklist": [], "auto_roles": [], "position_role": None}
        self.config.register_member(**default_member)
        self.config.register_guild(**default_guild)

    @commands.group()
    @commands.guild_only()
    @checks.bot_has_permissions(manage_roles=True)
    async def myrole(self, ctx):
        """Control of personal role"""
        pass

    @myrole.command()
    @checks.admin_or_permissions(manage_roles=True)
    async def assign(self, ctx, user: discord.Member, *, role: discord.Role):
        """Assign personal role to someone"""
        await self.config.member(user).role.set(role.id)
        await ctx.send(
            _("Ok. I just assigned {user.name} ({user.id}) to role {role.name} ({role.id}).").format(
                user=user, role=role
            )
        )

    @myrole.command()
    @checks.admin_or_permissions(manage_roles=True)
    async def unassign(self, ctx, *, user: discord.Member):
        """Unassign personal role from someone"""

        role = await self.config.member(user).role()
        await self.config.member(user).role.clear()

        role = ctx.guild.get_role(role)
        if role:
            try:
                await role.delete()
            except:
                await ctx.send(
                    _(
                        "Ok. I just unassigned {user.name} ({user.id}) from their personal role.\nHowever, I could not delete the role."
                    ).format(user=user)
                )
        else:
            await ctx.send("User didn't have a role or it wasn't found. Role unassigned anyway to make sure.")
            return

        await ctx.send(
            _("Ok. I just unassigned {user.name} ({user.id}) from their personal role and deleted the role.").format(
                user=user
            )
        )

    @myrole.command(name="list")
    @checks.admin_or_permissions(manage_roles=True)
    async def mr_list(self, ctx):
        """Assigned roles list"""
        members_data = await self.config.all_members(ctx.guild)
        if not members_data:
            await ctx.send(chat.info(_("There is no assigned personal roles on this server")))
            return
        assigned_roles = []
        for member, data in members_data.items():
            if not data["role"]:
                continue
            dic = {
                _("User"): ctx.guild.get_member(member) or f"[X] {member}",
                _("Role"): shorten(
                    str(ctx.guild.get_role(data["role"]) or "[X] {}".format(data["role"])),
                    32,
                    placeholder="…",
                ),
            }
            assigned_roles.append(dic)
        pages = list(chat.pagify(tabulate(assigned_roles, headers="keys", tablefmt="orgtbl")))
        pages = [chat.box(page) for page in pages]
        await menu(ctx, pages, DEFAULT_CONTROLS)

    @myrole.group(name="auto")
    @checks.admin_or_permissions(manage_roles=True)
    async def myrole_auto(self, ctx):
        """
        Manage Auto role creation settings
        """
        pass

    @myrole_auto.command(name="roles")
    async def myrole_auto_autoroles(self, ctx, *, role_list: str = None):
        """
        Set roles that a user must have to allow auto creation of assigned roles
        by the bot.

        If user has any one of the roles in the list, an assigned role will
        be automatically created for them and assigned.

        Role list should be comma seperate list of role names and/or IDs.
        Roles in role list already set for autorole will be removed, and roles
        not set for autrole will be added.
        """
        guild = ctx.guild

        if not role_list:
            curr = await self.config.guild(guild).auto_roles()
            roles = [guild.get_role(r) for r in curr]
            names = [r.name for r in roles if r is not None]
            msg = ""
            if None in curr:
                msg += chat.warning("Some auto roles cannot be found, they have been removed from the list.\n")
                for i, role in enumerate(roles):
                    if role is None:
                        del curr[i]
                await self.config.guild(guild).auto_roles.set(curr)

            await ctx.send(f"Current auto roles: {chat.humanize_list(names) if names else chat.bold('None')}")
            return

        role_list = role_list.strip().split(",")
        role_list = [r.strip() for r in role_list]
        not_found = set()
        found = set()
        added = set()
        removed = set()
        for role_name in role_list:
            role = self.role_from_string(guild, role_name)

            if role is None:
                not_found.add(role_name)
                continue

            found.add(role)

        if not_found:
            await ctx.send(
                chat.warning(
                    "These roles weren't found, please try again: {}".format(chat.humanize_list(list(not_found)))
                )
            )
            return

        async with self.config.guild(guild).auto_roles() as auto_roles:
            for role in found:
                if role.id in auto_roles:
                    auto_roles.remove(role.id)
                    removed.add(role.name)
                else:
                    auto_roles.append(role.id)
                    added.add(role.name)

        msg = ""
        if added:
            msg += "Added: {}\n".format(chat.humanize_list(list(added)))
        if removed:
            msg += "Removed: {}".format(chat.humanize_list(list(removed)))

        await ctx.send(msg)

    @myrole_auto.command(name="pos")
    async def myrole_auto_autopos(self, ctx, *, role_pos: discord.Role):
        """
        Set position of where new roles are auto created.

        New roles will be created under this role.
        Cannot be higher than the bot's highest role
        """
        if role_pos > ctx.guild.me.top_role:
            await ctx.send("The role must be under my highest role.")
            return

        await self.config.guild(ctx.guild).position_role.set(role_pos.id)
        await ctx.tick()

    @myrole.group()
    @commands.guild_only()
    @checks.admin_or_permissions(manage_roles=True)
    async def blacklist(self, ctx):
        """Manage blacklisted names"""
        pass

    @blacklist.command()
    @checks.admin_or_permissions(manage_roles=True)
    async def add(self, ctx, *, rolename: str):
        """Add rolename to blacklist
        Members will be not able to change name of role to blacklisted names"""
        rolename = rolename.casefold()
        async with self.config.guild(ctx.guild).blacklist() as blacklist:
            if rolename in blacklist:
                await ctx.send(chat.error(_("`{}` is already in blacklist").format(rolename)))
            else:
                blacklist.append(rolename)
                await ctx.send(chat.info(_("Added `{}` to blacklisted roles list").format(rolename)))

    @blacklist.command()
    @checks.admin_or_permissions(manage_roles=True)
    async def remove(self, ctx, *, rolename: str):
        """Remove rolename from blacklist"""
        rolename = rolename.casefold()
        async with self.config.guild(ctx.guild).blacklist() as blacklist:
            if rolename not in blacklist:
                await ctx.send(chat.error(_("`{}` is not blacklisted").format(rolename)))
            else:
                blacklist.remove(rolename)
                await ctx.send(chat.info(_("Removed `{}` from blacklisted roles list").format(rolename)))

    @blacklist.command(name="list")
    @checks.admin_or_permissions(manage_roles=True)
    async def bl_list(self, ctx):
        """List of blacklisted role names"""
        blacklist = await self.config.guild(ctx.guild).blacklist()
        pages = [chat.box(page) for page in chat.pagify("\n".join(blacklist))]
        if pages:
            await menu(ctx, pages, DEFAULT_CONTROLS)
        else:
            await ctx.send(chat.info(_("There is no blacklisted roles")))

    @commands.cooldown(1, 30, commands.BucketType.user)
    @myrole.command(aliases=["color"])
    @commands.guild_only()
    @commands.check(has_assigned_role)
    async def colour(self, ctx, *, colour: discord.Colour = discord.Colour.default()):
        """Change color of personal role"""

        role = await self.config.member(ctx.author).role()
        role = ctx.guild.get_role(role)
        if not role:
            await ctx.send(chat.warning(f"Please create your role using `{ctx.prefix}myrole create`!"))
            return

        try:
            await role.edit(colour=colour, reason=get_audit_reason(ctx.author, _("Personal Role")))
        except discord.Forbidden:
            ctx.command.reset_cooldown(ctx)
            await ctx.send(
                chat.error(
                    _(
                        "Unable to edit role.\n"
                        'Role must be lower than my top role and I must have permission "Manage Roles"'
                    )
                )
            )
        except discord.HTTPException as e:
            ctx.command.reset_cooldown(ctx)
            await ctx.send(chat.error(_("Unable to edit role: {}").format(e)))
        else:
            if not colour.value:
                await ctx.send(_("Reset {user}'s personal role color").format(user=ctx.message.author.name))
            else:
                await ctx.send(
                    _("Changed color of {user}'s personal role to {color}").format(
                        user=ctx.message.author.name, color=colour
                    )
                )

    @commands.cooldown(1, 30, commands.BucketType.user)
    @myrole.command()
    @commands.guild_only()
    @commands.check(has_assigned_role)
    async def name(self, ctx, *, name: str):
        """Change name of personal role
        You can't use blacklisted names
        Names must be 30 characters or less"""
        role = await self.config.member(ctx.author).role()
        role = ctx.guild.get_role(role)
        if not role:
            await ctx.send(chat.warning(f"Please create your role using `{ctx.prefix}myrole create`!"))
            return

        name = name[:30]
        if name.casefold() in await self.config.guild(ctx.guild).blacklist():
            await ctx.send(chat.error(_("This rolename is blacklisted.")))
            return
        try:
            await role.edit(name=name, reason=get_audit_reason(ctx.author, _("Personal Role")))
        except discord.Forbidden:
            ctx.command.reset_cooldown(ctx)
            await ctx.send(
                chat.error(
                    _(
                        "Unable to edit role.\n"
                        'Role must be lower than my top role and i must have permission "Manage Roles"'
                    )
                )
            )
        except discord.HTTPException as e:
            ctx.command.reset_cooldown(ctx)
            await ctx.send(chat.error(_("Unable to edit role: {}").format(e)))
        else:
            await ctx.send(
                _("Changed name of {user}'s personal role to {name}").format(user=ctx.message.author.name, name=name)
            )

    @commands.cooldown(1, 30, commands.BucketType.user)
    @myrole.command()
    @commands.guild_only()
    @commands.check(has_assigned_role)
    async def create(self, ctx):
        """ Create personal role if you don't have one already """

        role = await self.config.member(ctx.author).role()
        role = ctx.guild.get_role(role)

        if not role:
            pos = await self.config.guild(ctx.guild).position_role()
            pos = ctx.guild.get_role(pos)
            pos = pos.position if pos else 1

            try:
                role = await ctx.guild.create_role(
                    name=str(ctx.author), colour=ctx.author.colour, reason=_("Personal role")
                )
                await asyncio.sleep(0.3)
                await role.edit(position=pos)
                await asyncio.sleep(0.3)
                await ctx.author.add_roles(role, reason=_("Personal Roles"))
                await self.config.member(ctx.author).role.set(role.id)
                await self.config.member(ctx.author).auto_role.set(True)
            except:
                await ctx.send(chat.warning("Could not create your personal role, please contact an admin."))
                return

            await ctx.send(
                f"Role created! You can edit it using `{ctx.prefix}myrole name` and `{ctx.prefix}myrole colour` commands."
            )
        else:
            await ctx.send(chat.warning("You already have a personal role!"))

    ### Helper methods
    @staticmethod
    def role_from_string(guild: discord.Guild, role_name: str):

        role = discord.utils.find(lambda r: r.name == role_name, guild.roles)
        # if couldnt find by role name, try to find by role id
        if role is None:
            role = discord.utils.find(lambda r: r.id == role_name, guild.roles)

        return role

    ### Listeners
    @commands.Cog.listener("on_member_join")
    async def role_persistance(self, member):
        """Automatically give already assigned roles on join"""
        if await self.bot.cog_disabled_in_guild(self, member.guild):
            return
        role = await self.config.member(member).role()
        if role:
            role = member.guild.get_role(role)
            if role and member:
                try:
                    await member.add_roles(role, reason=_("Personal Role"))
                except discord.Forbidden:
                    pass

    @commands.Cog.listener("on_member_remove")
    async def remove_role(self, member):
        """ Delete personal role if member leaves."""
        if await self.bot.cog_disabled_in_guild(self, member.guild):
            return
        role = await self.config.member(member).role()
        auto = await self.config.member(member).auto_role()
        role = member.guild.get_role(role)
        if auto:
            await self.config.member(member).role.clear()
            await self.config.member(member).auto_role.clear()
            try:
                await role.delete()
            except:
                pass

    @commands.Cog.listener("on_member_update")
    async def modify_roles(self, before, after):
        """ Delete personal role if member looses their auto role or looses their personal role """
        if await self.bot.cog_disabled_in_guild(self, after.guild):
            return
        role = await self.config.member(after).role()
        role = before.guild.get_role(role)
        if not role:
            return

        auto = await self.config.member(after).auto_role()
        if not auto:
            return

        auto_roles = await self.config.guild(before.guild).auto_roles()

        if before.roles != after.roles:
            if role not in after.roles:
                await self.config.member(after).role.clear()
                await self.config.member(after).auto_role.clear()
                try:
                    await role.delete()
                except:
                    pass
            else:
                after_ids = [r.id for r in after.roles]
                for m_role in after_ids:
                    if m_role in auto_roles:
                        return
                # lost their auto role, remove personal role, delete, and clear their data.
                await after.remove_roles(role, reason=_("Personal Roles"))
                await self.config.member(after).role.clear()
                await self.config.member(after).auto_role.clear()
                try:
                    await role.delete()
                except:
                    pass
