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
from typing import Literal
import inspect
import logging
import time
import textwrap

log = logging.getLogger("red.isolate")

__version__ = "3.0.0"

PURGE_MESSAGES = 1  # for cisolate

DEFAULT_ROLE_NAME = "Isolated"
DEFAULT_TEXT_OVERWRITE = discord.PermissionOverwrite(
    send_messages=False, send_tts_messages=False, add_reactions=False, read_messages=False
)
DEFAULT_VOICE_OVERWRITE = discord.PermissionOverwrite(speak=False, connect=False, view_channel=False)
DEFAULT_TIMEOUT_OVERWRITE = discord.PermissionOverwrite(
    send_messages=True, read_messages=True, read_message_history=True
)

QUEUE_TIME_CUTOFF = 30

DEFAULT_TIMEOUT = "5m"
DEFAULT_CASE_MIN_LENGTH = "5m"  # only create modlog cases when length is longer than this


class Isolate(commands.Cog):
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
            "ISOLATED": {},
            "CASE_MIN_LENGTH": parse_time(DEFAULT_CASE_MIN_LENGTH),
            "PENDING_UNMUTE": [],
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
        isolate_case = {
            "name": "Timed Mute",
            "default_setting": True,
            "image": "\N{HOURGLASS WITH FLOWING SAND}\N{SPEAKER WITH CANCELLATION STROKE}",
            "case_str": "Timed Mute",
        }
        try:
            await modlog.register_casetype(**isolate_case)
        except RuntimeError:
            pass

    @commands.group(invoke_without_command=True)
    @commands.guild_only()
    @checks.mod()
    async def isolate(self, ctx, user: discord.Member, duration: str = None, *, reason: str = None):
        """
        Puts a user into timeout for a specified time, with optional reason.

        Time specification is any combination of number with the units s,m,h,d,w.
        Example: !isolate @idiot 1.1h10m Breaking rules
        """
        if ctx.invoked_subcommand:
            return
        elif user:
            await self._isolate_cmd_common(ctx, user, duration, reason)

    @isolate.command(name="cstart")
    @commands.guild_only()
    @checks.mod()
    async def isolate_cstart(self, ctx, user: discord.Member, duration: str = None, *, reason: str = None):
        """
        Same as [p]isolate start, but cleans up the target's last message.
        """

        success = await self._isolate_cmd_common(ctx, user, duration, reason, quiet=True)

        if not success:
            return

        def check(m):
            return m.id == ctx.message.id or m.author == user

        try:
            await ctx.message.channel.purge(limit=PURGE_MESSAGES + 1, check=check)
        except discord.errors.Forbidden:
            await ctx.send("Isolation set, but I need permissions to manage messages to clean up.")

    @isolate.command(name="list")
    @commands.guild_only()
    @checks.mod()
    async def isolate_list(self, ctx):
        """
        Shows a table of isolated users with time, mod and reason.

        Displays isolated users, time remaining, responsible moderator and
        the reason for isolation, if any.
        """

        guild = ctx.guild
        guild_id = guild.id
        now = time.time()
        headers = ["Member", "Remaining", "Moderator", "Reason"]
        isolated = await self.config.guild(guild).ISOLATED()

        embeds = []
        num_p = len(isolated)
        for i, data in enumerate(isolated.items()):
            member_id, data = data
            member_name = getmname(member_id, guild)
            moderator = getmname(data["by"], guild)
            reason = data["reason"]
            until = data["until"]
            sort = until or float("inf")
            remaining = generate_timespec(until - now, short=True) if until else "forever"

            row = [member_name, remaining, moderator, reason or "No reason set."]
            embed = discord.Embed(title="Isolate List", colour=discord.Colour.from_rgb(255, 0, 0))

            for header, row_val in zip(headers, row):
                embed.add_field(name=header, value=row_val)

            embed.set_footer(text=f"Page {i+1} out of {num_p}")
            embeds.append(embed)

        if not isolated:
            await ctx.send("No users are currently isolated.")
            return

        await menu(ctx, embeds, DEFAULT_CONTROLS)

    @isolate.command(name="clean")
    @commands.guild_only()
    @checks.mod()
    async def isolate_clean(self, ctx, clean_pending: bool = False):
        """
        Removes absent members from the isolated list.

        If run without an argument, it only removes members who are no longer
        present but whose timer has expired. If the argument is 'yes', 1,
        or another trueish value, it will also remove absent members whose
        timers have yet to expire.

        Use this option with care, as removing them will prevent the isolated
        role from being re-added if they rejoin before their timer expires.
        """

        count = 0
        now = time.time()
        guild = ctx.guild
        data = await self.config.guild(guild).ISOLATED()

        for mid, mdata in data.copy().items():
            intid = int(mid)
            if guild.get_member(intid):
                continue

            elif clean_pending or ((mdata["until"] or 0) < now):
                del data[mid]
                count += 1

        await self.config.guild(guild).ISOLATED.set(data)
        await ctx.send("Cleaned %i absent members from the list." % count)

    @isolate.command(name="clean-bans")
    @commands.guild_only()
    @checks.mod()
    @checks.bot_has_permissions(ban_members=True)
    async def isolate_clean_bans(self, ctx):
        """
        Removes banned members from the isolated list.
        """

        count = 0
        guild = ctx.guild
        data = await self.config.guild(guild).ISOLATED()

        bans = await guild.bans()
        ban_ids = {ban.user.id for ban in bans}

        for mid, mdata in data.copy().items():
            intid = int(mid)
            if guild.get_member(intid):
                continue

            elif intid in ban_ids:
                del data[mid]
                count += 1

        await self.config.guild(guild).ISOLATED.set(data)
        await ctx.send("Cleaned %i banned users from the list." % count)

    @isolate.command(name="warn")
    @commands.guild_only()
    @checks.mod_or_permissions(manage_messages=True)
    async def isolate_warn(self, ctx, user: discord.Member, *, reason: str = None):
        """
        Warns a user with boilerplate about the rules
        """

        msg = ["Hey %s, " % user.mention]
        msg.append("you're doing something that might get you muted if you keep " "doing it.")
        if reason:
            msg.append(" Specifically, %s." % reason)

        msg.append("Be sure to review the guild rules.")
        await ctx.send(" ".join(msg))

    @isolate.command(name="end", aliases=["remove"])
    @commands.guild_only()
    @checks.mod()
    async def isolate_end(self, ctx, user: discord.Member, *, reason: str = None):
        """
        Removes Isolation from a user before time has expired

        This is the same as removing the role directly.
        """

        role = await self.get_role(user.guild, quiet=True)
        sid = user.guild.id
        guild = user.guild
        moderator = ctx.author
        now = time.time()
        isolated = await self.config.guild(guild).ISOLATED()
        data = isolated.get(str(user.id), {})
        removed_roles_parsed = resolve_role_list(guild, data.get("removed_roles", []))

        if role and role in user.roles:
            msg = "Isolation manually ended early by %s." % ctx.author

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

            if not await self._unisolate(user, reason=updated_reason, update=True, moderator=moderator):
                msg += "\n\n(failed to send Isolation end notification DM)"

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
            del isolated[str(user.id)]
            await self.config.guild(guild).ISOLATED.set(isolated)

            await ctx.send(
                "That user doesn't have the %s role, but they still have a data entry. I removed it, "
                "but in case it's needed, this is what was there:\n\n%s" % (role.name, data_fmt)
            )
        elif role:
            await ctx.send("That user doesn't have the %s role." % role.name)
        else:
            await ctx.send("The isolate role couldn't be found in this guild.")

    @isolate.command(name="reason")
    @commands.guild_only()
    @checks.mod()
    async def isolate_reason(self, ctx, user: discord.Member, *, reason: str = None):
        """
        Updates the reason for a Isolation, including the modlog if a case exists.
        """
        guild = ctx.guild
        isolated = await self.config.guild(guild).ISOLATED()
        data = isolated.get(str(user.id), None)

        if not data:
            await ctx.send(
                "That user doesn't have an active Isolation entry. To update modlog "
                "cases manually, use the `%sreason` command." % ctx.prefix
            )
            return

        isolated[str(user.id)]["reason"] = reason
        await self.config.guild(guild).ISOLATED.set(isolated)

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
    async def isolateset(self, ctx):
        pass

    @isolateset.command(name="nitro-role")
    async def isolateset_nitro_role(self, ctx, *, role: str = None):
        """
        Set nitro booster role so its not removed when isolateing.
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

    @isolateset.command(name="sync-roles")
    async def isolateset_sync_roles(self, ctx):
        """
        Applies the remove-roles list to all isolated users

        This operation may take some time to complete, depending on the number of members.
        """
        guild = ctx.guild
        isolated = await self.config.guild(guild).ISOLATED()
        role = await self.config.guild(guild).ROLE_ID()
        nitro = await self.config.guild(guild).NITRO_ID()
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

        for member_id, member_data in isolated.items():

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

            guild_remove_roles = [r for r in member_roles if r.id != role and r.id != nitro and r.name != "@everyone"]

            # update new removed roles with intersection of guild removal list and baseline
            new_removed = guild_remove_roles & member_roles
            isolated[str(member.id)]["removed_roles"] = [r.id for r in new_removed]

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
                    await member.edit(roles=member_roles, reason="isolate sync roles")
                except Exception:
                    log.exception(f"Couldn't modify roles in sync-roles command in {guild.name}!")
                    errors += 1
                else:
                    count += 1

        msg = f"Updated {count} members' roles."

        if errors:
            msg += "\n" + warning(f"{errors} errors occured; check the bot logs for more information.")

        await ctx.send(msg)

    @isolateset.command(name="setup")
    async def isolateset_setup(self, ctx):
        """
        (Re)configures the isolate role and channel overrides
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
            role = await guild.create_role(name=default_name, permissions=perms, reason="isolate cog.")
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

    @isolateset.command(name="channel")
    async def isolateset_channel(self, ctx, channel: discord.TextChannel = None):
        """
        Sets or shows the isolation "timeout" channel.

        This channel has special settings to allow isolated users to discuss their
        infraction(s) with moderators.

        If there is a role deny on the channel for the isolate role, it is
        automatically set to allow. If the default permissions don't allow the
        isolated role to see or speak in it, an overwrite is created to allow
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
                    "The timeout channel is already %s. If you need to repair its permissions, use `%sisolateset setup`."
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

    @isolateset.command(name="clear-channel")
    async def isolateset_clear_channel(self, ctx):
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

    @isolateset.command(name="case-min")
    async def isolateset_case_min(self, ctx, *, timespec: str = None):
        """
        Set/disable or display the minimum isolation case duration

        If the isolation duration is less than this value, a case will not be created.
        Specify 'disable' to turn off case creation altogether.
        """
        guild = ctx.guild
        current = await self.config.guild(guild).CASE_MIN_LENGTH()

        if not timespec:
            if current:
                await ctx.send("Isolations longer than %s will create cases." % generate_timespec(current))
            else:
                await ctx.send("Isolation case creation is disabled.")
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

            await ctx.send("Isolations longer than %s will create cases." % generate_timespec(value))

    @isolateset.command(name="overrides")
    async def isolateset_overrides(self, ctx, *, channel_id: int = None):
        """
        Copy or display the isolate role overrides

        If a channel id is specified, the allow/deny settings for it are saved
        and applied to new channels when they are created. To apply the new
        settings to existing channels, use [p]isolateset setup.

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
            await ctx.send(error("Isolate role has not been created yet. Run `%sisolateset setup` first." % ctx.prefix))
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
                + "\n\nRun `%sisolateset setup` to apply them to all channels." % ctx.prefix
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

    @isolateset.command(name="reset-overrides")
    async def isolateset_reset_overrides(self, ctx, channel_type: str = "both"):
        """
        Resets the isolate role overrides for text, voice or both (default)

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

        msg.append("Run `%sisolateset setup` to apply them to all channels." % ctx.prefix)

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

                log.debug("Creating isolate role in %s" % guild.name)
                perms = discord.Permissions.none()
                role = await guild.create_role(name=DEFAULT_ROLE_NAME, permissions=perms, reason="isolate cog.")
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

        await channel.set_permissions(role, overwrite=perms, reason="isolate cog")

    async def on_load(self):
        await self.bot.wait_until_ready()

        _guilds = [g for g in self.bot.guilds if g.large and not (g.chunked or g.unavailable)]
        await self.bot.request_offline_members(*_guilds)

        for guild in self.bot.guilds:
            me = guild.me
            role = await self.get_role(guild, quiet=True, create=True)

            if not role:
                log.error("Needed to create isolate role in %s, but couldn't." % guild.name)
                continue

            role_memo = Memoizer(role_from_string, guild)
            isolated = await self.config.guild(guild).ISOLATED()

            for member_id, data in isolated.items():

                until = data["until"]
                member = guild.get_member(int(member_id))

                if until and (until - time.time()) < 0:
                    if member:
                        reason = "Isolation removal overdue, maybe the bot was offline. "

                        if data["reason"]:
                            reason += data["reason"]

                        await self._unisolate(member, reason=reason)
                    else:  # member disappeared
                        del isolated[member_id]
                elif member:
                    # re-check roles
                    user_roles = set(member.roles)
                    removed_roles = set(role_memo.filter(data.get("removed_roles", ()), skip_nulls=True))
                    removed_roles = user_roles & {r for r in removed_roles if r < me.top_role}
                    user_roles -= removed_roles

                    apply_roles = removed_roles

                    if role not in user_roles:
                        if role >= me.top_role:
                            log.error("Needed to re-add isolate role to %s in %s, but couldn't." % (member, guild.name))
                        else:
                            user_roles.add(role)  # add isolate role to the set
                            apply_roles = True

                    if apply_roles:
                        await member.edit(roles=member_roles, reason="isolate ending")

                    if until:
                        await self.schedule_unisolate(until, member)

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
            await self.execute_queue_event(0, *args)
        elif run_at - time.time() < QUEUE_TIME_CUTOFF:
            self.pending[args] = asyncio.create_task(self.execute_queue_event(diff, *args))
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
            if await self.execute_queue_event(0, *args):
                return
        elif diff < QUEUE_TIME_CUTOFF:
            self.pending[args] = asyncio.create_task(self.execute_queue_event(diff, *args))
            return True

        await self.queue.put(item)
        return False

    async def execute_queue_event(self, diff, *args) -> bool:
        # delays then executes queue event
        await asyncio.sleep(diff)
        self.enqueued.discard(args)

        try:
            return self.execute_unisolate(*args)
        except Exception:
            log.exception("failed to execute scheduled event")

    async def _isolate_cmd_common(self, ctx, member, duration, reason, quiet=False):
        guild = ctx.guild
        using_default = False
        updating_case = False
        case_error = None

        isolated = await self.config.guild(guild).ISOLATED()
        current = isolated.get(str(member.id), {})
        reason = reason or current.get("reason")  # don't clear if not given
        hierarchy_allowed = ctx.author.top_role > member.top_role
        case_min_length = await self.config.guild(guild).CASE_MIN_LENGTH()
        nitro_role = await self.config.guild(guild).NITRO_ID()

        if nitro_role is None:
            await ctx.send(f"Please set the nitro role using `{ctx.prefix}isolateset nitro-role`")
            return

        if member == guild.me:
            await ctx.send("You can't isolate the bot.")
            return

        # check if user is isolated, fix conflict with isolate cog
        punish = self.bot.get_cog("Punish")

        if punish:
            punished = await punish.config.guild(guild).PUNISHED()
            if str(member.id) in punished:
                await ctx.send(
                    warning("This person is punished, I will remove it now before isolating to avoid conflicts.")
                )
                await ctx.invoke(punish.punish_end, user=member, reason="Conflict with isolate cog.")
            # double check it actually worked
            punished = await punish.config.guild(guild).PUNISHED()
            if str(member.id) in punished:
                await ctx.send(error("Couldn't remove punish from user, please do it manually."))
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
                                "Error, modlog case not found, but user is isolated with case.\nTry unisolating and isolating again."
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

        if str(member.id) in isolated:
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

        # remove all roles from user that are specified in remove_role_list, only if its a new isolati
        if str(member.id) not in isolated:
            user_roles = {r for r in member.roles if r.name != "@everyone"}
            removed_roles = user_roles.copy()
            if nitro_role != "no_nitro_role":
                nitro_role = role_from_string(guild, nitro_role)
                removed_roles.discard(nitro_role)

            # build lists of roles that *should* be removed and ones that *can* be
            too_high_to_remove = {r for r in removed_roles if r >= guild.me.top_role}
            user_roles -= removed_roles - too_high_to_remove
            user_roles.add(role)  # add isolate role to the set
            await member.edit(roles=user_roles, reason=f"isolate {member}")

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
                    "`{}isolateset sync-roles`): {}".format(ctx.prefix, fmt_list)
                )
        if member.voice:
            muted = member.voice.mute
        else:
            muted = False

        async with self.config.guild(guild).ISOLATED() as isolated:
            isolated[str(member.id)] = {
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
                await member.edit(mute=True, deafen=True)

        # schedule callback for role removal
        if until:
            await self.schedule_unisolate(until, member)

        if not quiet:
            await ctx.send(msg)

        return True

    # Functions related to unisolateing

    async def schedule_unisolate(self, until, member):
        """
        Schedules role removal, canceling and removing existing tasks if present
        """

        await self.put_queue_event(until, member.guild.id, member.id)

    def execute_unisolate(self, guild_id, member_id) -> bool:
        guild = self.bot.get_guild(guild_id)

        if not guild:
            return False

        member = guild.get_member(member_id)

        if member:
            asyncio.create_task(self._unisolate(member))
            return True
        else:
            asyncio.create_task(self.bot.request_offline_members(guild))
            return False

    async def _unisolate(
        self, member, reason=None, apply_roles=True, update=False, moderator=None, quiet=False
    ) -> bool:
        """
        Remove isolate role, delete record and task handle
        """
        guild = member.guild
        role = await self.get_role(guild, quiet=True)
        nitro_role = await self.config.guild(guild).NITRO_ID()

        if role:
            data = await self.config.guild(guild).ISOLATED()
            member_data = data.get(str(member.id), {})
            caseno = member_data.get("caseno")
            removed_roles = set(resolve_role_list(guild, member_data.get("removed_roles", [])))

            # Has to be done first to prevent triggering listeners
            await self._unisolate_data(member)
            await self.cancel_queue_event(member.guild.id, member.id)

            if apply_roles:

                # readd removed roles from user, by replacing user's roles with all of their roles plus the ones that
                # were removed (and can be re-added), minus the isolate role
                user_roles = set(member.roles)
                too_high_to_restore = {r for r in removed_roles if r >= guild.me.top_role}
                removed_roles -= too_high_to_restore
                user_roles |= removed_roles
                user_roles.discard(role)
                await member.edit(roles=user_roles, reason="isolate end")

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
                        await member.edit(mute=False, deafen=False)
                else:
                    async with self.config.guild(guild).PENDING_UNMUTE() as unmute_list:
                        if member.id not in unmute_list:
                            unmute_list.append(member.id)

            if quiet:
                return True

            msg = "Your Isolation in %s has ended." % member.guild.name

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

    async def _unisolate_data(self, member):
        """Removes isolate data entry and cancels any present callback"""
        guild = member.guild

        async with self.config.guild(guild).ISOLATED() as isolated:
            if str(member.id) in isolated:
                del isolated[str(member.id)]

    # Listeners
    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel):
        """Run when new channels are created and set up role permissions"""
        if await self.bot.cog_disabled_in_guild(self, channel.guild):
            return
        role = await self.get_role(channel.guild, quiet=True)
        if not role:
            return

        await self.setup_channel(channel, role)

    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        """Remove scheduled unisolate when manually removed role"""
        if await self.bot.cog_disabled_in_guild(self, after.guild):
            return
        try:
            assert before.roles != after.roles
            guild_data = await self.config.guild(before.guild).ISOLATED()
            member_data = guild_data[str(before.id)]
            role = await self.get_role(before.guild, quiet=True)
            assert role
        except (KeyError, AssertionError):
            return

        new_roles = {role.id: role for role in after.roles}

        if role in before.roles and role.id not in new_roles:
            msg = "Isolation manually ended early by a moderator/admin."

            if member_data["reason"]:
                msg += "\nReason was: " + member_data["reason"]

            await self._unisolate(after, reason=msg, update=True)
        else:
            to_remove = {new_roles.get(role_id) for role_id in member_data.get("removed_roles", [])}
            to_remove = [r for r in to_remove if r and r < after.guild.me.top_role]

            if to_remove:
                await after.remove_roles(*to_remove)

    @commands.Cog.listener()
    async def on_member_join(self, member):
        """Restore Isolation if isolated user leaves/rejoins"""
        if await self.bot.cog_disabled_in_guild(self, member.guild):
            return
        guild = member.guild
        isolated = await self.config.guild(guild).ISOLATED()
        data = isolated.get(str(member.id), {})

        if not data:
            return

        # give other tools a chance to settle, then re-fetch data just in case
        await asyncio.sleep(1)
        member = self.bot.get_guild(guild.id).get_member(member.id)
        role = await self.get_role(member.guild, quiet=True)

        until = data["until"]
        duration = until - time.time()

        if role and duration > 0:
            await self.schedule_unisolate(until, member)

            if role not in member.roles:
                await member.add_roles(role)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if await self.bot.cog_disabled_in_guild(self, member.guild):
            return
        if not after.channel:
            return

        guild = member.guild
        data = await self.config.guild(guild).ISOLATED()
        member_data = data.get(str(member.id), {})
        unmute_list = await self.config.guild(guild).PENDING_UNMUTE()

        if member_data and not after.mute:
            await member.edit(mute=True, deafen=True)
        elif member.id in unmute_list:
            await member.edit(mute=False, deafen=False)
            if member.id in unmute_list:
                unmute_list.remove(member.id)

            await self.config.guild(guild).PENDING_UNMUTE.set(unmute_list)

    @commands.Cog.listener()
    async def on_member_ban(self, member):
        """Remove Isolation record when member is banned."""
        if await self.bot.cog_disabled_in_guild(self, member.guild):
            return
        guild = member.guild
        data = await self.config.guild(guild).ISOLATED()
        member_data = data.get(str(member.id))

        if member_data is None:
            return

        msg = "Isolation ended early due to ban."

        if member_data.get("reason"):
            msg += "\n\nOriginal reason was: " + member_data["reason"]

        await self._unisolate(member, reason=msg, apply_roles=False, update=True, quiet=True)

    async def red_delete_data_for_user(
        self,
        *,
        requester: Literal["discord_deleted_user", "owner", "user", "user_strict"],
        user_id: int,
    ):
        pass
