# redbot/discord
from redbot.core.utils.chat_formatting import *
from redbot.core import Config, checks, commands, modlog, bank
from redbot.core.data_manager import cog_data_path
from redbot.core.utils.mod import is_mod_or_superior
import discord

from .utils import *
from datetime import datetime
from dateutil.relativedelta import relativedelta
from dateutil.tz import tzlocal
import time
import os
import asyncio
import glob
import io
import functools

from typing import Literal

# plotting
from bisect import bisect_left
import matplotlib.pyplot as plt
from matplotlib.dates import AutoDateLocator, AutoDateFormatter
import pandas as pd

__version__ = "3.1.0"

TIMESTAMP_FORMAT = "%Y-%m-%d %X"  # YYYY-MM-DD HH:MM:SS

# 0 is Message object
AUTHOR_TEMPLATE = "@{0.author.name}#{0.author.discriminator}(id:{0.author.id})"
MESSAGE_TEMPLATE = AUTHOR_TEMPLATE + ": {0.clean_content}"

# 0 is Message object, 1 is the message replied too
REPLY_TEMPLATE = (
    AUTHOR_TEMPLATE
    + " replied to @{1.author.name}#{1.author.discriminator}(id:{1.author.id}): {1.clean_content} [with]: {0.clean_content}"
)

# 0 is Message object, 1 is attachment URL
ATTACHMENT_TEMPLATE = AUTHOR_TEMPLATE + ": {0.clean_content} (attachment url(s): {1})"

# 0 is Message object, 1 is sticker URL
STICKER_TEMPLATE = AUTHOR_TEMPLATE + ": {0.clean_content} (sticker url(s): {1})"

# 0 is Message object, 1 is attachment path
DOWNLOAD_TEMPLATE = AUTHOR_TEMPLATE + ": {0.clean_content} (attachment(s) saved to {1})"

# 0 is before, 1 is after, 2 is formatted timestamp
EDIT_TEMPLATE = AUTHOR_TEMPLATE + " edited message from {2} ({0.clean_content}) to read: {1.clean_content}"

# 0 is deleted message, 1 is formatted timestamp
DELETE_TEMPLATE = AUTHOR_TEMPLATE + " deleted message from {1} ({0.clean_content})"

# 0 is member who deleted the message, 1 is message, 2 is the user who authored the message
# 3 is formatted timestamp
DELETE_AUDIT_TEMPLATE = "@{0.name}#{0.discriminator}(id:{0.id}) deleted message from {3} @{2.name}#{2.discriminator}(id:{2.id}): ({1.clean_content})"

MAX_LINES = 50000


