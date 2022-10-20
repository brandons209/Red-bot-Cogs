import asyncio
import discord
import random
from typing import Optional, Literal

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

        default_channel = {
            "topics": {},
            "topic_threads": {},
            "ping_roles": [],
            "rotation_interval": 10080,
            "rotate_on": None,
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
        rotate_on = datetime.fromtimestamp(await self.config.channel(channel).rotate_on())
        last_topic = await self.config.channel(channel).last_topic()

        # choose new topic
        # don't want to choose the last topic, so set it's weight to 0 so it is not choosen
        if last_topic is not None:
            topics[last_topic] = 0

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
            except discord.HTTPException:  # may occur if bot cant unarchive manually archived threads or thread is deleted
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

    @commands.group(name="rotate")
    @commands.guild_only()
    @checks.admin()
    async def thread_rotate(self, ctx):
        """
        Manage thread rotations per channel
        """
        pass

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
    async def thread_rotate_topics(self, ctx, channel: discord.TextChannel, *, topics: str = None):
        """
        Modify topics for thread rotation.

        The channel must of already been setup for thread rotation
        """
        current = await self.config.channel(channel).topics()
        if not current:
            await ctx.send(error("That channel has not been setup for thread rotation!"), delete_after=30)
            return

        if topics is None:
            await ctx.send(info(f"{channel.mention}'s topics:"))
            topic_msg = "Topics:\n"
            for topic, weight in current.items():
                topic_msg += f"{topic}: {weight}\n"
            await ctx.send(box(topic_msg), delete_after=300)

            return

        topics = topics.split("\n")
        parsed_topics = {}
        for topic in topics:
            topic = topic.split(":")
            try:
                if len(topic) > 2:
                    parsed_topics[":".join(topic[0:-1])] = float(topic[-1])
                else:
                    parsed_topics[topic[0]] = float(topic[-1])
            except:
                await ctx.send(
                    error(
                        "Please make sure to use the correct format, every topic and weight should be split by a `:` and the weight should be a single decimal value."
                    ),
                    delete_after=60,
                )
                return

        await self.config.channel(channel).topics.set(parsed_topics)
        await ctx.tick()

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
                        await ctx.send(error(f"Unknown channel: `{r}`, please run the command again."), delete_after=60)
                        return

                role_objs.append(role)
        else:
            role_objs = []

        await ctx.send(
            info(
                "Final step is to list the thread topics and their selection weights.\nThe weight is how likely the topic will be choosen.\nA weight of `1` means it will not be choosen more or less than other topics.\nA weight between 0 and 1 means it is that weight times less likely to be choosen, with a weight of 0 meaning it will never be choosen.\nA weight greater than 1 means it will be that times more likely to be choosen.\n\nFor example, a weight of 1.5 means that topic is 1.5 more likely to be choose over the others. A weight of 0.5 means that topic is half as likely to be choosen by others.\n\nPlease use this format for listing the weights:\n"
            ),
            delete_after=300,
        )
        await ctx.send(box("topic name: weight_value\ntopic 2 name: weight_value\ntopic 3 name: weight_value"))

        pred = MessagePredicate.same_context(ctx)
        try:
            msg = await self.bot.wait_for("message", check=pred, timeout=301)
        except asyncio.TimeoutError:
            await ctx.send(error("Took too long, cancelling setup!"), delete_after=30)
            return

        topics = msg.content.split("\n")
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
                        "Please make sure to use the correct format, every topic and weight should be split by a `:` and the weight should be a single decimal value greater than or equal to 0."
                    ),
                    delete_after=60,
                )
                return

        topic_msg = "Topics:\n"
        for topic, weight in parsed_topics.items():
            topic_msg += f"{topic}: {weight}\n"

        await ctx.send(
            info(f"Please review the settings for thread rotation on channel {channel.mention}:"), delete_after=300,
        )
        await ctx.send(
            box(
                f"Rotation interval: {humanize_timedelta(seconds=interval.total_seconds())}\n\nRotation Start: {date}\n\nPing roles: {humanize_list([r.name for r in role_objs])}"
            ),
            delete_after=300,
        )
        await ctx.send(
            box(topic_msg), delete_after=300,
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

        await ctx.send(
            info(f"Thread rotation setup! The first rotation will start at <t:{int(date.timestamp())}>"),
            delete_after=60,
        )

