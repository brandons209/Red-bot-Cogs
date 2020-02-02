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

PURGE_DM_MESSAGE = "**__Notice of automatic inactivity removal__**\n\nYou have been kicked from {0.name} for lack of activity in the server; this is merely routine, and you are welcome to join back here: {1}"

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
        self.config = Config.get_conf(self, identifier=213438438248, force_registration=True)

        default_guild = {
            "user_count_channel": None,
            "sus_user_channel": None,
            "sus_user_threshold": None
        }

        default_role = {
            "addable": [] # role ids who can add this role
        }
        self.config.register_role(**default_role)
        self.config.register_guild(**default_guild)
        self.loop = asyncio.get_event_loop()
        self.loop.create_task(self.initialize())
        self.user_task = self.loop.create_task(self.user_count_updater())

    async def initialize(self):
        await self.register_casetypes()

    def cog_unload(self):
        self.user_task.cancel()

    @staticmethod
    async def register_casetypes():
        # register mod case
        punish_case = {
            "name": "Purge",
            "default_setting": True,
            "image": "\N{WOMANS BOOTS}",
            "case_str": "Purge",
        }
        try:
            await modlog.register_casetype(**punish_case)
        except RuntimeError:
            pass

    @staticmethod
    async def find_last_message(guild: discord.Guild, role: discord.Role):
        """
        Finds last message of EVERY user with role in a guild.
        **WARNING VERY SLOW AND COSTLY OPERATION!**

        returns: dictionary maping user ids -> last message
        """
        last_msgs = {}
        text_channels = [channel for channel in guild.channels if isinstance(channel, discord.TextChannel)]
        for channel in text_channels:
            async for message in channel.history(limit=None):
                if isinstance(message.author, discord.Member) and role in message.author.roles:
                    if message.author.id not in last_msgs.keys():
                        last_msgs[message.author.id] = message
                    else:
                        curr_last = last_msgs[message.author.id]
                        if message.created_at > curr_last.created_at:
                            last_msgs[message.author.id] = message

        return last_msgs

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

            await ctx.send(f"Would you like to clear the current channel? ({ctx.guild.get_channel(curr_channel).mention})")
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

            await ctx.send(f"Would you like to clear the current channel? ({ctx.guild.get_channel(curr_channel).mention})")
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


    @commands.command(name="giverole")
    @checks.mod_or_permissions(manage_roles=True)
    @checks.bot_has_permissions(manage_roles=True)
    async def admin_addrole(self, ctx, role: discord.Role, *, user: discord.Member):
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
    async def admin_remrole(self, ctx, role: discord.Role, *, user: discord.Member):
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

        Role should be a role name or role ID.
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

    @commands.command(name="purge")
    @checks.admin_or_permissions(administrator=True)
    @checks.bot_has_permissions(kick_members=True)
    async def purge(self, ctx, role: discord.Role, check_messages: bool = True, *, threshold: str = None):
        """
        Purge inactive users with role.

        **__WARNING: VERY SLOW AND COSTLY OPERATION!__**
        **If the role has spaces, you need to use quotes**

        If check_messages is yes/true/1 then purging is dictated by the user's last message.
        If check_messages is no/false/0 then purging is dictated by the user's join date.

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
        threshold = parse_timedelta(threshold)
        if not threshold:
            await ctx.send("Invalid threshold!")
            return

        guild = ctx.guild
        to_purge = []
        errored = []
        start_time = time.time()
        if check_messages:
            last_msgs = await self.find_last_message(guild, role)

        for member in guild.members:
            if role in member.roles:
                if check_messages:
                    last_msg = last_msgs.get(member.id, -1)
                    if last_msg == -1: # shouldn't happen, but just a sanity check
                        errored.append(member)
                    elif (ctx.message.created_at - last_msg.created_at) > threshold:
                        to_purge.append(member)
                else:
                    if (ctx.message.created_at - member.joined_at) > threshold:
                        to_purge.append(member)

        if errored:
            errored = [m.mention for m in errored]
            await ctx.send(f"Some user's last message could not be found. Please check them manually:\n\n{humanize_list(errored)}")

        if not to_purge:
            await ctx.send("No one to purge.")
            return

        await ctx.send(f"This will purge {len(to_purge)} users, are you sure you want to continue?")

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
            invite = await guild.invites()
            invite = invite[0].url
            purge_msg = PURGE_DM_MESSAGE.format(guild, invite)
            for user in to_purge:
                try:
                    await user.send(purge_msg)
                except:
                    pass

                if check_messages:
                    _purge = last_msgs[user.id].created_at
                    msg = "Last Message Time"
                else:
                    _purge = user.joined_at
                    msg = "Account Age"

                _purge = (ctx.message.created_at - _purge)
                _purge = parse_seconds(_purge.total_seconds())
                threshold = parse_seconds(threshold.total_seconds())
                reason = f"Purged by moreadmins cog. {msg}: {_purge}, Threshold: {threshold}"

                await user.kick(reason=reason)
                await modlog.create_case(self.bot, guild, ctx.message.created_at, "Purge", user, moderator=ctx.author, reason=reason)

            await ctx.send(f"Purge completed. Took {parse_seconds(time.time() - start_time)}.")

        else:
            await ctx.send("Cancelled.")

    @commands.command()
    @commands.guild_only()
    async def say(self, ctx, *, content: str):
        await ctx.send(escape(content, mass_mentions=True))

    @commands.command()
    @commands.guild_only()
    async def selfdm(self, ctx, *, content: str):
        try:
            await ctx.author.send(content)
        except:
            await ctx.send("I couldn't send you the DM, make sure to turn on messages from server members! Here is the message:")
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
            await ctx.send(msg)

        num = len(results)
        plural = "s" if num > 1 else ""
        await ctx.send(f"That is {num} member{plural} with these role(s)")

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

    ### DATA LOADING FROM V2, WILL REMOVE LATER ###
    @commands.command(name="loadecon")
    @checks.is_owner()
    async def load_econ(self, ctx, *, path: str):
        import json
        from redbot.core import bank
        with open(path, "r") as f:
            settings = json.load(f)

            for guild_id, member_data in settings.items():
                guild = self.bot.get_guild(int(guild_id))
                for mid, mdata in member_data.items():
                    user = guild.get_member(int(mid))
                    try:
                        await bank.deposit_credits(user, mdata["balance"])
                    except Exception as e:
                        print(e)

    @commands.command(name="loaduserstats")
    @checks.is_owner()
    async def load_stats(self, ctx, *, path: str):
        import json
        act_log = self.bot.get_cog("ActivityLogger")
        with open(path, "r") as f:
            settings = json.load(f)

        for guild in self.bot.guilds:
            for member in guild.members:
                data = settings[str(member.id)]
                async with act_log.config.member(member).stats() as stats:
                    stats["total_msg"] += data["total_msg"]
                    stats["bot_cmd"] += data["bot_cmd"]
                    stats["avg_len"] += data["avg_len"]
                    stats["vc_time_sec"] += data["vc_time_sec"]