class ActivityLogger(commands.Cog):
    """Log activity seen by bot"""

    def __init__(self, bot):
        super().__init__()
        global PATH
        PATH = cog_data_path(cog_instance=self)

        self.bot = bot
        self.config = Config.get_conf(self, identifier=9584736583, force_registration=True)
        default_global = {
            "attrs": {
                "attachments": False,
                "default": False,
                "direct": False,
                "everything": False,
                "rotation": "m",
                "check_audit": True,
            }
        }
        self.default_guild = {"all_s": False, "voice": False, "events": False, "prefixes": []}
        self.default_channel = {"enabled": False}
        default_user = {"past_names": []}
        default_member = {
            "stats": {"total_msg": 0, "bot_cmd": 0, "avg_len": 0.0, "vc_time_sec": 0.0, "last_vc_time": None}
        }
        self.config.register_global(**default_global)
        self.config.register_guild(**self.default_guild)
        self.config.register_channel(**self.default_channel)
        self.config.register_user(**default_user)
        self.config.register_member(**default_member)

        self.handles = {}
        self.lock = False
        self.cache = {}

        # remove userinfo since we are replacing it
        self.badge_emojis = {
            "staff": 848556248832016384,
            "early_supporter": 706198530837970998,
            "hypesquad_balance": 706198531538550886,
            "hypesquad_bravery": 706198532998299779,
            "hypesquad_brilliance": 706198535846101092,
            "hypesquad": 706198537049866261,
            "verified_bot_developer": 706198727953612901,
            "bug_hunter": 848556247632052225,
            "bug_hunter_level_2": 706199712402898985,
            "partner": 848556249192202247,
            "verified_bot": 848561838974697532,
            "verified_bot2": 848561839260434482,
        }
        self.bot.remove_command("userinfo")
        self.load_task = asyncio.create_task(self.initialize())
        self.loop = asyncio.get_event_loop()

    def cog_unload(self):
        self.lock = True

        for h in self.handles.values():
            h.close()

        if self.load_task:
            self.load_task.cancel()

    async def initialize(self):
        await self.bot.wait_until_ready()

        guild_data = await self.config.all_guilds()
        channel_data = await self.config.all_channels()
        self.cache = await self.config.attrs()

        # key ids for these should be ints
        for guild_id, data in guild_data.items():
            self.cache[guild_id] = data

        for channel_id, data in channel_data.items():
            self.cache[channel_id] = data

        if not guild_data:
            guilds = self.bot.guilds
            for guild in guilds:
                self.cache[guild.id] = self.default_guild.copy()

        guilds = self.bot.guilds
        for guild in guilds:
            for channel in guild.channels:
                if not channel.id in self.cache.keys():
                    self.cache[channel.id] = self.default_channel.copy()

        for guild in self.bot.guilds:
            async with self.config.guild(guild).prefixes() as prefixes:
                if not prefixes:
                    curr = await self.bot.get_valid_prefixes()
                    prefixes.extend(curr)
                    self.cache[guild.id]["prefixes"] = curr

    @commands.command(aliases=["uinfo"])
    @commands.guild_only()
    @commands.cooldown(rate=1, per=5, type=commands.BucketType.user)
    async def userinfo(self, ctx, *, user: discord.Member = None):
        """
        Show information about a user.
        """
        author = ctx.author
        guild = ctx.guild
        is_mod = await is_mod_or_superior(self.bot, author)

        if not user or not is_mod:
            user = author

        async with ctx.typing():
            if is_mod:
                roles = [x for x in user.roles if x.name != "@everyone"]
            else:
                roles = [x.name for x in sorted(user.roles, reverse=True) if x.name != "@everyone"]

            joined_at = user.joined_at
            since_created = (ctx.message.created_at - user.created_at).days
            if joined_at is not None:
                since_joined = (ctx.message.created_at - joined_at).days
                user_joined = f"<t:{int(joined_at.astimezone(tzlocal()).timestamp())}>"
            else:
                since_joined = "?"
                user_joined = "Unknown"

            user_created = f"<t:{int(user.created_at.astimezone(tzlocal()).timestamp())}>"
            member_number = sorted(guild.members, key=lambda m: m.joined_at or ctx.message.created_at).index(user) + 1

            created_on = "{}\n({} days ago)".format(user_created, since_created)
            joined_on = "{}\n({} days ago)".format(user_joined, since_joined)

            if user.is_on_mobile():
                statusemoji = "\N{MOBILE PHONE}"
            elif any(a.type is discord.ActivityType.streaming for a in user.activities):
                statusemoji = "\N{LARGE PURPLE CIRCLE}"
            elif user.status.name == "online":
                statusemoji = "\N{LARGE GREEN CIRCLE}"
            elif user.status.name == "offline":
                statusemoji = "\N{MEDIUM WHITE CIRCLE}"
            elif user.status.name == "dnd":
                statusemoji = "\N{LARGE RED CIRCLE}"
            elif user.status.name == "idle":
                statusemoji = "\N{LARGE ORANGE CIRCLE}"
            else:
                statusemoji = "\N{MEDIUM BLACK CIRCLE}\N{VARIATION SELECTOR-16}"

            if user.activity is None:  # Default status
                activity = "No Status"
            elif user.activity.type == discord.ActivityType.playing:
                activity = "Playing {}".format(user.activity.name)
            elif user.activity.type == discord.ActivityType.streaming:
                activity = "Streaming [{}]({})".format(user.activity.name, user.activity.url)
            elif user.activity.type == discord.ActivityType.listening:
                activity = "Listening to {}".format(user.activity.name)
            elif user.activity.type == discord.ActivityType.watching:
                activity = "Watching {}".format(user.activity.name)
            else:
                activity = "No Status"

            if roles and is_mod:
                roles = " ".join([x.mention for x in sorted(roles, reverse=True)])
            elif roles:
                roles = ", ".join(roles)
            else:
                roles = "None"

            if user.id != self.bot.user.id:
                stats, names = await self.userstats(guild, user)
                if is_mod:
                    # also add notes
                    moreadmin = self.bot.get_cog("MoreAdmin")
                    if moreadmin:
                        num_notes = len(await moreadmin.config.member(user).notes())
                        stats += f", Notes: `{num_notes}`"
            else:
                stats = "Stats are unavailable for this account."
                names = None

            title = guild.name

            data = discord.Embed(title=title, description=f"{statusemoji} {activity}", colour=user.colour)
            data.add_field(name="Joined Discord on", value=created_on)
            data.add_field(name="Joined this server on", value=joined_on)
            if roles != "None":
                roles = pagify(roles, page_length=1000, delims=[" "])
                for r in roles:
                    data.add_field(name="Roles", value=r, inline=False)

            data.add_field(name="Stats", value=stats)
            if names:
                names = pagify(names, page_length=1000)
                for name in names:
                    data.add_field(name="Also known as:", value=name, inline=False)
            data.set_footer(text="Member #{} | User ID: {}" "".format(member_number, user.id))

            name = str(user)
            name = " ~ ".join((name, user.nick)) if user.nick else name

            if user.avatar:
                avatar = user.avatar_url_as(static_format="png")
                data.set_author(name=name, url=avatar)
                data.set_thumbnail(url=avatar)
            else:
                data.set_author(name=name)

            flags = [f.name for f in user.public_flags.all()]
            badges = ""
            badge_count = 0
            if flags:
                for badge in sorted(flags):
                    if badge == "verified_bot":
                        emoji1 = self.badge_emojis["verified_bot"]
                        emoji2 = self.badge_emojis["verified_bot2"]
                        if emoji1:
                            emoji = f"{emoji1}{emoji2}"
                        else:
                            emoji = None
                    else:
                        emoji = self.badge_emojis[badge]
                    if emoji:
                        badges += f"{emoji} {badge.replace('_', ' ').title()}\n"
                    else:
                        badges += f"\N{BLACK QUESTION MARK ORNAMENT}\N{VARIATION SELECTOR-16} {badge.replace('_', ' ').title()}\n"
                    badge_count += 1
            if badges:
                data.add_field(name="Badges" if badge_count > 1 else "Badge", value=badges)
            if "Economy" in self.bot.cogs:
                balance_count = 1
                bankstat = f"**Bank**: {str(humanize_number(await bank.get_balance(user)))} {await bank.get_currency_name(ctx.guild)}\n"
                data.add_field(name="Balance", value=bankstat)

            if is_mod:
                try:
                    await ctx.send(embed=data, allowed_mentions=discord.AllowedMentions.all())
                except discord.HTTPException:
                    await ctx.send("I need the `Embed links` permission to send this")
            else:
                try:
                    await author.send(embed=data)
                except discord.HTTPException:
                    await ctx.send("Please allow messages from server members to get your info.")
                except Exception as e:
                    print(f"Error in userinfo: {e}")

    async def userstats(self, guild, user):
        """
        Get stats on a user about how active they are in the guild
        """
        stats = await self.config.member(user).stats()
        async with self.config.user(user).past_names() as past_names:
            if not past_names:
                guild_files = sorted(glob.glob(os.path.join(PATH, "usernames", "*.log")))
                names = get_all_names(guild_files, user)
            else:
                names = past_names

        num_messages = stats["total_msg"]
        num_bot_commands = stats["bot_cmd"]
        avg_len = stats["avg_len"]
        total_voice_time = stats["vc_time_sec"]
        minutes = total_voice_time // 60
        hours = (total_voice_time / 60) // 60

        cases = await modlog.get_cases_for_member(guild, self.bot, member=user)

        bans = 0
        kicks = 0
        mutes = 0
        warns = 0
        for case in cases:
            if "mute" in case.action_type.lower():
                mutes += 1
            elif "ban" in case.action_type.lower():
                bans += 1
            elif "kick" in case.action_type.lower():
                kicks += 1
            elif "warning" in case.action_type.lower():
                warns += 1

        msg = "Total Number of Messages: `{}`\n".format(num_messages)
        msg += "Number of bot commands: `{}`\n".format(num_bot_commands)
        msg += "Number of non-bot commands: `{}`\n".format(num_messages - num_bot_commands)
        try:
            msg += "Average message length: `{:.2f}` words\n".format(avg_len / (num_messages - num_bot_commands))
        except ZeroDivisionError:
            msg += "Average message length: `{:.2f}` words\n".format(0)
        msg += "Time spent in voice chat: `{:.0f}` {}.\n".format(
            minutes if minutes <= 120 else hours, "minutes" if minutes <= 120 else "hours"
        )
        msg += f"Bans: `{bans}`, Kicks: `{kicks}`, Mutes: `{mutes}`, Warnings: `{warns}`"
        if len(names) > 1:
            return msg, humanize_list(names)

        return msg, None

    @commands.command(name="graphstats")
    @checks.mod()
    @commands.guild_only()
    async def user_stats_graph(self, ctx, user: discord.Member, split: str, *, till: str):
        """
        Create a graph of a users activity over time.

        `split` is how to split the data on the graph, like per hour, per day, etc.
        Possible values are:
            "h" for hourly
            "d" for daily
            "w" for weekly
            "m" for monthly
            "y" for yearly

        `till` can be a date or interval

        **Times in graph are all in UTC**

        Dates/times look like:
            February 14 at 6pm EDT
            2019-04-13 06:43:00 PST
            01/20/18 at 21:00:43

        times default to UTC if no timezone provided

         Intervals look like:
            5 minutes
            1 minute 30 seconds
            1 hour
            2 days
            30 days
            5h30m
            (etc)
        """
        interval = parse_timedelta(till)
        date = None
        if not interval:
            try:
                date = parse_time(till).replace(tzinfo=None)
            except:
                await ctx.send("Invalid date or interval! Try again.")
                return

        split = split.lower()
        if split not in ["h", "d", "w", "m", "y"]:
            await ctx.send("Invalid split! Try again.")
            return

        guild = ctx.guild
        log_files = glob.glob(os.path.join(PATH, str(guild.id), "*.log"))
        # remove audit log entries
        log_files = [log for log in log_files if "guild" not in log]

        if interval:
            end_time = datetime.utcnow() - interval
        else:
            end_time = date

        # get messages split by channel
        messages = await self.loop.run_in_executor(
            None,
            functools.partial(
                self.log_handler,
                log_files,
                end_time,
                split_channels=True,
            ),
        )

        ### set up data dictionary
        num_messages = {}
        to_delete = []
        # make sure to include only text channels
        for ch_id in messages.keys():
            channel = guild.get_channel(ch_id)
            # channel may be deleted, but still want to include message data
            if isinstance(channel, discord.VoiceChannel):
                to_delete.append(ch_id)
                continue
            num_messages[ch_id] = 0
        # delete voice channels
        for ch_id in to_delete:
            del messages[ch_id]

        data = {"times": [], "num_messages": []}
        # add all the possible times based on the split
        # first for each one zero out now time to the minute, day, etc
        # then go through and add all possible times to get data for
        now = datetime.utcnow()
        if split == "h":
            now -= relativedelta(minute=0, second=0, microsecond=0)
            end_time -= relativedelta(minute=0, second=0, microsecond=0)
            while now >= end_time:
                data["times"].append(now)
                data["num_messages"].append(num_messages.copy())
                now = now - relativedelta(hours=1)
        elif split == "d":
            now -= relativedelta(hour=0, minute=0, second=0, microsecond=0)
            end_time -= relativedelta(hour=0, minute=0, second=0, microsecond=0)
            while now >= end_time:
                data["times"].append(now)
                data["num_messages"].append(num_messages.copy())
                now = now - relativedelta(days=1)
        elif split == "w":
            now -= relativedelta(days=now.weekday(), hour=0, minute=0, second=0, microsecond=0)
            end_time -= relativedelta(days=end_time.weekday(), hour=0, minute=0, second=0, microsecond=0)
            while now >= end_time:
                data["times"].append(now)
                data["num_messages"].append(num_messages.copy())
                now = now - relativedelta(weeks=1)
        elif split == "m":
            now -= relativedelta(day=1, hour=0, minute=0, second=0, microsecond=0)
            end_time -= relativedelta(day=1, hour=0, minute=0, second=0, microsecond=0)
            while now >= end_time:
                data["times"].append(now)
                data["num_messages"].append(num_messages.copy())
                now = now - relativedelta(months=1)
        elif split == "y":
            now -= relativedelta(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
            end_time -= relativedelta(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
            while now >= end_time:
                data["times"].append(now)
                data["num_messages"].append(num_messages.copy())
                now = now - relativedelta(years=1)

        if not data["times"]:
            await ctx.send(error("Your split is too large for the time provided, try a smaller split or longer time."))
            return

        data["times"].reverse()

        # calculate number of messages for the user for every split
        for ch_id, msgs in messages.items():
            for message in msgs:
                if str(user.id) not in message:
                    continue
                # grab time of the message
                current_time = parse_time_naive(message[:19])
                # find what time to put it in using binary search
                index = bisect_left(data["times"], current_time) - 1
                # add message to channel
                data["num_messages"][index][ch_id] += 1

        df = pd.DataFrame(data)
        # make dict of num_messages into columns for every channel
        df = pd.concat([df.drop("num_messages", axis=1), df["num_messages"].apply(pd.Series)], axis=1)
        # calculate total messages for each time.
        df["Total"] = df.drop("times", axis=1).sum(axis=1)

        # change channel ids to real names, or leave as delete channel
        names = {}
        for i, ch_id in enumerate(data["num_messages"][0].keys()):
            channel = guild.get_channel(ch_id)
            names[ch_id] = channel.name if channel else f"Deleted Channel {i+1}"
        df = df.rename(columns=names)

        # drop channels with no data (all zeros) and check if theres still data
        df = df.loc[:, (df != 0).any(axis=0)]
        if len(df.columns) <= 1:
            await ctx.send(warning("There is no messages from that user in the time period you specified."))
            return

        # make graph and send it
        fontsize = 30
        fig = plt.figure(figsize=(50, 30))
        ax = plt.axes()

        # set date formater for x axis
        xtick_locator = AutoDateLocator()
        ax.xaxis.set_major_locator(xtick_locator)
        ax.xaxis.set_major_formatter(AutoDateFormatter(xtick_locator))

        # define graph and table save paths
        save_path = str(PATH / f"plot_{ctx.message.id}.png")
        table_save_path = str(PATH / f"plot_data_{ctx.message.id}.txt")

        # plot each column
        for col_name, col_data in df.iteritems():
            if col_name == "times":
                continue
            plt.plot("times", col_name, data=df, linewidth=3, marker="o", markersize=8)

        # make graph look nice
        plt.title(f"{user} message history from {end_time} to now", fontsize=fontsize)
        plt.xlabel("dates (UTC)", fontsize=fontsize)
        plt.ylabel("messages", fontsize=fontsize)
        plt.xticks(fontsize=fontsize)
        plt.yticks(fontsize=fontsize)
        plt.grid(True)

        plt.legend(bbox_to_anchor=(1.00, 1.0), loc="upper left", prop={"size": 30})
        fig.tight_layout()

        fig.savefig(save_path, dpi=fig.dpi)
        plt.close()

        df.to_csv(table_save_path, index=False)

        with open(save_path, "rb") as f, open(table_save_path, "r") as t:
            files = (discord.File(f, filename="graph.png"), discord.File(t, filename="graph_data.csv"))
            await ctx.send(files=files)

        os.remove(save_path)
        os.remove(table_save_path)

    @staticmethod
    def log_handler(log_files: list, end_time: datetime, start: datetime = None, split_channels: bool = False):
        """
        gets messages up to a specified end time, with optional start time.

        returns a list of messages.

        if the split_channels is true, returns a dictionary of
        channel ids -> messages
        """
        if split_channels:
            messages = {}
        else:
            messages = []

        parsed_logs = []
        log_files.sort(reverse=True)

        for log in log_files:
            if split_channels:
                channel_id = int(log.split("_")[-1].strip(".log"))
                if channel_id not in messages:
                    messages[channel_id] = []
            with open(log, "r") as f:
                lines = f.readlines()

            # binary search to find where the cutoff for messages is
            index = bisect_left(lines, end_time.strftime(TIMESTAMP_FORMAT))

            lines = lines[index:]
            lines.reverse()
            if split_channels:
                messages[channel_id].extend(lines)
            else:
                messages.extend(lines)

        # reverse messages to get correct order
        if split_channels:
            for ch_id in messages.keys():
                messages[ch_id].reverse()
        else:
            messages.reverse()

        return messages

    async def log_sender(self, ctx, log_files, end_time, user=None, start=None):
        log_path = os.path.join(PATH, str(ctx.guild.id))

        await ctx.send(warning("**__Generating logs, please wait...__**"))
        # runs in descending order, with most recent log file first
        messages = await self.loop.run_in_executor(
            None,
            functools.partial(
                self.log_handler,
                log_files,
                end_time,
                start=start,
            ),
        )

        if user:
            messages = [message for message in messages if str(user.id) in message]

        message_chunks = [
            messages[i * MAX_LINES : (i + 1) * MAX_LINES] for i in range((len(messages) + MAX_LINES - 1) // MAX_LINES)
        ]

        if not message_chunks:
            await ctx.send(error("No logs found for the specified location and time period!"))
            return

        for msgs in message_chunks:
            temp_file = os.path.join(log_path, datetime.utcnow().strftime("%Y%m%d%X").replace(":", "") + ".txt")
            with open(temp_file, encoding="utf-8", mode="w") as f:
                f.writelines(msgs)

            await ctx.channel.send(file=discord.File(temp_file))
            os.remove(temp_file)

    @commands.group(aliases=["log"])
    @commands.guild_only()
    @checks.admin_or_permissions(administrator=True)
    async def logs(self, ctx):
        pass

    # log rotation independent
    @logs.command(name="from")
    async def logs_channel_interval(self, ctx, channel: discord.TextChannel, *, till: str):
        """
        Logs for an entire channel going back to a specific interval or date/time.

         Dates/times look like:
            February 14 at 6pm EDT
            2019-04-13 06:43:00 PST
            01/20/18 at 21:00:43

        times default to UTC if no timezone provided

         Intervals look like:
            5 minutes
            1 minute 30 seconds
            1 hour
            2 days
            30 days
            5h30m
            (etc)
        """
        interval = parse_timedelta(till)
        date = None
        if not interval:
            try:
                date = parse_time(till).replace(tzinfo=None)
            except:
                await ctx.send("Invalid date or interval! Try again.")
                return

        guild = ctx.guild
        log_files = glob.glob(os.path.join(PATH, str(guild.id), "*{}*.log".format(channel.id)))

        if interval:
            end_time = datetime.utcnow() - interval
        else:
            end_time = date

        await self.log_sender(ctx, log_files, end_time)

    @logs.command(name="in")
    async def logs_channel_in(self, ctx, channel: discord.TextChannel, *, date: str):
        """
        Logs for an entire channel in between the specified dates
        Seperate dates with a **__semicolon__**.

         times look like:
            February 14 at 6pm EDT
            2019-04-13 06:43:00 PST
            01/20/18 at 21:00:43

        times default to UTC if no timezone provided.
        """
        try:
            dates = date.split(";")
            dates = [dates[0].strip(), dates[1].strip()]  # only use 2 dates
            start, end = [parse_time(date).replace(tzinfo=None) for date in dates]
            # order doesnt matter, so check which date is older than the other
            # end time should be the newest date since logs are processed in reverse
            if start < end:  # start is before end date
                start, end = end, start  # swap order
        except:
            await ctx.send("Invalid dates! Try again.")
            return

        guild = ctx.guild
        log_files = glob.glob(os.path.join(PATH, str(guild.id), "*{}*.log".format(channel.id)))

        await self.log_sender(ctx, log_files, end, start=start)

    @logs.group(name="user")
    async def logs_users(self, ctx):
        """Gets messages from a user"""
        pass

    @logs_users.command(name="from")
    async def logs_users_channel_interval(self, ctx, user: discord.Member, *, till: str):
        """
        User's messages accross the guild going back to a specific interval or date/time.

         Dates/times look like:
            February 14 at 6pm EDT
            2019-04-13 06:43:00 PST
            01/20/18 at 21:00:43

        times default to UTC if no timezone provided

         Intervals look like:
            5 minutes
            1 minute 30 seconds
            1 hour
            2 days
            30 days
            5h30m
            (etc)
        """
        interval = parse_timedelta(till)
        date = None
        if not interval:
            try:
                date = parse_time(till).replace(tzinfo=None)
            except:
                await ctx.send("Invalid date or interval! Try again.")
                return

        guild = ctx.guild
        log_files = glob.glob(os.path.join(PATH, str(guild.id), "*.log"))
        log_files = [log for log in log_files if "guild" not in log]

        if interval:
            end_time = datetime.utcnow() - interval
        else:
            end_time = date

        await self.log_sender(ctx, log_files, end_time, user=user)

    @logs_users.command(name="in")
    async def logs_users_channel_in(self, ctx, user: discord.Member, *, date: str):
        """
        User's messages accross the guild in between the specified dates
        Seperate dates with a **__semicolon__**.

         times look like:
            February 14 at 6pm EDT
            2019-04-13 06:43:00 PST
            01/20/18 at 21:00:43

        times default to UTC if no timezone provided.
        """
        try:
            dates = date.split(";")
            dates = [dates[0].strip(), dates[1].strip()]  # only use 2 dates
            start, end = [parse_time(date).replace(tzinfo=None) for date in dates]
            # order doesnt matter, so check which date is older than the other
            # end time should be the newest date since logs are processed in reverse
            if start < end:  # start is before end date
                start, end = end, start  # swap order
        except:
            await ctx.send("Invalid dates! Try again.")
            return

        guild = ctx.guild
        log_files = glob.glob(os.path.join(PATH, str(guild.id), "*.log"))
        log_files = [log for log in log_files if "guild" not in log]

        await self.log_sender(ctx, log_files, end, start=start, user=user)

    @logs.group(name="audit")
    async def logs_audit(self, ctx):
        """Gets audit logs"""
        pass

    @logs_audit.command(name="from")
    async def logs_audit_from(self, ctx, *, till: str):
        """
        Audit logs for server going back a time or to a specific data.
        Gets all role and name changes, mutes, etc.
        Also gets audit actions (deleting messages, bans, etc)

        Date/times look like:
            February 14 at 6pm EDT
            2019-04-13 06:43:00 PST
            01/20/18 at 21:00:43

        times default to UTC if no timezone provided.

        Intervals look like:
            5 minutes
            1 minute 30 seconds
            1 hour
            2 days
            30 days
            5h30m
            (etc)
        """
        interval = parse_timedelta(till)
        date = None
        if not interval:
            try:
                date = parse_time(till).replace(tzinfo=None)
            except:
                await ctx.send("Invalid date or interval! Try again.")
                return

        guild = ctx.guild
        log_files = glob.glob(os.path.join(PATH, str(guild.id), "*guild*.log"))

        if interval:
            end_time = datetime.utcnow() - interval
        else:
            end_time = date

        await self.log_sender(ctx, log_files, end_time)

    @logs_audit.command(name="in")
    async def logs_audit_in(self, ctx, *, date: str):
        """
        Audit logs for server in between specified dates.
        Gets all role and name changes, mutes, etc.
        Also gets audit actions (deleting messages, bans, etc)

        Seperate dates with a **semicolon**.

        Date/times look like:
            February 14 at 6pm EDT
            2019-04-13 06:43:00 PST
            01/20/18 at 21:00:43

        times default to UTC if no timezone provided.
        """
        try:
            dates = date.split(";")
            dates = [dates[0].strip(), dates[1].strip()]  # only use 2 dates
            start, end = [parse_time(date).replace(tzinfo=None) for date in dates]
            # order doesnt matter, so check which date is older than the other
            # end time should be the newest date since logs are processed in reverse
            if start < end:  # start is before end date
                start, end = end, start  # swap order
        except:
            await ctx.send("Invalid dates! Try again.")
            return

        guild = ctx.guild
        log_files = glob.glob(os.path.join(PATH, str(guild.id), "*guild*.log"))
        await self.log_sender(ctx, log_files, end, start=start)

    @logs_audit.group(name="user")
    async def logs_audit_user(self, ctx):
        """Audit logs pertaining a user."""
        pass

    @logs_audit_user.command(name="from")
    async def logs_audit_user_from(self, ctx, user: discord.Member, *, till: str):
        """
        Audit logs for server from user going back a time or to a specified date.
        Gets all role and name changes, mutes, etc.
        Also gets audit actions (deleting messages, bans, etc)

        Date/times look like:
            February 14 at 6pm EDT
            2019-04-13 06:43:00 PST
            01/20/18 at 21:00:43

        times default to UTC if no timezone provided.

         Intervals look like:
            5 minutes
            1 minute 30 seconds
            1 hour
            2 days
            30 days
            5h30m
            (etc)
        """
        interval = parse_timedelta(till)
        date = None
        if not interval:
            try:
                date = parse_time(till).replace(tzinfo=None)
            except:
                await ctx.send("Invalid date or interval! Try again.")
                return

        guild = ctx.guild
        log_files = glob.glob(os.path.join(PATH, str(guild.id), "*guild*.log"))

        if interval:
            end_time = datetime.utcnow() - interval
        else:
            end_time = date

        await self.log_sender(ctx, log_files, end_time, user=user)

    @logs_audit_user.command(name="in")
    async def logs_audit_user_in(self, ctx, user: discord.Member = None, *, date: str):
        """
        Audit logs for server from user in between dates.
        Gets all role and name changes, mutes, etc.
        Also gets audit actions (deleting messages, bans, etc)

        Seperate dates with a **semicolon**.

         times look like:
            February 14 at 6pm EDT
            2019-04-13 06:43:00 PST
            01/20/18 at 21:00:43

        times default to UTC if no timezone provided.
        """
        try:
            dates = date.split(";")
            dates = [dates[0].strip(), dates[1].strip()]  # only use 2 dates
            start, end = [parse_time(date).replace(tzinfo=None) for date in dates]
            # order doesnt matter, so check which date is older than the other
            # end time should be the newest date since logs are processed in reverse
            if start < end:  # start is before end date
                start, end = end, start  # swap order
        except:
            await ctx.send("Invalid dates! Try again.")
            return

        guild = ctx.guild
        log_files = glob.glob(os.path.join(PATH, str(guild.id), "*guild*.log"))

        await self.log_sender(ctx, log_files, end, start=start, user=user)

    @logs.group(name="voice")
    async def logs_voice(self, ctx):
        """Gets voice chat logs (leave, join, mutes, etc)"""
        pass

    @logs_voice.command(name="from")
    async def logs_voice_from(self, ctx, channel_id: int, *, till: str):
        """
        Logs for a voice channel going back the specified interval.

         Intervals look like:
            5 minutes
            1 minute 30 seconds
            1 hour
            2 days
            30 days
            5h30m
            (etc)
        """
        interval = parse_timedelta(till)
        date = None
        if not interval:
            try:
                date = parse_time(till).replace(tzinfo=None)
            except:
                await ctx.send("Invalid date or interval! Try again.")
                return

        guild = ctx.guild
        channel = self.bot.get_channel(channel_id)
        if not channel:
            await ctx.send("Invalid channel!")
            return
        log_files = glob.glob(os.path.join(PATH, str(guild.id), "*{}*.log".format(channel.id)))

        if interval:
            end_time = datetime.utcnow() - interval
        else:
            end_time = date

        await self.log_sender(ctx, log_files, end_time)

    @logs_voice.command(name="in")
    async def logs_voice_in(self, ctx, channel_id: int, *, date: str):
        """
        Logs for an entire channel in between the specified dates
        Seperate dates with a **semicolon**.

         times look like:
            February 14 at 6pm EDT
            2019-04-13 06:43:00 PST
            01/20/18 at 21:00:43

        times default to UTC if no timezone provided.
        """
        try:
            dates = date.split(";")
            dates = [dates[0].strip(), dates[1].strip()]  # only use 2 dates
            start, end = [parse_time(date).replace(tzinfo=None) for date in dates]
            # order doesnt matter, so check which date is older than the other
            # end time should be the newest date since logs are processed in reverse
            if start < end:  # start is before end date
                start, end = end, start  # swap order
        except:
            await ctx.send("Invalid dates! Try again.")
            return

        guild = ctx.guild
        channel = self.bot.get_channel(channel_id)
        if not channel:
            await ctx.send("Invalid channel!")
            return
        log_files = glob.glob(os.path.join(PATH, str(guild.id), "*{}*.log".format(channel.id)))

        await self.log_sender(ctx, log_files, end, start=start)

    @commands.group()
    @checks.is_owner()
    async def logset(self, ctx):
        """
        Change activity logging settings
        """
        pass

    @logset.command(name="check-audit")
    async def set_audit_check(self, ctx, on_off: bool = None):
        """
        Set whether to access audit logs to get who does what audit action

        Turning this off means audit actions are saved but who did those actions are not saved.
        This should be turned off for bots in large amount of servers since you will hit global ratelimits very quickly.
        """
        if on_off is not None:
            async with self.config.attrs() as attrs:
                attrs["check_audit"] = on_off
            self.cache["check_audit"] = on_off

        status = self.cache["check_audit"]
        if status:
            await ctx.send("Checking audit logs is enabled.")
        else:
            await ctx.send("Checking audit logs is disabled.")

    @logset.command(name="everything", aliases=["global"])
    async def set_everything(self, ctx, on_off: bool = None):
        """
        Global override for all logging
        """
        if on_off is not None:
            async with self.config.attrs() as attrs:
                attrs["everything"] = on_off
            self.cache["everything"] = on_off

        status = self.cache["everything"]
        if status:
            await ctx.send("Global logging override is enabled.")
        else:
            await ctx.send("Global logging override is disabled.")

    @logset.command(name="default")
    async def set_default(self, ctx, on_off: bool = None):
        """
        Sets whether logging is on or off where unset

        guild overrides, global override, and attachments don't use this.
        """
        if on_off is not None:
            async with self.config.attrs() as attrs:
                attrs["default"] = on_off
            self.cache["default"] = on_off

        status = self.cache["default"]
        if status:
            await ctx.send("Logging is enabled by default.")
        else:
            await ctx.send("Logging is disabled by default.")

    @logset.command(name="dm")
    async def set_direct(self, ctx, on_off: bool = None):
        """
        Log direct messages?
        """
        if on_off is not None:
            async with self.config.attrs() as attrs:
                attrs["direct"] = on_off
            self.cache["direct"] = on_off

        status = self.cache["direct"]

        if status:
            await ctx.send("Logging of direct messages is enabled.")
        else:
            await ctx.send("Logging of direct messages is disabled.")

    @logset.command(name="attachments")
    async def set_attachments(self, ctx, on_off: bool = None):
        """
        Download message attachments?
        """
        if on_off is not None:
            async with self.config.attrs() as attrs:
                attrs["attachments"] = on_off
            self.cache["attachments"] = on_off

        status = self.cache["attachments"]
        if status:
            await ctx.send("Downloading of attachments is enabled.")
        else:
            await ctx.send("Downloading of attachments is disabled.")

    @logset.command(name="channel")
    @commands.guild_only()
    async def set_channel(self, ctx, on_off: bool, channel: discord.TextChannel = None):
        """
        Sets channel logging on or off (channel optional)

        To enable or disable all channels at once, use `logset server`.
        """
        if channel is None:
            channel = ctx.channel

        guild = channel.guild

        self.cache[channel.id]["enabled"] = on_off
        await self.config.channel(channel).enabled.set(on_off)

        if on_off:
            await ctx.send("Logging enabled for %s" % channel.mention)
        else:
            await ctx.send("Logging disabled for %s" % channel.mention)

    @logset.command(name="server")
    @commands.guild_only()
    async def set_guild(self, ctx, on_off: bool):
        """
        Sets logging on or off for all channels and server events
        """
        guild = ctx.guild

        self.cache[guild.id]["all_s"] = on_off
        await self.config.guild(guild).all_s.set(on_off)

        if on_off:
            await ctx.send("Logging enabled for %s" % guild)
        else:
            await ctx.send("Logging disabled for %s" % guild)

    @logset.command(name="voice")
    @commands.guild_only()
    async def set_voice(self, ctx, on_off: bool):
        """
        Sets logging on or off for ALL voice channel events
        """
        guild = ctx.guild

        self.cache[guild.id]["voice"] = on_off
        await self.config.guild(guild).voice.set(on_off)

        if on_off:
            await ctx.send("Voice event logging enabled for %s" % guild)
        else:
            await ctx.send("Voice event logging disabled for %s" % guild)

    @logset.command(name="events")
    @commands.guild_only()
    async def set_events(self, ctx, on_off: bool):
        """
        Sets logging on or off for guild events
        """
        guild = ctx.guild

        self.cache[guild.id]["events"] = on_off
        await self.config.guild(guild).events.set(on_off)

        if on_off:
            await ctx.send("Logging enabled for guild events in %s" % guild)
        else:
            await ctx.send("Logging disabled for guild events in %s" % guild)

    @logset.command(name="prefixes")
    @commands.guild_only()
    async def set_prefixes(self, ctx, *, prefixes: str = None):
        """Set list of prefixes to mark messages as bot commands for user stats.
        Seperate prefixes with spaces
        """
        if not prefixes:
            curr = [f"`{p}`" for p in self.cache[ctx.guild.id]["prefixes"]]
            if not curr:
                await ctx.send("No prefixes set, setting this bot's prefix.")
                await self.config.guild(ctx.guild).prefixes.set([ctx.clean_prefix])
                self.cache[ctx.guild.id]["prefixes"] = [ctx.clean_prefix]
                return
            await ctx.send("Current Prefixes: " + humanize_list(curr))
            return

        prefixes = [p for p in prefixes.split(" ")]
        await self.config.guild(ctx.guild).prefixes.set(prefixes)
        self.cache[ctx.guild.id]["prefixes"] = prefixes
        prefixes = [f"`{p}`" for p in prefixes]
        await ctx.send("Prefixes set to: " + humanize_list(prefixes))

    @logset.command(name="rotation")
    async def set_rotation(self, ctx, freq: str = None):
        """
        Show, disable, or set the log rotation period

        Days start at 00:00 UTC. Attachment folders are still shared.
        When enabled, log filenames will be prepended with their ISO 8601 date and period.
        Example: if monthly, logs for July in channel ID 1234 would be in 20180701--P1M_1234.log

        Valid options are:
        - none: disable rotation
        - d: one log file per day (starts 00:00Z each day)
        - w: one log file per week (starts 00:00Z each Monday)
        - m: one log file per month (starts 00:00Z on first day of month)
        - y: one log file per year (starts 00:00Z Jan 1)
        """
        if freq:
            freq = freq.lower().strip("\"'` ")

        if freq in ("d", "w", "m", "y", "none", "disable"):
            adj = "now"

            if freq in ("none", "disable"):
                freq = None

            async with self.config.attrs() as attrs:
                attrs["rotation"] = freq
            self.cache["rotation"] = freq

        elif freq:
            await self.bot.send_cmd_help(ctx)
            return
        else:
            adj = "currently"
            freq = self.cache["rotation"]

        if not freq:
            await ctx.send("Log rotation is %s disabled." % adj)
        else:
            desc = {"d": "daily", "w": "weekly", "m": "monthly", "y": "yearly"}[freq]

            await ctx.send("Log rotation period is %s %s." % (adj, desc))

    @staticmethod
    def format_rotation_string(timestamp, rotation_code, filename=None):
        kwargs = dict(hour=0, minute=0, second=0, microsecond=0)

        if not rotation_code:
            return filename or ""

        if rotation_code == "y":
            kwargs.update(day=1, month=1)
            start = timestamp.replace(**kwargs)
        elif rotation_code == "m":
            kwargs.update(day=1)
            start = timestamp.replace(**kwargs)
        elif rotation_code == "w":
            start = timestamp - relativedelta(days=timestamp.weekday())

        spec = start.strftime("%Y%m%d")

        if rotation_code == "w":
            spec += "--P7D"
        else:
            spec += "--P1%c" % rotation_code.upper()

        if filename:
            return "%s_%s" % (spec, filename)
        else:
            return spec

    @staticmethod
    def get_voice_flags(voice_state):
        flags = []
        for f in ("deaf", "mute", "self_deaf", "self_mute", "self_stream", "self_video"):
            if getattr(voice_state, f, None):
                flags.append(f)

        return flags

    @staticmethod
    def format_overwrite(target, channel, before, after, user=None):
        if user:
            target_str = "Channel overwrites by @{1.name}#{1.discriminator}(id:{1.id}): {0.name} ({0.id}): ".format(
                channel, user
            )
        else:
            target_str = "Channel overwrites: {0.name} ({0.id}): ".format(channel)
        target_str += "role" if isinstance(target, discord.Role) else "member"
        target_str += " {0.name} ({0.id})".format(target)

        if before:
            bpair = [x.value for x in before.pair()]

        if after:
            apair = [x.value for x in after.pair()]

        if before and after:
            fmt = " updated to values %i, %i (was %i, %i)"
            return target_str + fmt % tuple(apair + bpair)
        elif after:
            return target_str + " added with values %i, %i" % tuple(apair)
        elif before:
            return target_str + " removed (was %i, %i)" % tuple(bpair)

    def gethandle(self, path, mode="a"):
        """Manages logfile handles, culling stale ones and creating folders"""
        if path in self.handles:
            if os.path.exists(path):
                return self.handles[path]
            else:  # file was deleted?
                try:  # try to close, no guarantees tho
                    self.handles[path].close()
                except Exception:
                    pass

                del self.handles[path]
                return self.gethandle(path, mode)
        else:
            # Clean up excess handles before creating a new one
            if len(self.handles) >= 256:
                chrono = sorted(self.handles.items(), key=lambda x: x[1].time)
                oldest_path, oldest_handle = chrono[0]
                oldest_handle.close()
                del self.handles[oldest_path]

            dirname, _ = os.path.split(path)

            try:
                if not os.path.exists(dirname):
                    os.makedirs(dirname)

                handle = LogHandle(path, mode=mode)
            except Exception:
                raise

            self.handles[path] = handle
            return handle

    def should_log(self, location):
        if not self.cache:
            # cache is empty, still booting
            return False

        if self.cache.get("everything", False):
            return True

        default = self.cache.get("default", False)

        if type(location) is discord.Guild:
            loc = self.cache[location.id]
            return loc.get("all_s", False) or loc.get("events", default)

        elif type(location) is discord.TextChannel:
            loc = self.cache[location.guild.id]
            opts = [loc.get("all_s", False), self.cache[location.id].get("enabled", default)]
            return any(opts)

        elif type(location) is discord.VoiceChannel:
            loc = self.cache[location.guild.id]
            opts = [loc.get("all_s", False), loc.get("voice", False)]

            return any(opts)

        elif isinstance(location, discord.abc.PrivateChannel):
            return self.cache.get("direct", default)

        else:  # can't log other types
            return False

    def should_download(self, msg):
        return self.should_log(msg.channel) and self.cache.get("attachments", False)

    def process_attachment(self, message, a):
        aid = a.id
        aname = a.filename
        url = a.url
        channel = message.channel
        path = str(PATH)

        if type(channel) is discord.TextChannel:
            guildid = channel.guild.id
        elif isinstance(channel, discord.abc.PrivateChannel):
            guildid = "direct"

        path = os.path.join(path, str(guildid), str(channel.id) + "_attachments")
        filename = str(aid) + "_" + aname

        if len(filename) > 255:
            target_len = 255 - len(aid) - 4
            part_a = target_len // 2
            part_b = target_len - part_a
            filename = aid + "_" + aname[:part_a] + "..." + aname[-part_b:]
            truncated = True
        else:
            truncated = False

        return aid, url, path, filename, truncated

    async def log(self, location, text, timestamp=None, force=False, subfolder=None, mode="a"):
        if not timestamp:
            timestamp = datetime.utcnow()

        if self.lock or not (force or self.should_log(location)):
            return

        path = []
        entry = [timestamp.strftime(TIMESTAMP_FORMAT)]
        rotation = self.cache["rotation"]
        if type(location) is discord.Guild:
            path += [str(location.id), "guild.log"]
        elif type(location) is discord.TextChannel or type(location) is discord.VoiceChannel:
            guildid = str(location.guild.id)
            entry.append("#" + location.name)
            path += [guildid, str(location.id) + ".log"]
        elif isinstance(location, discord.abc.PrivateChannel):
            path += ["direct", str(location.id) + ".log"]
        elif type(location) is discord.User or type(location) is discord.Member:
            path += ["usernames", "usernames.log"]
        else:
            return

        if subfolder:
            path.insert(-1, str(subfolder))

        text = text.replace("\n", "\\n")
        entry.append(text)

        if rotation:
            path[-1] = self.format_rotation_string(timestamp, rotation, path[-1])

        fname = os.path.join(PATH, *path)
        handle = self.gethandle(fname, mode=mode)
        await handle.write(" ".join(entry) + "\n")

    async def message_handler(self, message, *args, force_attachments=None, **kwargs):
        dl_attachment = self.should_download(message)
        attachments = []

        if force_attachments is not None:
            dl_attachment = force_attachments

        if message.attachments and dl_attachment:
            for a in message.attachments:
                attachments += [self.process_attachment(message, a)]

            entry = DOWNLOAD_TEMPLATE.format(
                message, [a[3] + " (filename truncated)" if a[4] else a[3] for a in attachments]
            )

        elif message.attachments:
            urls = ",".join(a.url for a in message.attachments)
            entry = ATTACHMENT_TEMPLATE.format(message, urls)
        else:
            if message.reference:
                ref_channel = message.guild.get_channel(message.reference.channel_id)
                ref_message = None
                if ref_channel:
                    ref_message = await ref_channel.fetch_message(message.reference.message_id)
                if ref_message:
                    entry = REPLY_TEMPLATE.format(message, ref_message)
                else:
                    entry = MESSAGE_TEMPLATE.format(message)
            else:
                entry = MESSAGE_TEMPLATE.format(message)

        # don't calculate bot stats and make sure this isnt dm message
        if message.author.id != self.bot.user.id and isinstance(message.author, discord.Member):
            is_bot_msg = False
            async with self.config.member(message.author).stats() as stats:
                stats["total_msg"] += 1
                if len(message.content) > 0:
                    for prefix in self.cache[message.guild.id]["prefixes"]:
                        if prefix == message.content[: len(prefix)]:
                            stats["bot_cmd"] += 1
                            is_bot_msg = True
                            break
                    if not is_bot_msg:
                        stats["avg_len"] += len(message.content.split(" "))

        if message.attachments and dl_attachment:
            for i, data in enumerate(attachments):
                aid, url, path, filename, truncated = data
                if not os.path.exists(path):
                    os.mkdir(path)

                dl_path = os.path.join(path, filename)
                if not os.path.exists(dl_path):
                    try:
                        await message.attachments[i].save(dl_path)
                    except:
                        entry += f" (file: {filename} failed to save)"

        await self.log(message.channel, entry, message.created_at, *args, **kwargs)

    # Listeners
    @commands.Cog.listener()
    async def on_message(self, message):
        if await self.bot.cog_disabled_in_guild(self, message.guild):
            return
        await self.message_handler(message)

    @commands.Cog.listener()
    async def on_message_edit(self, before, after):
        if await self.bot.cog_disabled_in_guild(self, after.guild):
            return
        timestamp = before.created_at.strftime(TIMESTAMP_FORMAT)
        entry = EDIT_TEMPLATE.format(before, after, timestamp)
        await self.log(after.channel, entry, after.edited_at)

    @commands.Cog.listener()
    async def on_message_delete(self, message):
        if await self.bot.cog_disabled_in_guild(self, message.guild):
            return
        if not self.should_log(message.channel):
            return
        entry_s = None
        timestamp = message.created_at.strftime(TIMESTAMP_FORMAT)
        if self.cache["check_audit"]:
            try:
                async for entry in message.guild.audit_logs(limit=2):
                    # target is user who had message deleted
                    if entry.action is discord.AuditLogAction.message_delete:
                        if (
                            entry.target.id == message.author.id
                            and entry.extra.channel.id == message.channel.id
                            and entry.created_at.timestamp() > time.time() - 3000
                            and entry.extra.count >= 1
                        ):
                            entry_s = DELETE_AUDIT_TEMPLATE.format(entry.user, message, message.author, timestamp)
                            break
            except:
                pass

        if not entry_s:
            entry_s = DELETE_TEMPLATE.format(message, timestamp)

        await self.log(message.channel, entry_s)

    @commands.Cog.listener()
    async def on_guild_join(self, guild):
        if await self.bot.cog_disabled_in_guild(self, guild):
            return
        entry = "this bot joined the guild"
        await self.log(guild, entry)

    @commands.Cog.listener()
    async def on_guild_remove(self, guild):
        if await self.bot.cog_disabled_in_guild(self, guild):
            return
        entry = "this bot left the guild"
        await self.log(guild, entry)

    @commands.Cog.listener()
    async def on_guild_update(self, before, after):
        if await self.bot.cog_disabled_in_guild(self, after):
            return
        if not self.should_log(before):
            return

        entries = []
        user = None
        if self.cache["check_audit"]:
            try:
                async for entry in after.audit_logs(limit=1):
                    if entry.action is discord.AuditLogAction.guild_update:
                        user = entry.user
            except:
                pass

        if before.owner != after.owner:
            if user:
                entries.append(
                    "guild owner changed by @{2.name}#{2.discriminator}(id:{2.id}), from {0.owner} (id {0.owner.id}) to {1.owner} (id {1.owner.id})"
                )
            else:
                entries.append("guild owner changed from {0.owner} (id {0.owner.id}) to {1.owner} (id {1.owner.id})")

        if before.region != after.region:
            if user:
                entries.append(
                    "guild region changed by @{2.name}#{2.discriminator}(id:{2.id}), from {0.region} to {1.region}"
                )
            else:
                entries.append("guild region changed from {0.region} to {1.region}")

        if before.name != after.name:
            if user:
                entries.append(
                    'guild name changed by @{2.name}#{2.discriminator}(id:{2.id}), from "{0.name}" to "{1.name}"'
                )
            else:
                entries.append('guild name changed from "{0.name}" to "{1.name}"')

        if before.icon_url != after.icon_url:
            if user:
                entries.append(
                    "guild icon changed by @{2.name}#{2.discriminator}(id:{2.id}), from {0.icon_url} to {1.icon_url}"
                )
            else:
                entries.append("guild icon changed from {0.icon_url} to {1.icon_url}")

        if before.splash != after.splash:
            if user:
                entries.append(
                    "guild splash changed by @{2.name}#{2.discriminator}(id:{2.id}), from {0.splash} to {1.splash}"
                )
            else:
                entries.append("guild splash changed from {0.splash} to {1.splash}")

        for e in entries:
            if user:
                await self.log(before, e.format(before, after, user))
            else:
                await self.log(before, e.format(before, after))

    @commands.Cog.listener()
    async def on_guild_role_create(self, role):
        if await self.bot.cog_disabled_in_guild(self, role.guild):
            return
        if not self.should_log(role.guild):
            return

        user = None
        if self.cache["check_audit"]:
            try:
                async for entry in role.guild.audit_logs(limit=2):
                    if entry.action is discord.AuditLogAction.role_create:
                        if entry.target.id == role.id:
                            user = entry.user
            except:
                pass

        if user:
            entry = "Role created by @{1.name}#{1.discriminator}(id:{1.id}): '{0}' (id {0.id})".format(role, user)
        else:
            entry = "Role created: '{0}' (id {0.id})".format(role)

        await self.log(role.guild, entry)

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role):
        if await self.bot.cog_disabled_in_guild(self, role.guild):
            return
        if not self.should_log(role.guild):
            return

        user = None
        if self.cache["check_audit"]:
            try:
                async for entry in role.guild.audit_logs(limit=2):
                    if entry.action is discord.AuditLogAction.role_delete:
                        if entry.target.id == role.id:
                            user = entry.user
            except:
                pass

        if user:
            entry = "Role deleted by @{1.name}#{1.discriminator}(id:{1.id}): '{0}' (id {0.id})".format(role, user)
        else:
            entry = "Role deleted: '{0}' (id {0.id})".format(role)

        await self.log(role.guild, entry)

    @commands.Cog.listener()
    async def on_guild_role_update(self, before, after):
        if await self.bot.cog_disabled_in_guild(self, after.guild):
            return
        if not self.should_log(before.guild):
            return

        entries = []
        user = None
        if self.cache["check_audit"]:
            try:
                async for entry in after.guild.audit_logs(limit=2):
                    if entry.action is discord.AuditLogAction.role_update:
                        if entry.target.id == after.id:
                            user = entry.user
            except:
                pass

        if before.name != after.name:
            if user:
                entries.append('Role renamed by @{2.name}#{2.discriminator}(id:{2.id}): "{0.name}" to "{1.name}"')
            else:
                entries.append('Role renamed: "{0.name}" to "{1.name}"')

        if before.color != after.color:
            if user:
                entries.append(
                    'Role color by @{2.name}#{2.discriminator}(id:{2.id}): "{0}" (id {0.id}) changed from {0.color} to {1.color}'
                )
            else:
                entries.append('Role color: "{0}" (id {0.id}) changed from {0.color} to {1.color}')

        if before.mentionable != after.mentionable:
            if after.mentionable:
                if user:
                    entries.append(
                        'Role mentionable by @{2.name}#{2.discriminator}(id:{2.id}): "{1.name}" (id {1.id}) is now mentionable'
                    )
                else:
                    entries.append('Role mentionable: "{1.name}" (id {1.id}) is now mentionable')
            else:
                if user:
                    entries.append(
                        'Role mentionable by @{2.name}#{2.discriminator}(id:{2.id}): "{1.name}" (id {1.id}) is no longer mentionable'
                    )
                else:
                    entries.append('Role mentionable: "{1.name}" (id {1.id}) is no longer mentionable')

        if before.hoist != after.hoist:
            if after.hoist:
                if user:
                    entries.append(
                        'Role hoist by @{2.name}#{2.discriminator}(id:{2.id}): "{1.name}" (id {1.id}) is now shown seperately'
                    )
                else:
                    entries.append('Role hoist: "{1.name}" (id {1.id}) is now shown seperately')
            else:
                if user:
                    entries.append(
                        'Role hoist by @{2.name}#{2.discriminator}(id:{2.id}): "{1.name}" (id {1.id}) is no longer shown seperately'
                    )
                else:
                    entries.append('Role hoist: "{1.name}" (id {1.id}) is no longer shown seperately')

        if before.permissions != after.permissions:
            if user:
                entries.append(
                    'Role permissions by @{2.name}#{2.discriminator}(id:{2.id}): "{1.name}" (id {1.id}) changed from {0.permissions.value} '
                    "to {1.permissions.value}"
                )
            else:
                entries.append(
                    'Role permissions: "{1.name}" (id {1.id}) changed from {0.permissions.value} '
                    "to {1.permissions.value}"
                )

        if before.position != after.position:
            if user:
                entries.append(
                    'Role position by @{2.name}#{2.discriminator}(id:{2.id}): "{0}" changed from {0.position} to {1.position}'
                )
            else:
                entries.append('Role position: "{0}" changed from {0.position} to {1.position}')

        for e in entries:
            if user:
                await self.log(before.guild, e.format(before, after, user))
            else:
                await self.log(before.guild, e.format(before, after))

    @commands.Cog.listener()
    async def on_member_join(self, member):
        if await self.bot.cog_disabled_in_guild(self, member.guild):
            return
        entry = "Member join: @{0} (id {0.id})".format(member)

        async with self.config.user(member).past_names() as past_names:
            if str(member) not in past_names:
                past_names.append(str(member))

        await self.log(member.guild, entry)

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        if await self.bot.cog_disabled_in_guild(self, member.guild):
            return
        if not self.should_log(member.guild):
            await self.config.member(member).clear()
            return

        user = None
        if self.cache["check_audit"]:
            try:
                async for entry in member.guild.audit_logs(limit=2):
                    if entry.action is discord.AuditLogAction.kick:
                        if entry.target.id == member.id:
                            user = entry.user
            except:
                pass

        if user:
            entry = "Member kicked by @{1.name}#{1.discriminator}(id:{1.id}): @{0} (id {0.id})".format(member, user)
        else:
            entry = "Member leave: @{0} (id {0.id})".format(member)

        # don't clear stats right away if welcome cog is install so it can pull user stats
        if self.bot.get_cog("Welcome"):
            await asyncio.sleep(1)

        await self.config.member(member).clear()
        await self.log(member.guild, entry)

    @commands.Cog.listener()
    async def on_member_ban(self, guild, member):
        if await self.bot.cog_disabled_in_guild(self, guild):
            return
        if not self.should_log(guild):
            return

        user = None
        if self.cache["check_audit"]:
            try:
                async for entry in guild.audit_logs(limit=2):
                    if entry.action is discord.AuditLogAction.ban:
                        if entry.target.id == member.id:
                            user = entry.user
            except:
                pass

        if user:
            entry = "Member banned by @{1.name}#{1.discriminator}(id:{1.id}): @{0} (id {0.id})".format(member, user)
        else:
            entry = "Member ban: @{0} (id {0.id})".format(member)

        await self.log(guild, entry)

    @commands.Cog.listener()
    async def on_member_unban(self, guild, member):
        if await self.bot.cog_disabled_in_guild(self, guild):
            return
        if not self.should_log(guild):
            return

        user = None
        if self.cache["check_audit"]:
            try:
                async for entry in guild.audit_logs(limit=2):
                    if entry.action is discord.AuditLogAction.unban:
                        if entry.target.id == member.id:
                            user = entry.user
            except:
                pass

        if user:
            entry = "Member unbanned by @{1.name}#{1.discriminator}(id:{1.id}): @{0} (id {0.id})".format(member, user)
        else:
            entry = "Member unban: @{0} (id {0.id})".format(member)

        await self.log(guild, entry)

    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        if await self.bot.cog_disabled_in_guild(self, after.guild):
            return
        if not self.should_log(before.guild):
            return

        entries = []
        user = None
        if self.cache["check_audit"]:
            try:
                async for entry in after.guild.audit_logs(limit=2):
                    if (
                        entry.action is discord.AuditLogAction.member_update
                        or entry.action is discord.AuditLogAction.member_role_update
                    ):
                        if entry.target.id == after.id:
                            user = entry.user
            except:
                pass

        if before.nick != after.nick:
            if user:
                entries.append(
                    'Member nickname changed by @{2.name}#{2.discriminator}(id:{2.id}): "@{0}" (id {0.id}) nickname change from "{0.nick}" to "{1.nick}"'
                )
            else:
                entries.append('Member nickname: "@{0}" (id {0.id}) changed nickname from "{0.nick}" to "{1.nick}"')

        if before.roles != after.roles:
            broles = set(before.roles)
            aroles = set(after.roles)
            added = aroles - broles
            removed = broles - aroles

            for r in added:
                if user:
                    entries.append(
                        'Member role added by @{1.name}#{1.discriminator}(id:{1.id}): "{0}" (id {0.id}) role '
                        'was added to "@{{0}}" (id {{0.id}})'.format(r, user)
                    )
                else:
                    entries.append(
                        'Member role add: "{0}" (id {0.id}) role ' 'was added to "@{{0}}" (id {{0.id}})'.format(r)
                    )

            for r in removed:
                if user:
                    entries.append(
                        'Member role removed by @{1.name}#{1.discriminator}(id:{1.id}): "{0}" (id {0.id}) role was removed from "@{{0}}" (id {{0.id}})'.format(
                            r, user
                        )
                    )
                else:
                    entries.append(
                        'Member role remove: "{0}" (id {0.id}) role '
                        'was removed from "@{{0}}" (id {{0.id}})'.format(r)
                    )

        for e in entries:
            await self.log(before.guild, e.format(before, after, user))

    @commands.Cog.listener()
    async def on_user_update(self, before, after):
        entries = []

        if before.name != after.name:
            entries.append('Member username: "@{0}" (id {0.id}) changed username from "{0.name}" to "{1.name}"')
            async with self.config.user(after).past_names() as past_names:
                if str(after) not in past_names:
                    past_names.append(str(after))

        if before.discriminator != after.discriminator:
            entries.append('Member discriminator: "@{0}" (id {0.id}) changed discriminator from "{0}" to "{1}"')
            async with self.config.user(after).past_names() as past_names:
                if str(after) not in past_names:
                    past_names.append(str(after))

        for e in entries:
            await self.log(after, e.format(before, after))

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel):
        if await self.bot.cog_disabled_in_guild(self, channel.guild):
            return
        if not self.should_log(channel.guild):
            return

        user = None
        if self.cache["check_audit"]:
            try:
                async for entry in channel.guild.audit_logs(limit=2):
                    if entry.action is discord.AuditLogAction.channel_create:
                        if entry.target.id == after.id:
                            user = entry.user
            except:
                pass

        if user:
            entry = 'Channel created by @{1.name}#{1.discriminator}(id:{1.id}): "{0.name}" (id {0.id})'.format(
                channel, user
            )
        else:
            entry = 'Channel created: "{0.name}" (id {0.id})'.format(channel)

        await self.log(channel.guild, entry)

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel):
        if await self.bot.cog_disabled_in_guild(self, channel.guild):
            return
        if not self.should_log(channel.guild):
            return

        user = None
        if self.cache["check_audit"]:
            try:
                async for entry in channel.guild.audit_logs(limit=2):
                    if entry.action is discord.AuditLogAction.channel_delete:
                        if entry.target.id == after.id:
                            user = entry.user
            except:
                pass

        if user:
            entry = 'Channel deleted by @{1.name}#{1.discriminator}(id:{1.id}): "{0.name}" (id {0.id})'.format(
                channel, user
            )
        else:
            entry = 'Channel deleted: "{0.name}" (id {0.id})'.format(channel)

        await self.log(channel.guild, entry)

    @commands.Cog.listener()
    async def on_guild_channel_update(self, before, after):
        if await self.bot.cog_disabled_in_guild(self, after.guild):
            return
        if not self.should_log(before.guild):
            return

        user = None
        if self.cache["check_audit"]:
            try:
                async for entry in after.guild.audit_logs(limit=2):
                    if entry.action is discord.AuditLogAction.channel_update:
                        if entry.target.id == after.id:
                            user = entry.user
            except:
                pass

        entries = []

        if before.name != after.name:
            if user:
                entries.append(
                    'Channel rename by @{2.name}#{2.discriminator}(id:{2.id}): "{0.name}" (id {0.id}) renamed to "{1.name}"'
                )
            else:
                entries.append('Channel rename: "{0.name}" (id {0.id}) renamed to "{1.name}"')

        if isinstance(before, discord.TextChannel):
            if before.topic != after.topic:
                if user:
                    entries.append(
                        'Channel topic by @{2.name}#{2.discriminator}(id:{2.id}): "{0.name}" (id {0.id}) topic was set to "{1.topic}"'
                    )
                else:
                    entries.append('Channel topic: "{0.name}" (id {0.id}) topic was set to "{1.topic}"')

        if before.position != after.position:
            if user:
                entries.append(
                    'Channel position by @{2.name}#{2.discriminator}(id:{2.id}): "{0.name}" (id {0.id}) moved from {0.position} to {1.position}'
                )
            else:
                entries.append('Channel position: "{0.name}" (id {0.id}) moved from {0.position} to {1.position}')

        before_ow = dict(before.overwrites)
        after_ow = dict(after.overwrites)
        before_ow_set = set(before_ow)
        after_ow_set = set(after_ow)

        for old_ow in before_ow_set - after_ow_set:
            entries.append(self.format_overwrite(old_ow, before, before_ow[old_ow], None, user=user))

        for new_ow in after_ow_set - before_ow_set:
            entries.append(self.format_overwrite(new_ow, before, None, after_ow[new_ow], user=user))

        for isect_ow in after_ow_set & before_ow_set:
            if before_ow[isect_ow].pair() == after_ow[isect_ow].pair():
                continue

            entries.append(self.format_overwrite(isect_ow, before, before_ow[isect_ow], after_ow[isect_ow], user=user))

        for e in entries:
            if user:
                await self.log(before.guild, e.format(before, after, user))
            else:
                await self.log(before.guild, e.format(before, after))

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if await self.bot.cog_disabled_in_guild(self, member.guild):
            return
        if not self.should_log(before.channel):
            return

        # will add audit logging later, just a pain trying to figure it out here

        if before.channel != after.channel:
            if before.channel:
                msg = "Voice channel leave: {0} (id {0.id})"

                async with self.config.member(member).stats() as stats:
                    if stats["last_vc_time"]:  # incase someone joins when bot is offline
                        stats["vc_time_sec"] += time.time() - stats["last_vc_time"]
                        stats["last_vc_time"] = None

                if after.channel:
                    msg += " moving to {1.channel}"

                await self.log(before.channel, msg.format(member, after))

            if after.channel:
                msg = "Voice channel join: {0} (id {0.id})"

                async with self.config.member(member).stats() as stats:
                    stats["last_vc_time"] = time.time()

                if before.channel:
                    msg += ", moved from {1.channel}"

                flags = self.get_voice_flags(after)

                if flags:
                    msg += ", flags: %s" % ",".join(flags)

                await self.log(after.channel, msg.format(member, before))

        if before.deaf != after.deaf:
            verb = "deafen" if after.deaf else "undeafen"
            await self.log(before.channel, "guild {0}: {1} (id {1.id})".format(verb, member))

        if before.mute != after.mute:
            verb = "mute" if after.mute else "unmute"
            await self.log(before.channel, "guild {0}: {1} (id {1.id})".format(verb, member))

        if before.self_deaf != after.self_deaf:
            verb = "deafen" if after.self_deaf else "undeafen"
            await self.log(before.channel, "guild self-{0}: {1} (id {1.id})".format(verb, member))

        if before.self_mute != after.self_mute:
            verb = "mute" if after.self_mute else "unmute"
            await self.log(before.channel, "guild self-{0}: {1} (id {1.id})".format(verb, member))

        if before.self_stream != after.self_stream:
            verb = "stop-stream" if not after.self_stream else "start-stream"
            await self.log(before.channel, "guild self-{0}: {1} (id {1.id})".format(verb, member))

        if before.self_video != after.self_video:
            verb = "start-video" if after.self_video else "stop-video"
            await self.log(before.channel, "guild self-{0}: {1} (id {1.id})".format(verb, member))

    # async def red_get_data_for_user(self, user_id: int):
    # default_user = {"past_names": []}
    # default_member = {
    #    "stats": {"total_msg": 0, "bot_cmd": 0, "avg_len": 0.0, "vc_time_sec": 0.0, "last_vc_time": None}
    #    }
    # past_names = await self.config.user_from_id(user_id).past_names()
    # data = {"past_names": past_names}

    # for guild in self.bot.guilds:
    #    member = guild.get_member(user_id)
    #    if member:
    #        data[guild.name] = await self.config.member(member).stats()

    async def red_delete_data_for_user(
        self,
        *,
        requester: Literal["discord_deleted_user", "owner", "user", "user_strict"],
        user_id: int,
    ):
        pass
