import asyncio
import discord
import random
from datetime import datetime, timedelta
from typing import Optional, Literal

from redbot.core import Config, checks, commands
from redbot.core.utils.chat_formatting import *
from redbot.core.utils.predicates import MessagePredicate

from .discord_thread_feature import *
from .time_utils import *


class ThreadRotate(commands.Cog):
    """
    Rotate threads for events, roleplay, etc
    """

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=45612361654894681623, force_registration=True)

        default_channel = {
            "topics": {},
            "ping_roles": [],
            "rotation_interval": 10080,
            "rotate_on": None,
            "last_topic": None,
        }
        self.config.register_channel(**default_channel)

    @commands.group(name="rotate")
    @commands.guild_only()
    @checks.admin()
    async def thread_rotate(self, ctx):
        """
        Manage thread rotations per channel
        """
        pass

    @thread_rotate.command(name="setup")
    async def thread_rotate_setup(self, ctx, channel: discord.TextChannel):
        """
        Interactively setup a thread rotation for a channel
        """
        guild = ctx.guild
        await ctx.send(
            info(
                "Welcome to the thread rotation setup wizard!\n\nFirst, please specifiy the rotation interval. Rotation intervals can be formatted as follows:\n\t5 minutes\n\t1 minute 30 seconds\n\t1 hour\n\t2 days\n\t30 days\n\t5h30m\n\t(etc)"
            )
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
            )
        )

        pred = MessagePredicate.same_context(ctx)
        try:
            msg = await self.bot.wait_for("message", check=pred, timeout=121)
        except asyncio.TimeoutError:
            await ctx.send(error("Took too long, cancelling setup!"), delete_after=30)
            return

        date = parse_time(msg.content.strip())
        if date is None:
            await ctx.send(error("Invalid date, please run setup again!"), delete_after=60)
            return

        await ctx.send(
            info(
                "Great, next step is to list all roles that should be pinged and added to each thread when it rotates.\n\nList each role **seperated by a comma `,`**.\nYou can use role IDs, role mentions, or role names."
            )
        )

        pred = MessagePredicate.same_context(ctx)
        try:
            msg = await self.bot.wait_for("message", check=pred, timeout=241)
        except asyncio.TimeoutError:
            await ctx.send(error("Took too long, cancelling setup!"), delete_after=30)
            return

        roles = [m.strip().strip("<").strip(">").strip("@").strip("&") for m in msg.content.split(",")]
        role_objs = []
        for r in roles:
            try:
                role = guild.get_role(int(r))
            except:
                role = discord.utils.find(lambda c: c.name == r, guild.roles)
                if role is None:
                    await ctx.send(error(f"Unknown channel: `{r}`, please run the command again."))
                    return

            role_objs.append(channel)

        await ctx.send(
            info(
                "Final step is to list the thread topics and their selection weights.\nThe weight is how likely the topic will be choosen.\nA weight of `1` means it will not be choosen more or less than other topics.\nA weight between 0 and 1 means it is that weight times less likely to be choosen, with a weight of 0 meaning it will never be choosen.\nA weight greater than 1 means it will be that times more likely to be choosen.\n\nFor example, a weight of 1.5 means that topic is 1.5 more likely to be choose over the others. A weight of 0.5 means that topic is half as likely to be choosen by others.\n\nPlease use this format for listing the weights:\n"
            )
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
        # TODO error checking
        for topic in topics:
            topic = topic.split(":")
            parsed_topics[topic[0]] = float(topic[1])

        await ctx.send(info(f"Please review the settings for thread rotation on channel {channel.mention}"))
