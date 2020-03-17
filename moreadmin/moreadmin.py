from redbot.core.utils.chat_formatting import *
from redbot.core.utils import mod
from redbot.core.utils.predicates import MessagePredicate
from redbot.core import Config, checks, commands, modlog
from redbot.core.bot import Red
from redbot.core.data_manager import cog_data_path
import discord

from .utils import *
import asyncio
from typing import Union
import os
import random

from datetime import datetime
import time

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

MIN_MSG_LEN = 6

# 0 is guild object, 1 is invite link
PURGE_DM_MESSAGE = "**__Notice of automatic inactivity removal__**\n\nYou have been kicked from {0.name} for lack of activity in the server; this is merely routine, and you are welcome to join back here: {1}"

# 0 is guild object, number of messages is 1, 2 is anything extra to add.
PURGE_DM_WARN_MESSAGE = "**__WARNING! You may be kicked from {0.name} soon!__**\n\nDue to your inactivity, it may happen that you get kicked. If you don't want that, then we recommend you chat with people in text channels! The minimum number of messages you need is **{1}** to be marked as active. {2}\n\nHowever, you can't just spam letters or messages! We aren't doing this to be rude but simply to try and keep active people within our community. We hope you understand and apologize for any inconvenience."


def parse_timedelta(argument: str) -> Optional[timedelta]:
    matches = TIME_RE.match(argument)
    if matches:
        params = {k: int(v) for k, v in matches.groupdict().items() if v}
        if params:
            return timedelta(**params)
    return None


