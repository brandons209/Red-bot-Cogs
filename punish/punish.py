# redbot/discord
from redbot.core.utils.chat_formatting import *
from redbot.core.utils import mod
from redbot.core.utils.menus import menu, DEFAULT_CONTROLS
from redbot.core import Config, checks, commands, modlog
import discord

from .utils import *
from .memoizer import Memoizer

# general
import asyncio
from datetime import datetime
import inspect
import logging
import time
import textwrap

log = logging.getLogger("red.punish")

__version__ = "3.0.0"

PURGE_MESSAGES = 1  # for cpunish

DEFAULT_ROLE_NAME = "Punished"
DEFAULT_TEXT_OVERWRITE = discord.PermissionOverwrite(send_messages=False, send_tts_messages=False, add_reactions=False)
DEFAULT_VOICE_OVERWRITE = discord.PermissionOverwrite(speak=False, connect=False)
DEFAULT_TIMEOUT_OVERWRITE = discord.PermissionOverwrite(
    send_messages=True, read_messages=True, read_message_history=True
)

QUEUE_TIME_CUTOFF = 30

DEFAULT_TIMEOUT = "5m"
DEFAULT_CASE_MIN_LENGTH = "5m"  # only create modlog cases when length is longer than this


class Punish(commands.Cog):
    """
    Put misbehaving users in timeout where they are unable to speak, read, or
    do other things that can be denied using discord permissions. Includes
    auto-setup and more.
    """

    def __init__(self, bot):
        super().__init__()

        self.bot = bot
        self.config = Config.get_conf(self, identifier=1574368792)
        # config
        default_guild = {
            "PUNISHED": {},
            "CASE_MIN_LENGTH": parse_time(DEFAULT_CASE_MIN_LENGTH),
            "PENDING_UNMUTE": [],
            "REMOVE_ROLE_LIST": [],
            "TEXT_OVERWRITE": overwrite_to_dict(DEFAULT_TEXT_OVERWRITE),
            "VOICE_OVERWRITE": overwrite_to_dict(DEFAULT_VOICE_OVERWRITE),
            "ROLE_ID": None,
            "NITRO_ID": None,
            "CHANNEL_ID": None,
        }
        self.config.register_guild(**default_guild)

        # queue variables
        self.queue = asyncio.PriorityQueue()
        self.queue_lock = asyncio.Lock()
        self.pending = {}
        self.enqueued = set()

        self.task = asyncio.create_task(self.on_load())

    def cog_unload(self):
        self.task.cancel()

    async def initialize(self):
        await self.register_casetypes()

    @staticmethod
    async def register_casetypes():
        # register mod case
        punish_case = {
            "name": "Timed Mute",
            "default_setting": True,
            "image": "\N{HOURGLASS WITH FLOWING SAND}\N{SPEAKER WITH CANCELLATION STROKE}",
            "case_str": "Timed Mute",
        }
        try:
            await modlog.register_casetype(**punish_case)
        except RuntimeError:
            pass

    @commands.group(invoke_without_command=True)
    @commands.guild_only()
    @checks.mod()
    async def punish(self, ctx, user: discord.Member, duration: str = None, *, reason: str = None):
        """
        Puts a user into timeout for a specified time, with optional reason.

        Time specification is any combination of number with the units s,m,h,d,w.
        Example: !punish @idiot 1.1h10m Breaking rules
        """
        if ctx.invoked_subcommand:
            return
        elif user:
            await self._punish_cmd_common(ctx, user, duration, reason)

    @punish.command(name="cstart")
    @commands.guild_only()
    @checks.mod()
    async def punish_cstart(self, ctx, user: discord.Member, duration: str = None, *, reason: str = None):
        """
        Same as [p]punish start, but cleans up the target's last message.
        """

        success = await self._punish_cmd_common(ctx, user, duration, reason, quiet=True)

        if not success:
            return

        def check(m):
            return m.id == ctx.message.id or m.author == user

        try:
            await ctx.message.channel.purge(limit=PURGE_MESSAGES + 1, check=check)
        except discord.errors.Forbidden:
            await ctx.send("Punishment set, but I need permissions to manage messages to clean up.")

    @punish.command(name="list")
    @commands.guild_only()
    @checks.mod()
    async def punish_list(self, ctx):
        """
        Shows a table of punished users with time, mod and reason.

        Displays punished users, time remaining, responsible moderator and
        the reason for punishment, if any.
        """

        guild = ctx.guild
        guild_id = guild.id
        now = time.time()
        headers = ["Member", "Remaining", "Moderator", "Reason"]
        punished = await self.config.guild(guild).PUNISHED()

        embeds = []
        num_p = len(punished)
        for i, data in enumerate(punished.items()):
            member_id, data = data
            member_name = getmname(member_id, guild)
            moderator = getmname(data["by"], guild)
            reason = data["reason"]
            until = data["until"]
            sort = until or float("inf")
            remaining = generate_timespec(until - now, short=True) if until else "forever"

            row = [member_name, remaining, moderator, reason or "No reason set."]
            embed = discord.Embed(title="Punish List", colour=discord.Colour.from_rgb(255, 0, 0))

            for header, row_val in zip(headers, row):
                embed.add_field(name=header, value=row_val)

            embed.set_footer(text=f"Page {i+1} out of {num_p}")
            embeds.append(embed)

        if not punished:
            await ctx.send("No users are currently punished.")
            return

        await menu(ctx, embeds, DEFAULT_CONTROLS)

    @punish.command(name="clean")
    @commands.guild_only()
    @checks.mod()
    async def punish_clean(self, ctx, clean_pending: bool = False):
        """
        Removes absent members from the punished list.

        If run without an argument, it only removes members who are no longer
        present but whose timer has expired. If the argument is 'yes', 1,
        or another trueish value, it will also remove absent members whose
        timers have yet to expire.

        Use this option with care, as removing them will prevent the punished
        role from being re-added if they rejoin before their timer expires.
        """

        count = 0
        now = time.time()
        guild = ctx.guild
        data = await self.config.guild(guild).PUNISHED()

        for mid, mdata in data.copy().items():
            intid = int(mid)
            if guild.get_member(intid):
                continue

            elif clean_pending or ((mdata["until"] or 0) < now):
                del data[mid]
                count += 1

        await self.config.guild(guild).PUNISHED.set(data)
        await ctx.send("Cleaned %i absent members from the list." % count)

    @punish.command(name="clean-bans")
    @commands.guild_only()
    @checks.mod()
    @checks.bot_has_permissions(ban_members=True)
    async def punish_clean_bans(self, ctx):
        """
        Removes banned members from the punished list.
        """

        count = 0
        guild = ctx.guild
        data = await self.config.guild(guild).PUNISHED()

        bans = await guild.bans()
        ban_ids = {ban.user.id for ban in bans}

        for mid, mdata in data.copy().items():
            intid = int(mid)
            if guild.get_member(intid):
                continue

            elif intid in ban_ids:
                del data[mid]
                count += 1

        await self.config.guild(guild).PUNISHED.set(data)
        await ctx.send("Cleaned %i banned users from the list." % count)

    @punish.command(name="warn")
    @commands.guild_only()
    @checks.mod_or_permissions(manage_messages=True)
    async def punish_warn(self, ctx, user: discord.Member, *, reason: str = None):
        """
        Warns a user with boilerplate about the rules
        """

        msg = ["Hey %s, " % user.mention]
        msg.append("you're doing something that might get you muted if you keep " "doing it.")
        if reason:
            msg.append(" Specifically, %s." % reason)

        msg.append("Be sure to review the guild rules.")
        await ctx.send(" ".join(msg))

    @punish.command(name="end", aliases=["remove"])
    @commands.guild_only()
    @checks.mod()
    async def punish_end(self, ctx, user: discord.Member, *, reason: str = None):
        """
        Removes punishment from a user before time has expired

        This is the same as removing the role directly.
        """

        role = await self.get_role(user.guild, quiet=True)
        sid = user.guild.id
        guild = user.guild
        moderator = ctx.author
        now = time.time()
        punished = await self.config.guild(guild).PUNISHED()
        data = punished.get(str(user.id), {})
        removed_roles_parsed = resolve_role_list(guild, data.get("removed_roles", []))

        if role and role in user.roles:
            msg = "Punishment manually ended early by %s." % ctx.author

            original_start = data.get("start")
            original_end = data.get("until")
            remaining = original_end and (original_end - now)

            if remaining:
                msg += " %s was left" % generate_timespec(round(remaining))

                if original_start:
                    msg += " of the original %s." % generate_timespec(round(original_end - original_start))
                else:
                    msg += "."

            if reason:
                msg += "\n\nReason for ending early: " + reason

            if data.get("reason"):
                msg += "\n\nOriginal reason was: " + data["reason"]

            updated_reason = str(msg)  # copy string

            if removed_roles_parsed:
                names_list = format_list(*(r.name for r in removed_roles_parsed))
                msg += "\nRestored role(s): {}".format(names_list)

            if not await self._unpunish(user, reason=updated_reason, update=True, moderator=moderator):
                msg += "\n\n(failed to send punishment end notification DM)"

            await ctx.send(msg)
        elif data:  # This shouldn't happen, but just in case
            now = time.time()
            until = data.get("until")
            remaining = until and generate_timespec(round(until - now)) or "forever"

            data_fmt = "\n".join(
                [
                    "**Reason:** %s" % (data.get("reason") or "no reason set"),
                    "**Time remaining:** %s" % remaining,
                    "**Moderator**: %s" % (user.guild.get_member(data.get("by")) or "Missing ID#%s" % data.get("by")),
                ]
            )
            del punished[str(user.id)]
            await self.config.guild(guild).PUNISHED.set(punished)

            await ctx.send(
                "That user doesn't have the %s role, but they still have a data entry. I removed it, "
                "but in case it's needed, this is what was there:\n\n%s" % (role.name, data_fmt)
            )
        elif role:
            await ctx.send("That user doesn't have the %s role." % role.name)
        else:
            await ctx.send("The punish role couldn't be found in this guild.")

    @punish.command(name="reason")
    @commands.guild_only()
    @checks.mod()
    async def punish_reason(self, ctx, user: discord.Member, *, reason: str = None):
        """
        Updates the reason for a punishment, including the modlog if a case exists.
        """
        guild = ctx.guild
        punished = await self.config.guild(guild).PUNISHED()
        data = punished.get(str(user.id), None)

        if not data:
            await ctx.send(
                "That user doesn't have an active punishment entry. To update modlog "
                "cases manually, use the `%sreason` command." % ctx.prefix
            )
            return

        punished[str(user.id)]["reason"] = reason
        await self.config.guild(guild).PUNISHED.set(punished)

        if reason:
            msg = "Reason updated."
        else:
            msg = "Reason cleared."

        caseno = data.get("caseno")
        try:
            case = await modlog.get_case(caseno, guild, self.bot)
        except:
            msg += "\nMod case not found!"
            case = None

        if case:
            moderator = ctx.author

            try:
                edits = {"reason": reason}

                if moderator.id != data.get("by"):
                    edits["amended_by"] = moderator

                edits["modified_at"] = ctx.message.created_at.timestamp()

                await case.edit(edits)
            except:
                msg += "\n" + warning("Mod case not modified due to error.")

        await ctx.send(msg)

    @commands.group()
    @commands.guild_only()
    @checks.admin_or_permissions(administrator=True)
    async def punishset(self, ctx):
        pass

    @punishset.command(name="remove-roles")
    async def punishset_remove_role_list(self, ctx, *, rolelist=None):
        """Set what roles to remove when punishing.

        COMMA SEPARATED LIST (e.g. Admin,Staff,Mod), Can also use role IDs as well.

        To get current remove role list, run command with no roles.

        Add role_list_clear as the role to clear the guild's remove role list.
        """
        guild = ctx.guild
        role_list = await self.config.guild(guild).REMOVE_ROLE_LIST()
        punished = await self.config.guild(guild).PUNISHED()
        current_roles = resolve_role_list(guild, role_list)

        if rolelist is None:
            if current_roles:
                names_list = format_list(*(r.name for r in current_roles))
                await ctx.send(f"Current list of roles removed when a user is punished: {names_list}")
            else:
                await ctx.send("No roles defined for removal.")
            return
        elif "role_list_clear" in rolelist.lower():
            await ctx.send("Remove role list cleared.")
            await self.config.guild(guild).REMOVE_ROLE_LIST.set([])
            return

        found_roles = set()
        notfound_names = set()
        punish_role = await self.get_role(guild, quiet=True)

        for lookup in rolelist.split(","):
            lookup = lookup.strip()
            role = role_from_string(guild, lookup)

            if role:
                found_roles.add(role)
            else:
                notfound_names.add(lookup)

        if notfound_names:
            fmt_list = format_list(*("`{}`".format(x) for x in notfound_names))
            await ctx.send(warning(f"These roles were not found: {fmt_list}\n\nPlease try again."))
        elif punish_role and punish_role in found_roles:
            await ctx.send(warning("The punished role cannot be removed.\n\nPlease try again."))
        elif guild.default_role in found_roles:
            await ctx.send(warning("The everyone role cannot be removed.\n\nPlease try again."))
        elif found_roles == set(current_roles):
            await ctx.send("No changes to make.")
        else:
            if punished:
                extra = f"\n\nRun `{ctx.prefix}punishset sync-roles` to apply the changes to punished members."
            else:
                extra = ""

            too_high = {r for r in found_roles if r > guild.me.top_role}

            if too_high:
                fmt_list = format_list(*(r.name for r in too_high))
                extra += "\n\n" + warning(
                    "These roles are too high for me to manage, and cannot be autoremoved until "
                    f"they are moved under my highest role ({guild.me.top_role}): {fmt_list}."
                )

            await self.config.guild(guild).REMOVE_ROLE_LIST.set([r.id for r in found_roles])

            fmt_list = format_list(*(r.name for r in found_roles))
            await ctx.send(f"Will remove these roles when a user is punished: {fmt_list}.{extra}")

    @punishset.command(name="nitro-role")
    async def punishset_nitro_role(self, ctx, *, role: str = None):
        """
        Set nitro booster role so its not removed when punishing.
        If your server doesn't have a nitro role, run this command with the role string `no_nitro_role`
        """
        guild = ctx.guild
        current = await self.config.guild(guild).NITRO_ID()
        current = role_from_string(guild, current)

        if role and role.lower() == "no_nitro_role":
            await self.config.guild(guild).NITRO_ID.set(role)
            await ctx.send("No nitro role set.")
            return

        if not role and current:
            await ctx.send(f"Nitro role set to {current}")
            return
        elif not role:
            await ctx.send("No nitro role defined.")
            return

        role = role_from_string(guild, role)
        if not role:
            await ctx.send("Role not found!")
            return

        await self.config.guild(guild).NITRO_ID.set(role.id)
        await ctx.send("Nitro role set!")

    @punishset.command(name="sync-roles")
    async def punishset_sync_roles(self, ctx):
        """
        Applies the remove-roles list to all punished users

        This operation may take some time to complete, depending on the number of members.
        """
        guild = ctx.guild
        punished = await self.config.guild(guild).PUNISHED()
        remove_roles = await self.config.guild(guild).REMOVE_ROLE_LIST()
        role_memo = Memoizer(role_from_string, guild)
        highest_role = guild.me.top_role
        count = 0
        errors = 0

        if not guild.me.guild_permissions.manage_roles:
            await ctx.send(error("I need the Manage Roles permission to do that."))
            return

        # (re)populate the member cache
        if guild.large:
            await self.bot.request_offline_members(guild)

        # Get current set of roles to remove
        guild_remove_roles = set(role_memo.filter(remove_roles, skip_nulls=True))

        for member_id, member_data in punished.items():

            member = guild.get_member(member_id)

            if not member:
                continue

            member_roles = set(member.roles)
            original_roles = member_roles.copy()

            try:
                # Combine sets to get the baseline (roles they'd have normally)
                member_roles |= set(role_memo.filter(member_data["removed_roles"], skip_nulls=True))
            except KeyError:
                pass

            # update new removed roles with intersection of guild removal list and baseline
            new_removed = guild_remove_roles & member_roles
            punished[str(member.id)]["removed_roles"] = [r.id for r in new_removed]

            member_roles -= guild_remove_roles

            # can't restore, so skip (remove from set)
            for role in member_roles - original_roles:
                if role >= highest_role:
                    member_roles.discard(role)

            # can't remove, so skip (re-add to set)
            for role in original_roles - member_roles:
                if role >= highest_role:
                    member_roles.add(role)

            # Now update roles if we need to
            if member_roles != original_roles:
                try:
                    await member.edit(roles=member_roles, reason="punish sync roles")
                except Exception:
                    log.exception(f"Couldn't modify roles in sync-roles command in {guild.name}!")
                    errors += 1
                else:
                    count += 1

        msg = f"Updated {count} members' roles."

        if errors:
            msg += "\n" + warning(f"{errors} errors occured; check the bot logs for more information.")

        await ctx.send(msg)

    @punishset.command(name="setup")
    async def punishset_setup(self, ctx):
        """
        (Re)configures the punish role and channel overrides
        """
        guild = ctx.guild
        default_name = DEFAULT_ROLE_NAME
        role_id = await self.config.guild(guild).ROLE_ID()

        if role_id:
            role = discord.utils.get(guild.roles, id=role_id)
        else:
            role = discord.utils.get(guild.roles, name=default_name)

        perms = guild.me.guild_permissions
        if not perms.manage_roles and perms.manage_channels:
            await ctx.send("I need the Manage Roles and Manage Channels permissions for that command to work.")
            return

        if not role:
            msg = "The %s role doesn't exist; Creating it now... " % default_name

            msgobj = await ctx.send(msg)

            perms = discord.Permissions.none()
            role = await guild.create_role(name=default_name, permissions=perms, reason="punish cog.")
        else:
            msgobj = await ctx.send("%s role exists... " % role.name)

        if role.position != (guild.me.top_role.position - 1):
            if role < guild.me.top_role:
                await msgobj.edit(content=msgobj.content + "moving role to higher position... ")
                await role.edit(position=guild.me.top_role.position - 1)
            else:
                await msgobj.edit(
                    content=msgobj.content + "role is too high to manage." " Please move it to below my highest role."
                )
                return

        await msgobj.edit(content=msgobj.content + "(re)configuring channels... ")

        for channel in guild.channels:
            await self.setup_channel(channel, role)

        await msgobj.edit(content=msgobj.content + "done.")

        if role and role.id != role_id:
            await self.config.guild(guild).ROLE_ID.set(role.id)

    @punishset.command(name="channel")
    async def punishset_channel(self, ctx, channel: discord.TextChannel = None):
        """
        Sets or shows the punishment "timeout" channel.

        This channel has special settings to allow punished users to discuss their
        infraction(s) with moderators.

        If there is a role deny on the channel for the punish role, it is
        automatically set to allow. If the default permissions don't allow the
        punished role to see or speak in it, an overwrite is created to allow
        them to do so.
        """
        guild = ctx.guild
        current = await self.config.guild(guild).CHANNEL_ID()
        current = current and guild.get_channel(current)

        if channel is None:
            if not current:
                await ctx.send("No timeout channel has been set.")
            else:
                await ctx.send("The timeout channel is currently %s." % current.mention)
        else:
            if current == channel:
                await ctx.send(
                    "The timeout channel is already %s. If you need to repair its permissions, use `%spunishset setup`."
                    % (current.mention, ctx.prefix)
                )
                return

            await self.config.guild(guild).CHANNEL_ID.set(channel.id)

            role = await self.get_role(guild, create=True)
            update_msg = "{} to the %s role" % role
            grants = []
            denies = []
            perms = permissions_for_roles(channel, role)
            overwrite = channel.overwrites_for(role) or discord.PermissionOverwrite()

            for perm, value in DEFAULT_TIMEOUT_OVERWRITE:
                if value is None:
                    continue

                if getattr(perms, perm) != value:
                    setattr(overwrite, perm, value)
                    name = perm.replace("_", " ").title().replace("Tts", "TTS")

                    if value:
                        grants.append(name)
                    else:
                        denies.append(name)

            # Any changes made? Apply them.
            if grants or denies:
                grants = grants and ("grant " + format_list(*grants))
                denies = denies and ("deny " + format_list(*denies))
                to_join = [x for x in (grants, denies) if x]
                update_msg = update_msg.format(format_list(*to_join))

                if current and current.id != channel.id:
                    if current.permissions_for(guild.me).manage_roles:
                        msg = info("Resetting permissions in the old channel (%s) to the default...")
                    else:
                        msg = error("I don't have permissions to reset permissions in the old channel (%s)")

                    await ctx.send(msg % current.mention)
                    await self.setup_channel(current, role)

                if channel.permissions_for(guild.me).manage_roles:
                    await ctx.send(info("Updating permissions in %s to %s..." % (channel.mention, update_msg)))
                    await channel.set_permissions(role, overwrite=overwrite)
                else:
                    await ctx.send(error("I don't have permissions to %s." % update_msg))

            await ctx.send("Timeout channel set to %s." % channel.mention)

    @punishset.command(name="clear-channel")
    async def punishset_clear_channel(self, ctx):
        """
        Clears the timeout channel and resets its permissions
        """
        guild = ctx.guild
        current = await self.config.guild(guild).CHANNEL_ID()
        current = current and guild.get_channel(current)

        if current:
            msg = None
            await self.config.guild(guild).CHANNEL_ID.set(None)

            if current.permissions_for(guild.me).manage_roles:
                role = await self.get_role(guild, quiet=True)
                await self.setup_channel(current, role)
                msg = " and its permissions reset"
            else:
                msg = ", but I don't have permissions to reset its permissions."

            await ctx.send("Timeout channel has been cleared%s." % msg)
        else:
            await ctx.send("No timeout channel has been set yet.")

    @punishset.command(name="case-min")
    async def punishset_case_min(self, ctx, *, timespec: str = None):
        """
        Set/disable or display the minimum punishment case duration

        If the punishment duration is less than this value, a case will not be created.
        Specify 'disable' to turn off case creation altogether.
        """
        guild = ctx.guild
        current = await self.config.guild(guild).CASE_MIN_LENGTH()

        if not timespec:
            if current:
                await ctx.send("Punishments longer than %s will create cases." % generate_timespec(current))
            else:
                await ctx.send("Punishment case creation is disabled.")
        else:
            if timespec.strip("'\"").lower() == "disable":
                value = None
            else:
                try:
                    value = parse_time(timespec)
                except BadTimeExpr as e:
                    await ctx.send(error(e.args[0]))
                    return

            await self.config.guild(guild).CASE_MIN_LENGTH.set(value)

            await ctx.send("Punishments longer than %s will create cases." % generate_timespec(value))

    @punishset.command(name="overrides")
    async def punishset_overrides(self, ctx, *, channel_id: int = None):
        """
        Copy or display the punish role overrides

        If a channel id is specified, the allow/deny settings for it are saved
        and applied to new channels when they are created. To apply the new
        settings to existing channels, use [p]punishset setup.

        An important caveat: voice channel and text channel overrides are
        configured separately! To set the overrides for a channel type,
        specify the name of or mention a channel of that type.
        """

        guild = ctx.guild
        role = await self.get_role(guild, quiet=True)
        timeout_channel_id = await self.config.guild(guild).CHANNEL_ID()
        confirm_msg = None
        channel = guild.get_channel(channel_id)

        if not role:
            await ctx.send(error("Punish role has not been created yet. Run `%spunishset setup` first." % ctx.prefix))
            return

        if channel:
            overwrite = channel.overwrites_for(role)
            if channel.id == timeout_channel_id:
                confirm_msg = "Are you sure you want to copy overrides from the timeout channel?"
            elif overwrite is None:
                overwrite = discord.PermissionOverwrite()
                confirm_msg = "Are you sure you want to copy blank (no permissions set) overrides?"
            else:
                confirm_msg = "Are you sure you want to copy overrides from this channel?"

            if channel.type is discord.ChannelType.text:
                key = "text"
            elif channel.type is discord.ChannelType.voice:
                key = "voice"
            else:
                await ctx.send(error("Unknown channel type!"))
                return

            if confirm_msg:
                await ctx.send(warning(confirm_msg + "(reply `yes` within 30s to confirm)"))

                def check(m):
                    return m.author == ctx.author and m.channel == ctx.channel

                try:
                    reply = await self.bot.wait_for("message", check=check, timeout=30.0)
                    if reply.content.strip(" `\"'").lower() != "yes":
                        await ctx.send("Commmand cancelled.")
                        return
                except asyncio.TimeoutError:
                    await ctx.send("Timed out waiting for a response.")
                    return

            if key == "text":
                await self.config.guild(guild).TEXT_OVERWRITE.set(overwrite_to_dict(overwrite))
            else:
                await self.config.guild(guild).VOICE_OVERWRITE.set(overwrite_to_dict(overwrite))

            await ctx.send(
                "{} channel overrides set to:\n".format(key.title())
                + format_permissions(overwrite)
                + "\n\nRun `%spunishset setup` to apply them to all channels." % ctx.prefix
            )
        else:
            msg = []
            for key in ("text", "voice"):
                if key == "text":
                    data = await self.config.guild(guild).TEXT_OVERWRITE()
                else:
                    data = await self.config.guild(guild).VOICE_OVERWRITE()
                title = "%s permission overrides:" % key.title()

                if data == overwrite_to_dict(DEFAULT_TEXT_OVERWRITE) or data == overwrite_to_dict(
                    DEFAULT_VOICE_OVERWRITE
                ):
                    title = title[:-1] + " (defaults):"

                msg.append(bold(title) + "\n" + format_permissions(overwrite_from_dict(data)))

            await ctx.send("\n\n".join(msg))

    @punishset.command(name="reset-overrides")
    async def punishset_reset_overrides(self, ctx, channel_type: str = "both"):
        """
        Resets the punish role overrides for text, voice or both (default)

        This command exists in case you want to restore the default settings
        for newly created channels.
        """

        channel_type = channel_type.strip("`\"' ").lower()

        msg = []
        for key in ("text", "voice"):
            if channel_type not in ["both", key]:
                continue

            title = "%s permission overrides reset to:" % key.title()

            if key == "text":
                await self.config.guild(guild).TEXT_OVERWRITE.set(overwrite_to_dict(DEFAULT_TEXT_OVERWRITE))
                msg.append(bold(title) + "\n" + format_permissions(overwrite_to_dict(DEFAULT_TEXT_OVERWRITE)))
            else:
                await self.config.guild(guild).VOICE_OVERWRITE.set(overwrite_to_dict(DEFAULT_VOICE_OVERWRITE))
                msg.append(bold(title) + "\n" + format_permissions(overwrite_to_dict(DEFAULT_VOICE_OVERWRITE)))

        if not msg:
            await ctx.send("Invalid channel type. Use `text`, `voice`, or `both` (the default, if not specified)")
            return

        msg.append("Run `%spunishset setup` to apply them to all channels." % ctx.prefix)

        await ctx.send("\n\n".join(msg))

    async def get_role(self, guild, quiet=False, create=False):
        role_id = await self.config.guild(guild).ROLE_ID()

        if role_id:
            role = discord.utils.get(guild.roles, id=role_id)
        else:
            role = discord.utils.get(guild.roles, name=DEFAULT_ROLE_NAME)

        if create and not role:
            perms = guild.me.guild_permissions
            if not perms.manage_roles and perms.manage_channels:
                await ctx.send("The Manage Roles and Manage Channels permissions are required to use this command.")
                return

            else:
                msg = "The %s role doesn't exist; Creating it now..." % DEFAULT_ROLE_NAME

                if not quiet:
                    msgobj = await ctx.send(msg)

                log.debug("Creating punish role in %s" % guild.name)
                perms = discord.Permissions.none()
                role = await guild.create_role(name=DEFAULT_ROLE_NAME, permissions=perms, reason="punish cog.")
                await role.edit(position=guild.me.top_role.position - 1)

                if not quiet:
                    await msgobj.edit(content=msgobj.content + "\nconfiguring channels... ")

                for channel in guild.channels:
                    await self.setup_channel(channel, role)

                if not quiet:
                    await msgobj.edit(content=msgobj.content + "\ndone.")

        if role and role.id != role_id:
            await self.config.guild(guild).ROLE_ID.set(role.id)

        return role

    async def setup_channel(self, channel, role):
        guild = channel.guild
        timeout_channel_id = await self.config.guild(guild).CHANNEL_ID()

        if channel.id == timeout_channel_id:
            # maybe this will be used later:
            # config = settings.get('TIMEOUT_OVERWRITE')
            config = None
            defaults = DEFAULT_TIMEOUT_OVERWRITE
        elif channel.type is discord.ChannelType.voice:
            config = await self.config.guild(guild).VOICE_OVERWRITE()
            defaults = DEFAULT_VOICE_OVERWRITE
        else:
            config = await self.config.guild(guild).TEXT_OVERWRITE()
            defaults = DEFAULT_TEXT_OVERWRITE

        if config:
            perms = overwrite_from_dict(config)
        else:
            perms = defaults

        await channel.set_permissions(role, overwrite=perms, reason="punish cog")

    async def on_load(self):
        await self.bot.wait_until_ready()

        for guild in self.bot.guilds:
            me = guild.me
            role = await self.get_role(guild, quiet=True, create=True)

            if not role:
                log.error("Needed to create punish role in %s, but couldn't." % guild.name)
                continue

            role_memo = Memoizer(role_from_string, guild)
            punished = await self.config.guild(guild).PUNISHED()

            for member_id, data in punished.items():

                until = data["until"]
                member = guild.get_member(member_id)

                if until and (until - time.time()) < 0:
                    if member:
                        reason = "Punishment removal overdue, maybe the bot was offline. "

                        if data["reason"]:
                            reason += data["reason"]

                        await self._unpunish(member, reason=reason)
                    else:  # member disappeared
                        del punished[str(member_id)]
                elif member:
                    # re-check roles
                    user_roles = set(member.roles)
                    removed_roles = set(role_memo.filter(data.get("removed_roles", ()), skip_nulls=True))
                    removed_roles = user_roles & {r for r in removed_roles if r < me.top_role}
                    user_roles -= removed_roles

                    apply_roles = removed_roles

                    if role not in user_roles:
                        if role >= me.top_role:
                            log.error("Needed to re-add punish role to %s in %s, but couldn't." % (member, guild.name))
                        else:
                            user_roles.add(role)  # add punish role to the set
                            apply_roles = True

                    if apply_roles:
                        await member.edit(roles=member_roles, reason="punish ending")

                    if until:
                        await self.schedule_unpunish(until, member)

        while True:
            try:
                async with self.queue_lock:
                    while await self.process_queue_event():
                        pass

                await asyncio.sleep(5)

            except asyncio.CancelledError:
                break
            except Exception:
                pass

        log.debug("queue manager dying")

        while not self.queue.empty():
            self.queue.get_nowait()

        for fut in self.pending.values():
            fut.cancel()

    async def cancel_queue_event(self, *args) -> bool:
        if args in self.pending:
            self.pending.pop(args).cancel()
            return True
        else:
            events = []
            removed = None

            async with self.queue_lock:
                while not self.queue.empty():
                    item = self.queue.get_nowait()

                    if args == item[1:]:
                        removed = item
                        break
                    else:
                        events.append(item)

                for item in events:
                    self.queue.put_nowait(item)

            return removed is not None

    async def put_queue_event(self, run_at: float, *args):
        diff = run_at - time.time()

        if args in self.enqueued:
            return False

        self.enqueued.add(args)

        if diff < 0:
            self.execute_queue_event(*args)
        elif run_at - time.time() < QUEUE_TIME_CUTOFF:
            self.pending[args] = asyncio.get_event_loop().call_later(diff, self.execute_queue_event, *args)
        else:
            await self.queue.put((run_at, *args))

    async def process_queue_event(self):
        if self.queue.empty():
            return False

        now = time.time()
        item = await self.queue.get()
        next_time, *args = item

        diff = next_time - now

        if diff < 0:
            if self.execute_queue_event(*args):
                return
        elif diff < QUEUE_TIME_CUTOFF:
            self.pending[args] = asyncio.get_event_loop().call_later(diff, self.execute_queue_event, *args)
            return True

        await self.queue.put(item)
        return False

    def execute_queue_event(self, *args) -> bool:
        self.enqueued.discard(args)

        try:
            return self.execute_unpunish(*args)
        except Exception:
            log.exception("failed to execute scheduled event")

    async def _punish_cmd_common(self, ctx, member, duration, reason, quiet=False):
        guild = ctx.guild
        using_default = False
        updating_case = False
        case_error = None

        remove_role_set = await self.config.guild(guild).REMOVE_ROLE_LIST()
        remove_role_set = set(resolve_role_list(guild, remove_role_set))
        punished = await self.config.guild(guild).PUNISHED()
        current = punished.get(str(member.id), {})
        reason = reason or current.get("reason")  # don't clear if not given
        hierarchy_allowed = ctx.author.top_role > member.top_role
        case_min_length = await self.config.guild(guild).CASE_MIN_LENGTH()
        nitro_role = await self.config.guild(guild).NITRO_ID()

        if nitro_role is None:
            await ctx.send(f"Please set the nitro role using `{ctx.prefix}punishset nitro-role`")
            return

        if member == guild.me:
            await ctx.send("You can't punish the bot.")
            return

        if duration and duration.lower() in ["forever", "inf", "infinite"]:
            duration = None
        else:
            if not duration:
                using_default = True
                duration = DEFAULT_TIMEOUT
            try:
                duration = parse_time(duration)
                if duration < 1:
                    await ctx.send("Duration must be 1 second or longer.")
                    return False
            except BadTimeExpr as e:
                await ctx.send("Error parsing duration: %s." % e.args)
                return False

        role = await self.get_role(guild, quiet=quiet, create=True)

        if role is None:
            return
        elif role >= guild.me.top_role:
            await ctx.send("The %s role is too high for me to manage." % role)
            return

        # Call time() after getting the role due to potential creation delay
        now = time.time()
        until = (now + duration + 0.5) if duration else None
        duration_ok = (case_min_length is not None) and ((duration is None) or duration >= case_min_length)

        if duration_ok:
            now_date = datetime.utcfromtimestamp(now)
            mod_until = until and datetime.utcfromtimestamp(until)

            try:
                if current:
                    case_number = current.get("caseno")
                    try:
                        case = await modlog.get_case(case_number, guild, self.bot)
                    except:  # shouldn't happen
                        await ctx.send(
                            warning(
                                "Error, modlog case not found, but user is punished with case.\nTry unpunishing and punishing again."
                            )
                        )
                        return

                    moderator = ctx.author

                    try:
                        edits = {"reason": reason}

                        if moderator.id != current.get("by"):
                            edits["amended_by"] = moderator

                        edits["modified_at"] = ctx.message.created_at.timestamp()

                        await case.edit(edits)
                    except Exception as e:
                        await ctx.send(warning(f"Couldn't edit case: {e}"))
                        return

                    updating_case = True

                else:
                    case = await modlog.create_case(
                        self.bot,
                        guild,
                        now_date,
                        "Timed Mute",
                        member,
                        moderator=ctx.author,
                        reason=reason,
                        until=mod_until,
                    )
                    case_number = case.case_number

            except Exception as e:
                case_error = e
        else:
            case_number = None

        subject = "the %s role" % role.name

        if str(member.id) in punished:
            if role in member.roles:
                msg = "{0} already had the {1.name} role; resetting their timer."
            else:
                msg = "{0} is missing the {1.name} role for some reason. I added it and reset their timer."
        elif role in member.roles:
            msg = "{0} already had the {1.name} role, but had no timer; setting it now."
        else:
            msg = "Applied the {1.name} role to {0}."
            subject = "it"

        msg = msg.format(member, role)

        if duration:
            timespec = generate_timespec(duration)

            if using_default:
                timespec += " (the default)"

            msg += " I will remove %s in %s." % (subject, timespec)

        if case_error:
            if isinstance(case_error, CaseMessageNotFound):
                case_error = "the case message could not be found"
            elif isinstance(case_error, NoModLogAccess):
                case_error = "I do not have access to the modlog channel"
            else:
                case_error = None

            if case_error:
                verb = "updating" if updating_case else "creating"
                msg += "\n\n" + warning("There was an error %s the modlog case: %s." % (verb, case_error))
        elif case_number:
            verb = "updated" if updating_case else "created"
            msg += " I also %s case #%i in the modlog." % (verb, case_number)

        voice_overwrite = await self.config.guild(guild).VOICE_OVERWRITE()

        if voice_overwrite:
            voice_overwrite = overwrite_from_dict(voice_overwrite)
        else:
            voice_overwrite = DEFAULT_VOICE_OVERWRITE

        voice_deny = voice_overwrite.pair()[1]
        overwrite_denies_speak = (voice_deny.speak is False) or (voice_deny.connect is False)

        # remove all roles from user that are specified in remove_role_list, only if its a new punish
        if str(member.id) not in punished:
            if nitro_role != "no_nitro_role":
                nitro_role = role_from_string(guild, nitro_role)
                remove_role_set.discard(nitro_role)

            user_roles = set(member.roles)
            # build lists of roles that *should* be removed and ones that *can* be
            removed_roles = user_roles & remove_role_set
            too_high_to_remove = {r for r in removed_roles if r >= guild.me.top_role}
            user_roles -= removed_roles - too_high_to_remove
            user_roles.add(role)  # add punish role to the set
            await member.edit(roles=user_roles, reason=f"punish {member}")

        else:
            removed_roles = set(resolve_role_list(guild, current.get("removed_roles", [])))
            too_high_to_remove = {r for r in removed_roles if r >= guild.me.top_role}

        if removed_roles:
            actually_removed = removed_roles - too_high_to_remove
            if actually_removed:
                msg += "\nRemoved roles: {}".format(format_list(*(r.name for r in actually_removed)))

            if too_high_to_remove:
                fmt_list = format_list(*(r.name for r in removed_roles))
                msg += "\n" + warning(
                    "These roles were too high to remove (fix hierarchy, then run "
                    "`{}punishset sync-roles`): {}".format(ctx.prefix, fmt_list)
                )
        if member.voice:
            muted = member.voice.mute
        else:
            muted = False

        async with self.config.guild(guild).PUNISHED() as punished:
            punished[str(member.id)] = {
                "start": current.get("start") or now,  # don't override start time if updating
                "until": until,
                "by": current.get("by") or ctx.author.id,  # don't override original moderator
                "reason": reason,
                "unmute": overwrite_denies_speak and not muted,
                "caseno": case_number,
                "removed_roles": [r.id for r in removed_roles],
            }

        if member.voice and overwrite_denies_speak:
            if member.voice.channel:
                await member.edit(mute=True)

        # schedule callback for role removal
        if until:
            await self.schedule_unpunish(until, member)

        if not quiet:
            await ctx.send(msg)

        return True

    # Functions related to unpunishing

    async def schedule_unpunish(self, until, member):
        """
        Schedules role removal, canceling and removing existing tasks if present
        """

        await self.put_queue_event(until, member.guild.id, member.id)

    def execute_unpunish(self, guild_id, member_id) -> bool:
        guild = self.bot.get_guild(guild_id)

        if not guild:
            return False

        member = guild.get_member(member_id)

        if member:
            asyncio.create_task(self._unpunish(member))
            return True
        else:
            asyncio.create_task(self.bot.request_offline_members(guild))
            return False

    async def _unpunish(self, member, reason=None, apply_roles=True, update=False, moderator=None, quiet=False) -> bool:
        """
        Remove punish role, delete record and task handle
        """
        guild = member.guild
        role = await self.get_role(guild, quiet=True)
        nitro_role = await self.config.guild(guild).NITRO_ID()

        if role:
            data = await self.config.guild(guild).PUNISHED()
            member_data = data.get(str(member.id), {})
            caseno = member_data.get("caseno")
            removed_roles = set(resolve_role_list(guild, member_data.get("removed_roles", [])))

            # Has to be done first to prevent triggering listeners
            await self._unpunish_data(member)
            await self.cancel_queue_event(member.guild.id, member.id)

            if apply_roles:

                # readd removed roles from user, by replacing user's roles with all of their roles plus the ones that
                # were removed (and can be re-added), minus the punish role
                user_roles = set(member.roles)
                too_high_to_restore = {r for r in removed_roles if r >= guild.me.top_role}
                removed_roles -= too_high_to_restore
                user_roles |= removed_roles
                user_roles.discard(role)
                await member.edit(roles=user_roles, reason="punish end")

            if update and caseno:
                until = member_data.get("until") or False
                # fallback gracefully
                moderator = moderator or guild.get_member(member_data.get("by")) or guild.me

                if until:
                    until = datetime.utcfromtimestamp(until).timestamp()

                edits = {"reason": reason}

                if moderator.id != data.get("by"):
                    edits["amended_by"] = moderator

                edits["modified_at"] = time.time()
                edits["until"] = until

                try:
                    case = await modlog.get_case(caseno, guild, self.bot)
                    await case.edit(edits)
                except Exception:
                    pass

            if member_data.get("unmute", False):
                if member.voice:
                    if member.voice.channel:
                        await member.edit(mute=False)
                else:
                    async with self.config.guild(guild).PENDING_UNMUTE() as unmute_list:
                        if member.id not in unmute_list:
                            unmute_list.append(member.id)

            if quiet:
                return True

            msg = "Your punishment in %s has ended." % member.guild.name

            if reason:
                msg += "\nReason: %s" % reason

            if removed_roles:
                msg += "\n\nRestored roles: {}.".format(format_list(*(r.name for r in removed_roles)))

                if too_high_to_restore:
                    fmt_list = format_list(*(r.name for r in too_high_to_restore))
                    msg += "\n" + warning(
                        "These roles were too high for me to restore: {}. " "Ask a mod for help.".format(fmt_list)
                    )

            try:
                await member.send(msg)
                return True
            except Exception:
                return False

    async def _unpunish_data(self, member):
        """Removes punish data entry and cancels any present callback"""
        guild = member.guild

        async with self.config.guild(guild).PUNISHED() as punished:
            if str(member.id) in punished:
                del punished[str(member.id)]

    # Listeners
    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel):
        """Run when new channels are created and set up role permissions"""
        role = await self.get_role(channel.guild, quiet=True)
        if not role:
            return

        await self.setup_channel(channel, role)

    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        """Remove scheduled unpunish when manually removed role"""
        try:
            assert before.roles != after.roles
            guild_data = await self.config.guild(before.guild).PUNISHED()
            member_data = guild_data[str(before.id)]
            role = await self.get_role(before.guild, quiet=True)
            assert role
        except (KeyError, AssertionError):
            return

        new_roles = {role.id: role for role in after.roles}

        if role in before.roles and role.id not in new_roles:
            msg = "Punishment manually ended early by a moderator/admin."

            if member_data["reason"]:
                msg += "\nReason was: " + member_data["reason"]

            await self._unpunish(after, reason=msg, update=True)
        else:
            to_remove = {new_roles.get(role_id) for role_id in member_data.get("removed_roles", [])}
            to_remove = [r for r in to_remove if r and r < after.guild.me.top_role]

            if to_remove:
                await after.remove_roles(*to_remove)

    @commands.Cog.listener()
    async def on_member_join(self, member):
        """Restore punishment if punished user leaves/rejoins"""
        guild = member.guild
        punished = await self.config.guild(guild).PUNISHED()
        data = punished.get(str(member.id), {})

        if not data:
            return

        # give other tools a chance to settle, then re-fetch data just in case
        await asyncio.sleep(1)
        member = self.bot.get_guild(guild.id).get_member(member.id)
        role = await self.get_role(member.guild, quiet=True)

        until = data["until"]
        duration = until - time.time()

        if role and duration > 0:
            await self.schedule_unpunish(until, member)

            if role not in member.roles:
                await member.add_roles(role)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if not after.channel:
            return

        guild = member.guild
        data = await self.config.guild(guild).PUNISHED()
        member_data = data.get(str(member.id), {})
        unmute_list = await self.config.guild(guild).PENDING_UNMUTE()

        if member_data and not after.mute:
            await member.edit(mute=True)
        elif member.id in unmute_list:
            await member.edit(mute=False)
            if member.id in unmute_list:
                unmute_list.remove(member.id)

            await self.config.guild(guild).PENDING_UNMUTE.set(unmute_list)

    @commands.Cog.listener()
    async def on_member_ban(self, member):
        """Remove punishment record when member is banned."""
        guild = member.guild
        data = await self.config.guild(guild).PUNISHED()
        member_data = data.get(str(member.id))

        if member_data is None:
            return

        msg = "Punishment ended early due to ban."

        if member_data.get("reason"):
            msg += "\n\nOriginal reason was: " + member_data["reason"]

        await self._unpunish(member, reason=msg, apply_roles=False, update=True, quiet=True)
