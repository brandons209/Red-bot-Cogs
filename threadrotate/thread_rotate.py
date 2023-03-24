import asyncio
import discord
import random
import matplotlib.pyplot as plt
import pandas as pd
from typing import Optional, Literal
from io import BytesIO

from redbot.core import Config, checks, commands
from redbot.core.utils.chat_formatting import *
from redbot.core.utils.predicates import MessagePredicate

from .discord_thread_feature import send_thread_message, create_thread
from .time_utils import parse_time, parse_timedelta

from datetime import datetime
from datetime import timedelta


class ThreadRotate(commands.Cog):
    """
    Rotate threads for events, roleplay, etc
    """

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=45612361654894681623, force_registration=True)
        self.methods = ["replacement", "unique"]
        default_channel = {
            "topics": {},
            "topic_threads": {},
            "ping_roles": [],
            "rotation_interval": 10080,
            "rotate_on": None,
            "method": "replacement",
            "prev_topics": [],
            "last_topic": None,
        }
        self.config.register_channel(**default_channel)

        self.task = asyncio.create_task(self.thread_rotation_task())

    def cog_unload(self):
        if self.task is not None:
            self.task.cancel()
        return super().cog_unload()()

    async def thread_rotation_task(self):
        await self.bot.wait_until_ready()

        while True:
            for guild in self.bot.guilds:
                for channel in guild.text_channels:
                    topics = await self.config.channel(channel).topics()
                    if not topics:
                        continue
                    rotate_on = datetime.fromtimestamp(await self.config.channel(channel).rotate_on())
                    if datetime.now() > rotate_on:
                        await self.rotate_thread(channel)
                        await asyncio.sleep(1)

            await asyncio.sleep(60)

    async def rotate_thread(self, channel: discord.TextChannel):
        topics = await self.config.channel(channel).topics()
        topic_threads = await self.config.channel(channel).topic_threads()
        ping_roles = await self.config.channel(channel).ping_roles()
        rotation = timedelta(seconds=await self.config.channel(channel).rotation_interval())
        rotate_on = datetime.now()
        last_topic = await self.config.channel(channel).last_topic()
        method = await self.config.channel(channel).method()
        prev_topics = await self.config.channel(channel).prev_topics()

        # choose new topic
        # don't want to choose the last topic, so set it's weight to 0 so it is not choosen
        if last_topic is not None:
            topics[last_topic] = 0

        # select without replacement if method is "unique"
        if method == "unique":
            # first check if the list of topics have been exhausted
            topic_names = list(topics.keys())
            cnt = 0
            for t in topic_names:
                if t in prev_topics:
                    cnt += 1

            # reset list
            if cnt == len(topic_names):
                prev_topics = []

            for t in prev_topics:
                topics[t] = 0

        new_topic = random.choices(list(topics.keys()), weights=list(topics.values()), k=1)[0]

        # rotate the thread, create new thread, ping roles, etc
        # ping roles
        roles = [channel.guild.get_role(r) for r in ping_roles]
        roles = [r for r in roles if r is not None]

        role_msg = " ".join([r.mention for r in roles])
        role_msg += f"\n\nHello, a new topic has been set for {channel.mention}: `{new_topic}`"

        # if a thread already exists for the topic, try to send a message to it to unarchive it
        new_thread_id = None
        if new_topic in topic_threads:
            try:
                await send_thread_message(self.bot, topic_threads[new_topic], role_msg, mention_roles=ping_roles)
                new_thread_id = topic_threads[new_topic]
            except (
                discord.HTTPException
            ):  # may occur if bot cant unarchive manually archived threads or thread is deleted
                try:
                    new_thread_id = await create_thread(self.bot, channel, new_topic, archive=10080)
                except discord.HTTPException:
                    return
                await send_thread_message(self.bot, new_thread_id, role_msg, mention_roles=ping_roles)
        else:
            try:
                new_thread_id = await create_thread(self.bot, channel, new_topic, archive=10080)
            except discord.HTTPException:
                return
            await send_thread_message(self.bot, new_thread_id, role_msg, mention_roles=ping_roles)

        # update next rotation
        async with self.config.channel(channel).topic_threads() as topic_threads:
            topic_threads[new_topic] = new_thread_id

        await self.config.channel(channel).rotate_on.set(int((rotate_on + rotation).timestamp()))
        await self.config.channel(channel).last_topic.set(new_topic)
        if method == "unique":
            prev_topics.append(new_topic)
            await self.config.channel(channel).prev_topics.set(prev_topics)

    @commands.group(name="rotate")
    @commands.guild_only()
    @checks.admin()
    async def thread_rotate(self, ctx):
        """
        Manage thread rotations per channel
        """
        pass

    @thread_rotate.command(name="simulation")
    async def thread_rotate_simulation(self, ctx, channel: discord.TextChannel):
        """
        Run a simulation using the settings for the channel to see how often topics are chosen.
        """
        topics = await self.config.channel(channel).topics()
        if not topics:
            await ctx.send(error("That channel has not been setup for thread rotation!"), delete_after=30)
            return

        topic_names = [k + f": {v}" for k, v in topics.items()]
        dist = random.choices(topic_names, weights=list(topics.values()), k=10000 * len(topics))

        # make graph and send it
        fontsize = 30
        fig = plt.figure(figsize=(50, 20 + 10 * (len(topics) % 10)))

        # define graph and table save paths
        save_path = BytesIO()

        pd.Series(dist).value_counts(sort=False).plot(kind="barh")

        # make graph look nice
        plt.title(
            f"Simulation for {channel} with {len(topics)} unique topics and {10000 * len(topics)} rotations",
            fontsize=fontsize,
        )
        plt.xlabel("# of times chosen", fontsize=fontsize)
        plt.ylabel("Topics and Weights", fontsize=fontsize)
        plt.xticks(fontsize=fontsize)
        plt.yticks(fontsize=fontsize)
        plt.grid(True)

        fig.tight_layout()

        fig.savefig(save_path, dpi=fig.dpi)
        plt.close()

        save_path.seek(0)
        files = [discord.File(save_path, filename="graph.png")]
        await ctx.send(files=files)
        save_path.close()

    @thread_rotate.command(name="manual")
    async def thread_rotate_manual(self, ctx, channel: discord.TextChannel):
        """
        Manually rotate a thread topic
        """
        current = await self.config.channel(channel).topics()
        if not current:
            await ctx.send(error("That channel has not been setup for thread rotation!"), delete_after=30)
            return

        await self.rotate_thread(channel)
        await ctx.tick()

    @thread_rotate.command(name="method")
    async def thread_rotate_method(self, ctx, channel: discord.TextChannel, method: str):
        """
        Set the method for random selection of topics.

        Possible methods are:
            - replacement: select a channel with replacement, meaning the same channel can be selected again for every rotation.
            - unique: select a channel without replacement, meaning for each rotation a new topic will be selected that was not selected previously, until all topics are exhausted.
        """
        current = await self.config.channel(channel).topics()
        if not current:
            await ctx.send(error("That channel has not been setup for thread rotation!"), delete_after=30)
            return

        method = method.lower()
        if method not in self.methods:
            await ctx.send(
                error(f"Unknown method {method}, please choose from this list: {humanize_list(self.methods)}."),
                delete_after=60,
            )
            return

        prev_method = await self.config.channel(channel).method()

        if method == prev_method:
            await ctx.send(info(f"Selection method for {channel.mention} is already set to {method}!"), delete_after=60)
            return

        if prev_method == "replacement":
            await self.config.channel(channel).prev_topics.clear()

        await self.config.channel(channel).method.set(method)
        await ctx.tick()

    @thread_rotate.command(name="interval")
    async def thread_rotate_interval(self, ctx, channel: discord.TextChannel, interval: str):
        """
        Modify the rotation interval for a thread rotation

        The channel must of already been setup for thread rotation

        This will apply on the next thread rotation for the channel!
        """
        current = await self.config.channel(channel).topics()
        if not current:
            await ctx.send(error("That channel has not been setup for thread rotation!"), delete_after=30)
            return

        interval = parse_timedelta(interval.strip())
        if interval is None:
            await ctx.send(error("Invalid time interval, please try again!"), delete_after=60)
            return

        await self.config.channel(channel).rotation_interval.set(interval.total_seconds())
        await ctx.tick()

    @thread_rotate.command(name="roles")
    async def thread_rotate_roles(self, ctx, channel: discord.TextChannel, *roles: discord.Role):
        """
        Modify the ping roles for a thread rotation

        The channel must of already been setup for thread rotation
        """
        current = await self.config.channel(channel).topics()
        if not current:
            await ctx.send(error("That channel has not been setup for thread rotation!"), delete_after=30)
            return

        await self.config.channel(channel).ping_roles.set([r.id for r in roles])
        await ctx.tick()

    @thread_rotate.command(name="topics")
    async def thread_rotate_topics(self, ctx, channel: discord.TextChannel):
        """
        Modify topics for thread rotation.

        The channel must of already been setup for thread rotation
        """
        current = await self.config.channel(channel).topics()
        if not current:
            await ctx.send(error("That channel has not been setup for thread rotation!"), delete_after=30)
            return

        await ctx.send(info(f"{channel.mention}'s topics:"))
        topic_msg = "Topics:\n"
        for topic, weight in current.items():
            topic_msg += f"{topic}: {weight}\n"

        for page in pagify(topic_msg):
            await ctx.send(box(page), delete_after=300)

        await ctx.send(
            info(
                "Please list the thread topics and their selection weights.\nThe weight is how likely the topic will be choosen.\nA weight of `1` means it will not be choosen more or less than other topics.\nA weight between 0 and 1 means it is that weight times less likely to be choosen, with a weight of 0 meaning it will never be choosen.\nA weight greater than 1 means it will be that times more likely to be choosen.\n\nFor example, a weight of 1.5 means that topic is 1.5 more likely to be choose over the others. A weight of 0.5 means that topic is half as likely to be choosen over others.\n\nPlease use this format for listing the weights:\n"
            ),
            delete_after=300,
        )
        msg = await ctx.send(
            box("topic name: weight_value\ntopic 2 name: weight_value\ntopic 3 name: weight_value")
            + "\n\nYou can send as many messages as needed, when you are done, type `done`."
        )

        topic_msg = ""
        while msg.content.lower() != "done":
            pred = MessagePredicate.same_context(ctx)
            try:
                msg = await self.bot.wait_for("message", check=pred, timeout=301)
            except asyncio.TimeoutError:
                await ctx.send(error("Took too long, cancelling setup!"), delete_after=30)
                return
            topic_msg += msg.content + "\n"

        topics = topic_msg.strip().split("\n")[:-1]  # remove done from end
        parsed_topics = {}
        for topic in topics:
            topic = topic.split(":")
            try:
                if len(topic) > 2:
                    parsed_topics[":".join(topic[0:-1])] = float(topic[-1])
                else:
                    parsed_topics[topic[0]] = float(topic[-1])

                if float(topic[-1]) < 0:
                    raise ValueError()
            except:
                await ctx.send(
                    error(
                        "Please make sure to use the correct format, every topic and weight should be split by a `:` and the weight should be a single decimal value greater than or equal to 0. Topic {topic} caused this error."
                    ),
                    delete_after=60,
                )
                return

        await self.config.channel(channel).topics.set(parsed_topics)
        await ctx.send(info("Topics changed successfully!"), delete_after=60)

    @thread_rotate.command(name="clear")
    async def thread_rotate_clear(self, ctx, channel: discord.TextChannel):
        """
        Clear a channel's thread rotation settings
        """
        await ctx.send(
            warning(f"Are you sure you want to delete all settings for {channel.mention}? This cannot be reversed."),
            delete_after=31,
        )
        pred = MessagePredicate.yes_or_no(ctx)
        try:
            await self.bot.wait_for("message", check=pred, timeout=30)
        except asyncio.TimeoutError:
            await ctx.send(error("Took too long, cancelling clear!"), delete_after=30)
            return

        if not pred.result:
            await ctx.send(info("Cancelling clear."), delete_after=30)
            return

        await self.config.channel(channel).clear()
        await ctx.send(info(f"Settings for {channel.mention} cleared."), delete_after=30)

    @thread_rotate.command(name="setup")
    async def thread_rotate_setup(self, ctx, channel: discord.TextChannel):
        """
        Interactively setup a thread rotation for a channel
        """
        guild = ctx.guild
        now = datetime.now()

        await ctx.send(
            info(
                "Welcome to the thread rotation setup wizard!\n\nFirst, please specifiy the rotation interval. Rotation intervals can be formatted as follows:\n\t5 minutes\n\t1 minute 30 seconds\n\t1 hour\n\t2 days\n\t30 days\n\t5h30m\n\t(etc)"
            ),
            delete_after=300,
        )

        pred = MessagePredicate.same_context(ctx)
        try:
            msg = await self.bot.wait_for("message", check=pred, timeout=121)
        except asyncio.TimeoutError:
            await ctx.send(error("Took too long, cancelling setup!"), delete_after=30)
            return

        interval = parse_timedelta(msg.content.strip())
        if interval is None:
            await ctx.send(error("Invalid time interval, please run setup again!"), delete_after=60)
            return

        await ctx.send(
            info(
                "Thank you.\n\nNow, please specify the date and time to start rotation. You can say `now` to start rotation as soon as setup is complete.\n\nValid date formats are:\n\tFebruary 14 at 6pm EDT\n\t2019-04-13 06:43:00 PST\n\t01/20/18 at 21:00:43\n\t(etc)"
            ),
            delete_after=300,
        )

        pred = MessagePredicate.same_context(ctx)
        try:
            msg = await self.bot.wait_for("message", check=pred, timeout=121)
        except asyncio.TimeoutError:
            await ctx.send(error("Took too long, cancelling setup!"), delete_after=30)
            return

        if msg.content.strip().lower() == "now":
            date = datetime.now()
        else:
            date = parse_time(msg.content.strip())

        if date is None:
            await ctx.send(error("Invalid date, please run setup again!"), delete_after=60)
            return

        if date < now:
            await ctx.send(
                error("Invalid date, the date must be in the future! Please run the setup again."), delete_after=60
            )

        await ctx.send(
            info(
                "Great, next step is to list all roles that should be pinged and added to each thread when it rotates.\n\nList each role **seperated by a comma `,`**.\nYou can use role IDs, role mentions, or role names. If you do not want to ping any roles type `next` or `no`."
            ),
            delete_after=300,
        )

        pred = MessagePredicate.same_context(ctx)
        try:
            msg = await self.bot.wait_for("message", check=pred, timeout=241)
        except asyncio.TimeoutError:
            await ctx.send(error("Took too long, cancelling setup!"), delete_after=30)
            return

        if msg.content.strip().lower() != "no" and msg.content.strip().lower() != "next":
            roles = [m.strip().strip("<").strip(">").strip("@").strip("&") for m in msg.content.split(",")]
            role_objs = []
            for r in roles:
                try:
                    role = guild.get_role(int(r))
                except:
                    role = discord.utils.find(lambda c: c.name == r, guild.roles)
                    if role is None:
                        await ctx.send(
                            error(
                                f"Unknown role: `{r}`, please run the command again. (make sure to seperate roles by commas!)"
                            ),
                            delete_after=60,
                        )
                        return

                role_objs.append(role)
        else:
            role_objs = []

        await ctx.send(
            info(
                "Next step: select the method I will use to rotate topics with.\nAvailable methods are:\n\t- `replacement`: the same channel can be selected again for every rotation.\n\t- `unique`: for each rotation a new topic will be selected that was not selected previously, until all topics are exhausted."
            ),
            delete_after=300,
        )

        pred = MessagePredicate.same_context(ctx)
        try:
            msg = await self.bot.wait_for("message", check=pred, timeout=241)
        except asyncio.TimeoutError:
            await ctx.send(error("Took too long, cancelling setup!"), delete_after=30)
            return

        method = msg.content.lower().strip()
        if method not in self.methods:
            await ctx.send(
                error(f"Unknown method {method}, please choose from this list: {humanize_list(self.methods)}."),
                delete_after=30,
            )
            return

        await ctx.send(
            info(
                "Final step is to list the thread topics and their selection weights.\nThe weight is how likely the topic will be choosen.\nA weight of `1` means it will not be choosen more or less than other topics.\nA weight between 0 and 1 means it is that weight times less likely to be choosen, with a weight of 0 meaning it will never be choosen.\nA weight greater than 1 means it will be that times more likely to be choosen.\n\nFor example, a weight of 1.5 means that topic is 1.5 more likely to be choose over the others. A weight of 0.5 means that topic is half as likely to be choosen over others.\n\nPlease use this format for listing the weights:\n"
            ),
            delete_after=300,
        )
        msg = await ctx.send(
            box("topic name: weight_value\ntopic 2 name: weight_value\ntopic 3 name: weight_value")
            + "\n\nYou can send as many messages as needed, when you are done, type `done`."
        )

        topic_msg = ""
        while msg.content.lower() != "done":
            pred = MessagePredicate.same_context(ctx)
            try:
                msg = await self.bot.wait_for("message", check=pred, timeout=301)
            except asyncio.TimeoutError:
                await ctx.send(error("Took too long, cancelling setup!"), delete_after=30)
                return
            topic_msg += msg.content + "\n"

        topics = topic_msg.strip().split("\n")[:-1]  # remove done from end
        parsed_topics = {}
        for topic in topics:
            topic = topic.split(":")
            try:
                if len(topic) > 2:
                    parsed_topics[":".join(topic[0:-1])] = float(topic[-1])
                else:
                    parsed_topics[topic[0]] = float(topic[-1])

                if float(topic[-1]) < 0:
                    raise ValueError()
            except:
                await ctx.send(
                    error(
                        "Please make sure to use the correct format, every topic and weight should be split by a `:` and the weight should be a single decimal value greater than or equal to 0. Topic {topic} caused this error."
                    ),
                    delete_after=60,
                )
                return

        topic_msg = "Topics:\n"
        for topic, weight in parsed_topics.items():
            topic_msg += f"{topic}: {weight}\n"

        await ctx.send(
            info(f"Please review the settings for thread rotation on channel {channel.mention}:"),
            delete_after=300,
        )
        await ctx.send(
            box(
                f"Rotation interval: {humanize_timedelta(seconds=interval.total_seconds())}\n\nRotation Start: {date}\n\nRotation Method: `{method}`\n\nPing roles: {humanize_list([r.name for r in role_objs])}"
            ),
            delete_after=300,
        )
        for page in pagify(topic_msg):
            await ctx.send(
                box(page),
                delete_after=300,
            )

        await ctx.send("Type yes to confirm the thread rotation, type no to cancel thread rotation setup.")

        pred = MessagePredicate.yes_or_no(ctx)

        try:
            msg = await self.bot.wait_for("message", check=pred, timeout=240)
        except asyncio.TimeoutError:
            await ctx.send(error("Took too long, cancelling setup!"), delete_after=30)
            return

        if not pred.result:
            await ctx.send(info("Cancelled setup."), delete_after=60)
            return

        # setup the channel
        await self.config.channel(channel).topics.set(parsed_topics)
        await self.config.channel(channel).ping_roles.set([r.id for r in role_objs])
        await self.config.channel(channel).rotation_interval.set(interval.total_seconds())
        await self.config.channel(channel).rotate_on.set(int(date.timestamp()))
        await self.config.channel(channel).method.set(method)

        await ctx.send(
            info(f"Thread rotation setup! The first rotation will start at <t:{int(date.timestamp())}>"),
            delete_after=60,
        )