class MoreAdmin(commands.Cog):
    """
    Provides some more Admin commands to Red.
    """

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=9468294573, force_registration=True)

        default_guild = {
            "user_count_channel": None,
            "sus_user_channel": None,
            "sus_user_threshold": None,
            "ignore_bot_commands": False,
            "last_msg_num": 5,
            "prefixes": [],
        }

        default_role = {"addable": []}  # role ids who can add this role

        # maps message_time -> dict("channel_id":int, "message_id": int)
        default_member = {"last_msgs": {}}

        self.config.register_role(**default_role)
        self.config.register_member(**default_member)
        self.config.register_guild(**default_guild)

        # initalize prefixes and add user count updater task
        asyncio.create_task(self.initialize())
        self.user_task = asyncio.create_task(self.user_count_updater())

    async def initialize(self):
        await self.register_casetypes()
        for guild in self.bot.guilds:
            async with self.config.guild(guild).prefixes() as prefixes:
                if not prefixes:
                    curr = await self.bot.get_valid_prefixes()
                    prefixes.extend(curr)

    def cog_unload(self):
        self.user_task.cancel()

    @staticmethod
    async def register_casetypes():
        # register mod case
        purge_case = {
            "name": "Purge",
            "default_setting": True,
            "image": "\N{WOMANS BOOTS}",
            "case_str": "Purge",
        }
        try:
            await modlog.register_casetype(**purge_case)
        except RuntimeError:
            pass

    async def check_prefix(self, message: discord.Message):
        # check if prefixes appear in message
        prefixes = await self.config.guild(message.guild).prefixes()
        for prefix in prefixes:
            if prefix == message.content[: len(prefix)]:
                return False

        return True

    async def add_last_msg(self, message):
        if not isinstance(message.author, discord.Member):
            return

        # length/attachment check
        if not message.attachments and len(message.content) < MIN_MSG_LEN:
            return

        # adds last message for user
        max_msg = await self.config.guild(message.guild).last_msg_num()
        async with self.config.member(message.author).last_msgs() as last_msgs:
            if len(last_msgs.keys()) < max_msg:
                last_msgs[message.created_at.timestamp()] = {"channel_id": message.channel.id, "message_id": message.id}
            else:
                keys = sorted([float(k) for k in last_msgs.keys()])
                # if oldest message saved is newer than the message to add, dont add it
                if keys:  # need to make sure if user has last message
                    if keys[0] > message.created_at.timestamp():
                        return
                    del last_msgs[str(keys[0])]  # remove oldest entry

                # append new entry
                last_msgs[message.created_at.timestamp()] = {"channel_id": message.channel.id, "message_id": message.id}

    async def last_message_sync(self, ctx: commands.Context):
        """
        Syncs last message of EVERY user in a guild.
        **WARNING VERY SLOW AND COSTLY OPERATION!**
        """
        text_channels = [channel for channel in ctx.guild.channels if isinstance(channel, discord.TextChannel)]
        ignore = await self.config.guild(ctx.guild).ignore_bot_commands()
        num_text_c = len(text_channels)
        progress_message = await ctx.send(f"Processed 0/{num_text_c} channels...")
        start_time = time.time()
        for i, channel in enumerate(text_channels):
            async for message in channel.history(limit=None):
                to_add = True
                if ignore:
                    to_add = await self.check_prefix(message)

                if to_add:
                    await self.add_last_msg(message)

            await progress_message.edit(content=f"Processed {i+1}/{num_text_c} channels...")

        await progress_message.edit(
            content=f"Done. Processed {num_text_c} channels in {parse_seconds(time.time() - start_time)}."
        )

    async def user_count_updater(self):
        await self.bot.wait_until_ready()
        SERVER_STATS_MSG = "USERS: {}/{}"
        SLEEP_TIME = 300
        while True:
            for guild in self.bot.guilds:
                channel = await self.config.guild(guild).user_count_channel()
                if channel:
                    channel = guild.get_channel(channel)
                    online = len([m.status for m in guild.members if m.status != discord.Status.offline])
                    title = SERVER_STATS_MSG.format(online, len(guild.members))
                    await channel.edit(name=title)

            await asyncio.sleep(SLEEP_TIME)

    async def get_purges(self, ctx, role, threshold, check_messages=True):
        # returns users that can be purged given the settings.
        guild = ctx.guild
        to_purge = []

        for member in guild.members:
            if member.id == self.bot.user.id:  # don't want to purge the bot.
                continue
            if role in member.roles:
                if check_messages:
                    last_msgs = await self.config.member(member).last_msgs()
                    keys = sorted([float(k) for k in last_msgs.keys()])
                    if not keys:
                        to_purge.append(member)
                    # if their oldest message is longer than the threshold, then must be purged.
                    # so a user where 3/5 messages meet the threshold still gets purged.
                    elif (ctx.message.created_at - datetime.fromtimestamp(keys[0])) > threshold:
                        to_purge.append(member)
                else:
                    if (ctx.message.created_at - member.joined_at) > threshold:
                        to_purge.append(member)

        return to_purge

    @commands.group(name="adminset")
    @commands.guild_only()
    @checks.admin_or_permissions(administrator=True)
    async def adminset(self, ctx):
        """
        Manage more admin settings.
        """
        pass

    @adminset.command(name="user-count")
    async def adminset_user_count(self, ctx, *, channel: Union[discord.TextChannel, discord.VoiceChannel] = None):
        """
        Set channel to display guild user count.
        Run with no channel to disable.
        """
        if not channel:
            pred = MessagePredicate.yes_or_no(ctx)
            curr_channel = await self.config.guild(ctx.guild).user_count_channel()
            if not curr_channel:
                await ctx.send("No channel defined.")
                return

            await ctx.send(
                f"Would you like to clear the current channel? ({ctx.guild.get_channel(curr_channel).mention})"
            )
            try:
                await self.bot.wait_for("message", check=pred, timeout=30)
            except asyncio.TimeoutError:
                await ctx.send("Took too long.")
                return
            if pred.result:
                await self.config.guild(ctx.guild).user_count_channel.set(None)
                await ctx.tick()
                return
            else:
                await ctx.send("Nothing changed.")
                return

        await self.config.guild(ctx.guild).user_count_channel.set(channel.id)
        await ctx.tick()

    @adminset.command(name="sus-channel")
    async def adminset_sus_user(self, ctx, *, channel: discord.TextChannel = None):
        """
        Set channel to log new users.
        Run with no channel to disable.
        Make sure to set threshold age for new account using [p]adminset sus-threshold
        """
        if not channel:
            pred = MessagePredicate.yes_or_no(ctx)
            curr_channel = await self.config.guild(ctx.guild).sus_user_channel()
            if not curr_channel:
                await ctx.send("No channel defined.")
                return

            await ctx.send(
                f"Would you like to clear the current channel? ({ctx.guild.get_channel(curr_channel).mention})"
            )
            try:
                await self.bot.wait_for("message", check=pred, timeout=30)
            except asyncio.TimeoutError:
                await ctx.send("Took too long.")
                return
            if pred.result:
                await self.config.guild(ctx.guild).sus_user_channel.set(None)
                await ctx.tick()
                return
            else:
                await ctx.send("Nothing changed.")
                return

        await self.config.guild(ctx.guild).sus_user_channel.set(channel.id)
        await ctx.tick()

    @adminset.command(name="sus-threshold")
    async def adminset_sus_threshold(self, ctx, *, threshold: str):
        """
        Set threshold for classifying users as new.

        Threshold should look like:
           5 minutes
           1 minute 30 seconds
           1 hour
           2 days
           30 days
           5h30m
           (etc)
        """
        threshold = parse_timedelta(threshold)
        if not threshold:
            await ctx.send("Invalid threshold!")
            return

        await self.config.guild(ctx.guild).sus_user_threshold.set(int(threshold.total_seconds()))
        await ctx.tick()

    @adminset.command(name="addable")
    async def adminset_addable(self, ctx, role: discord.Role, *, role_list: str = None):
        """
        Set roles that can add this role to others.

        Role list should be a list of one or more **role names or ids** seperated by commas.
        Roles in role list will be removed if already in the role list, or added if they are not.

        Role names are case sensitive!

        Don't pass a role list to see the current roles
        """
        if not role_list:
            curr = await self.config.role(role).addable()
            if not curr:
                await ctx.send("No roles defined.")
            else:
                curr = [ctx.guild.get_role(role_id) for role_id in curr]
                not_found = len([r for r in curr if r is None])
                curr = [r.name for r in curr if curr is not None]
                if not_found:
                    await ctx.send(
                        f"{not_found} roles weren't found, please run {ctx.prefix}costset clear to remove these roles.\nAddable Roles: {humanize_list(curr)}"
                    )
                else:
                    await ctx.send(f"Addable Roles: {humanize_list(curr)}")
            return

        guild = ctx.guild
        role_list = role_list.strip().split(",")
        role_list = [r.strip() for r in role_list]
        not_found = set()
        found = set()
        added = set()
        removed = set()
        for role_name in role_list:
            role = role_from_string(guild, role_name)

            if role is None:
                not_found.add(role_name)
                continue

            found.add(role)

        if not_found:
            await ctx.send(
                warning("These roles weren't found, please try again: {}".format(humanize_list(list(not_found))))
            )
            return

        async with self.config.role(role).addable() as addable:
            for role in found:
                if role.id in addable:
                    addable.remove(role.id)
                    removed.add(role.name)
                else:
                    addable.append(role.id)
                    added.add(role.name)
        msg = ""
        if added:
            msg += "Added: {}\n".format(humanize_list(list(added)))
        if removed:
            msg += "Removed: {}".format(humanize_list(list(removed)))

        await ctx.send(msg)

    @commands.group(name="purgeset")
    @commands.guild_only()
    @checks.admin_or_permissions(administrator=True)
    async def purgeset(self, ctx):
        """
        Manage purge settings.
        """
        pass

    @purgeset.command(name="prefixes")
    async def purgeset_prefixes(self, ctx, *, prefixes: str = None):
        """
        Set prefixes for bot commands to check for when purging.

        Seperate prefixes with spaces.
        """
        if not prefixes:
            prefixes = await self.config.guild(ctx.guild).prefixes()
            curr = [f"`{p}`" for p in prefixes]
            await ctx.send("Current Prefixes: " + humanize_list(curr))
            return

        prefixes = [p for p in prefixes.split(" ")]
        await self.config.guild(ctx.guild).prefixes.set(prefixes)
        prefixes = [f"`{p}`" for p in prefixes]
        await ctx.send("Prefixes set to: " + humanize_list(prefixes))

    @purgeset.command(name="bot")
    async def purgeset_ignore_bot(self, ctx, *, toggle: bool):
        """
        Set whether to ignore bot commands for last messages.
        """
        await self.config.guild(ctx.guild).ignore_bot_commands.set(toggle)
        await ctx.tick()

    @purgeset.command(name="numlast")
    async def purgeset_last_message_number(self, ctx, count: int):
        """
        Set the number of messages to track.

        This number of messages must be within threshold when purging in order
        for a member to **not** be purged.
        """
        if count < 0 or count > 500:
            await ctx.send("Invalid message count.")
            return

        await self.config.guild(ctx.guild).last_msg_num.set(count)
        await ctx.tick()

    @purgeset.command(name="sync")
    async def purgeset_sync(self, ctx):
        """
        Syncs last messages for all users in the guild.
        **WARNING, VERY SLOW OPERATION!**
        """
        await ctx.send("This will take a long time! Are you sure you want to continue?")
        pred = MessagePredicate.yes_or_no(ctx)
        try:
            await self.bot.wait_for("message", check=pred, timeout=30)
        except asyncio.TimeoutError:
            await ctx.send("Took too long.")
            return

        if pred.result:
            await ctx.send("Better grab some coffee then.")
            await self.last_message_sync(ctx)

    @commands.command(name="giverole")
    @checks.mod_or_permissions(manage_roles=True)
    @checks.bot_has_permissions(manage_roles=True)
    async def admin_addrole(self, ctx, user: discord.Member, *, role: discord.Role):
        """
        Add a role to a user.
        **Must be setup before hand with `[p]adminset`**
        Admins will bypass role checks.
        """
        author = ctx.author
        reason = f"Added by {author} (id: {author.id})"
        if mod.is_admin_or_superior(self.bot, author):
            try:
                await user.add_roles(role, reason=reason)
            except:
                await ctx.send("Adding role failed!")
            return

        roles = {r.id for r in author.roles if r.name != "@everyone"}
        addable = await self.config.role(role).addable()
        roles &= set(addable)

        if roles:
            await user.add_roles(role, reason=reason)
        else:
            await ctx.send("You do not have the proper roles to add this role.")

    @commands.command(name="remrole")
    @checks.mod()
    @checks.bot_has_permissions(manage_roles=True)
    async def admin_remrole(self, ctx, user: discord.Member, *, role: discord.Role):
        """
        Removes a role to a user.
        **Must be setup before hand with `[p]adminset`**
        Admins will bypass role checks.
        """
        author = ctx.author
        reason = f"Removed by {author} (id: {author.id})"
        if mod.is_admin_or_superior(self.bot, author):
            try:
                await user.remove_roles(role, reason=reason)
            except:
                await ctx.send("Removing role failed!")
            return

        roles = {r.id for r in author.roles if r.name != "@everyone"}
        addable = await self.config.role(role).addable()
        roles &= set(addable)

        if roles:
            await user.remove_roles(role, reason=reason)
        else:
            await ctx.send("You do not have the proper roles to remove this role.")

    @commands.command(name="pingable")
    @checks.mod()
    @checks.bot_has_permissions(manage_roles=True)
    async def pingable(self, ctx, seconds: int, *, role: discord.Role):
        """
        Sets a role to be pingable for <seconds> amount of seconds.

        A time of 0 will just toggle the pingable status.

        Role should be a role name (case sensitive) or role ID.
        """
        guild = ctx.guild

        if seconds < 0:
            await ctx.send("Please enter a time greater than or equal to 0.")
            return

        if seconds == 0:
            current_status = True is not role.mentionable
            await ctx.send("Setting pingable status to {} now.".format("ON" if current_status else "OFF"))
            await role.edit(mentionable=current_status)
        else:
            await ctx.send("Setting {} to be pingable for {} seconds.".format(role.name, seconds))
            await role.edit(mentionable=True)
            await asyncio.sleep(seconds)
            await role.edit(mentionable=False)

    @commands.command(name="lastmsg")
    @checks.mod()
    async def last_msg(self, ctx, *, user: discord.Member):
        """
        Gets stored last messages for a user
        """
        last_msgs = await self.config.member(user).last_msgs()
        if not last_msgs:
            await ctx.send(
                "No last messages for this user. Make sure you have synced last messages for all users in the guild."
            )
            return
        keys = sorted([float(k) for k in last_msgs.keys()])
        msg = ""
        for i, k in enumerate(keys):
            channel = last_msgs[str(k)]["channel_id"]
            message = last_msgs[str(k)]["message_id"]

            channel = ctx.guild.get_channel(channel)
            if not channel:
                msg += f"{i+1}. Time: {datetime.fromtimestamp(k)}, channel not found\n"
                continue
            message = await channel.fetch_message(message)
            if not message:
                msg += f"{i+1}. Time: {datetime.fromtimestamp(k)}, message not found\n"
                continue

            msg += f"{i+1}. Time: {datetime.fromtimestamp(k)}, {message.jump_url}\n"

        pages = pagify(msg)
        for page in pages:
            await ctx.send(page)

    @commands.group(name="purge", invoke_without_command=True)
    @checks.admin_or_permissions(administrator=True)
    @checks.bot_has_permissions(kick_members=True)
    async def purge(
        self, ctx, role: discord.Role, check_messages: bool = True, *, threshold: str = None,
    ):
        """
        Purge inactive users with role.

        **If the role has spaces, you need to use quotes**

        If check_messages is yes/true/1 then purging is dictated by the user's last message.
        If check_messages is no/false/0 then purging is dictated by the user's join date.

        **Make sure to set purge settings with [p]purgeset**

        Threshold should be an interval.

        Intervals look like:
           5 minutes
           1 minute 30 seconds
           1 hour
           2 days
           30 days
           5h30m
           (etc)
        """
        if ctx.invoked_subcommand:
            return

        threshold = parse_timedelta(threshold)
        if not threshold:
            await ctx.send("Invalid threshold!")
            return

        guild = ctx.guild
        start_time = time.time()
        to_purge = await self.get_purges(ctx, role, threshold, check_messages=check_messages)

        if not to_purge:
            await ctx.send("No one to purge.")
            return

        num = len(to_purge)
        await ctx.send(f"This will purge {num} users, are you sure you want to continue?")

        pred = MessagePredicate.yes_or_no(ctx)
        try:
            await self.bot.wait_for("message", check=pred, timeout=30)
        except asyncio.TimeoutError:
            await ctx.send("Took too long.")
            return
        if pred.result:
            await ctx.send("Are you really sure? This cannot be stopped once it starts.")
            try:
                await self.bot.wait_for("message", check=pred, timeout=30)
            except asyncio.TimeoutError:
                await ctx.send("Took too long.")
                return

            if not pred.result:
                await ctx.send("Cancelled")
                return

            await ctx.send("Okay, here we go.")
            progress_message = await ctx.send(f"Processed 0/{num} users...")
            invite = await guild.invites()

            if not invite:
                invite = (await ctx.channel.create_invite()).url
            else:
                invite = invite[0].url
            purge_msg = PURGE_DM_MESSAGE.format(guild, invite)
            _threshold = parse_seconds(threshold.total_seconds())

            for i, user in enumerate(to_purge):
                try:
                    await user.send(purge_msg)
                except:
                    pass

                if check_messages:
                    last_msgs = await self.config.member(user).last_msgs()
                    keys = sorted([float(k) for k in last_msgs.keys()])
                    if keys:
                        _purge = datetime.fromtimestamp(keys[0])
                    else:
                        _purge = ctx.message.created_at
                    msg = "Last Message Time"
                else:
                    _purge = user.joined_at
                    msg = "Account Age"

                _purge = ctx.message.created_at - _purge
                _purge = parse_seconds(_purge.total_seconds())
                reason = f"Purged by moreadmins cog. {msg}: {_purge}, Threshold: {_threshold}"

                await user.kick(reason=reason)
                # await modlog.create_case(
                #    self.bot, guild, ctx.message.created_at, "Purge", user, moderator=ctx.author, reason=reason
                # )
                if i % 10 == 0:
                    await progress_message.edit(content=f"Processed {i+1}/{num} users...")

            await progress_message.edit(
                content=f"Purged {num} users successfully. Took {parse_seconds(time.time() - start_time)}."
            )

        else:
            await ctx.send("Cancelled.")

    @purge.command(name="audit")
    async def purge_audit(self, ctx, role: discord.Role, check_messages: bool = True, *, threshold: str = None):
        """
        Audits a potential purge.

        Gives number of users, the purge settings, and 10 potential purge users for you to check.
        """
        threshold = parse_timedelta(threshold)
        if not threshold:
            await ctx.send("Invalid threshold!")
            return

        to_purge = await self.get_purges(ctx, role, threshold, check_messages=check_messages)

        if not to_purge:
            await ctx.send("No one can be purged with those settings.")
            return

        purge_settings = await self.config.guild(ctx.guild).all()
        msg = "**__Settings:__**\nIgnore bot commands: {}\nNumber of messages to check: {}\nPrefixes: {}\n**Number of users who can be purged: {}**\n\nHere are some users who can be purged:\n"
        msg = msg.format(
            purge_settings["ignore_bot_commands"],
            purge_settings["last_msg_num"],
            humanize_list([f"`{p}`" for p in purge_settings["prefixes"]]),
            len(to_purge),
        )

        try:
            sample = random.sample(to_purge, 10)
        except ValueError:
            sample = to_purge

        for m in sample:
            msg += f"{m.mention}\n"

        await ctx.send(msg)

    @purge.command(name="dm")
    async def purge_dm(self, ctx, role: discord.Role, check_messages: bool = True, *, threshold: str = None):
        """
        DMs users warning them of their potential to be purged.
        """
        threshold = parse_timedelta(threshold)
        if not threshold:
            await ctx.send("Invalid threshold!")
            return

        start_time = time.time()
        to_purge = await self.get_purges(ctx, role, threshold, check_messages=check_messages)

        if not to_purge:
            await ctx.send("No one can be purged with those settings.")
            return

        num = len(to_purge)
        plural = "s" if num > 1 else ""
        await ctx.send(f"This will send DMs to {num} user{plural}, are you sure you want to continue?")
        pred = MessagePredicate.yes_or_no(ctx)
        try:
            await self.bot.wait_for("message", check=pred, timeout=30)
        except asyncio.TimeoutError:
            await ctx.send("Took too long.")
            return

        if not pred.result:
            await ctx.send("Cancelled.")
            return

        await ctx.send("Okay, here we go.")
        progress_message = await ctx.send(f"Processed 0/{num} users...")

        number = await self.config.guild(ctx.guild).last_msg_num()
        ignore = await self.config.guild(ctx.guild).ignore_bot_commands()
        failed = 0
        if ignore:
            msg = PURGE_DM_WARN_MESSAGE.format(ctx.guild, number, "**Bot commands do not count!**")
        else:
            msg = PURGE_DM_WARN_MESSAGE.format(ctx.guild, number, "")

        for i, member in enumerate(to_purge):
            try:
                await member.send(msg)
            except:
                failed += 1
                pass
            if i % 10 == 0:
                await progress_message.edit(content=f"Processed {i+1}/{num} users...")

        extra = f"\n\nFailed to send DMs to {failed} users" if failed > 0 else ""
        await progress_message.edit(
            content=f"Done. DMed {num - failed} users in {parse_seconds(time.time() - start_time)}." + extra
        )

    @commands.command(hidden=True)
    @commands.guild_only()
    async def say(self, ctx, *, content: str):
        await ctx.send(escape(content, mass_mentions=True))

    @commands.command(hidden=True)
    @commands.guild_only()
    async def selfdm(self, ctx, *, content: str):
        try:
            await ctx.author.send(content)
        except:
            await ctx.send(
                "I couldn't send you the DM, make sure to turn on messages from server members! Here is the message:"
            )
            await ctx.send(content)

    @commands.command()
    @checks.mod()
    @commands.guild_only()
    async def edit(self, ctx, channel: discord.TextChannel, message_id: int, *, msg: str):
        """
        Edit any message sent by Aurelia.
        Needs message ID of message to edit, and the channel the message is in.
        """
        try:
            message = await channel.fetch_message(message_id)
        except:
            await ctx.send("Sorry, that message could not be found.")
            return

        try:
            await message.edit(content=msg)
        except:
            await ctx.send("Could not edit message.")

    @commands.command()
    @commands.guild_only()
    @checks.admin_or_permissions(administrator=True)
    async def send(self, ctx, channel: discord.TextChannel, *, msg: str):
        """
        Sends a message to a channel from Aurelia.
        """
        try:
            await channel.send(msg)
        except:
            await ctx.send("Could not send message in that channel.")

    @commands.command()
    @commands.guild_only()
    @checks.admin_or_permissions(administrator=True)
    async def sendatt(self, ctx, channel: discord.TextChannel):
        """
        Sends an attachment to a channel from Aurelia.

        Attach content to the message.
        """
        attach = ctx.message.attachments
        if len(attach) < 1:
            await ctx.send("Please add an attachment.")
            return

        filepaths = []
        if attach:
            for a in attach:
                filepaths.append(cog_data_path(cog_instance=self) / f"{ctx.author.id}_{a.filename}")
                a.save(filepaths[-1])
        else:
            await ctx.send("You must provide a Discord attachment.")
            return

        files = [discord.File(file) for file in filepaths]

        await channel.send(files=files)

        for file in filepaths:
            os.remove(file)

    @commands.command()
    @commands.guild_only()
    @checks.mod()
    async def get(self, ctx, channel: discord.TextChannel, message_id: int):
        """
        Gets a message with it's formatting from Aurelia.
        """
        try:
            message = await channel.fetch_message(message_id)
        except:
            await ctx.send("Sorry, that message could not be found.")
            return

        if message.content == "":
            await ctx.send("(no message content)")
        else:
            await ctx.send("{}".format(escape(message.content, formatting=True, mass_mentions=True)))

    @commands.command()
    @commands.guild_only()
    @checks.admin_or_permissions(administrator=True)
    async def listrole(self, ctx, *, role_list: str = None):
        """
        Lists all memebers with specified roles.
        Leave list empty to list everyone with no roles.

        Role list should be a list of one or more **role names or ids** seperated by commas.

        Role names are case sensitive!
        """
        guild = ctx.guild
        results = []
        if role_list is None:
            for member in guild.members:
                if len(member.roles) == 1:
                    results.append(member)
        else:
            role_list = role_list.strip().split(",")
            role_list = [r.strip() for r in role_list]
            parsed_roles = [role_from_string(guild, role) for role in role_list]

            if None in parsed_roles:
                await ctx.send("Some of those role(s) were not found, please try again.")
                return

            num_parsed_roles = len(parsed_roles)
            for member in guild.members:
                found = 0
                for role in parsed_roles:
                    if role in member.roles:
                        found += 1

                if num_parsed_roles == found:
                    results.append(member)

        if not results:
            await ctx.send("No members found with specified role(s).")
            return

        results = [m.mention for m in results]
        msg = " ".join(results)
        msg_pages = pagify(msg)

        for page in msg_pages:
            await ctx.send(page)

        num = len(results)
        plural = "s" if num > 1 else ""
        await ctx.send(f"That is {num} member{plural} with these role(s)")

    ### Listeners ###

    @commands.Cog.listener()
    async def on_member_join(self, member):
        sus_threshold = await self.config.guild(member.guild).sus_user_threshold()
        if not sus_threshold:
            return
        channel = await self.config.guild(member.guild).sus_user_channel()
        channel = member.guild.get_channel(channel)
        if not channel:
            return

        age = (datetime.utcnow() - member.created_at).total_seconds()

        if age < sus_threshold:
            data = discord.Embed(title="NEW ACCOUNT DETECTED", colour=member.colour)
            data.add_field(name="Account Age", value=parse_seconds(age))
            data.add_field(name="Threshold", value=parse_seconds(sus_threshold))
            data.set_footer(text=f"User ID:{member.id}")

            name = str(member)
            name = " ~ ".join((name, member.nick)) if member.nick else name

            if member.avatar_url:
                data.set_author(name=name, url=member.avatar_url)
                data.set_thumbnail(url=member.avatar_url)
            else:
                data.set_author(name=name)

            await channel.send(embed=data)

    @commands.Cog.listener()
    async def on_message(self, message):
        # Set user's last message
        if not message.guild:
            return
        to_add = True
        ignore = await self.config.guild(message.guild).ignore_bot_commands()
        if ignore:
            to_add = await self.check_prefix(message)

        if to_add:
            await self.add_last_msg(message)
