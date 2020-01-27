import discord
from redbot.core import checks, commands
from redbot.core.utils.chat_formatting import *
from redbot.core import Config

import time
import random
import asyncio
import datetime
import pytz
from tzlocal import get_localzone


basic_colors = [
    discord.Colour.blue(),
    discord.Colour.teal(),
    discord.Colour.dark_teal(),
    discord.Colour.green(),
    discord.Colour.dark_green(),
    discord.Colour.dark_blue(),
    discord.Colour.purple(),
    discord.Colour.dark_purple(),
    discord.Colour.magenta(),
    discord.Colour.gold(),
    discord.Colour.orange(),
    discord.Colour.red(),
    discord.Colour.dark_red(),
    discord.Colour.blurple(),
    discord.Colour.greyple(),
]


class Events(commands.Cog):
    """
    Set events that track time since set events
    """

    def __init__(self, bot):
        super().__init__()
        self.config = Config.get_conf(self, identifier=6748392754)
        self.timezone = get_localzone()
        self.bot = bot
        # set default values
        self.config.register_guild(events={}, channel=0)

    @commands.group()
    @commands.guild_only()
    async def event(self, ctx):
        """
        Track time since event occured.
        """
        pass

    @event.command(name="add")
    async def addevent(self, ctx, start_time: str, *, event_name: str = ""):
        """
        Add event to track. If start time is not given, the current data and time is used.
        Start time should be a UNIX timestamp in UTC.
        """
        guild = ctx.guild
        channel_id = await self.config.guild(guild).channel()
        if channel_id == 0:
            await ctx.send("Channel not setup, use ``{}eventset channel` to set channel for events.".format(ctx.prefix))
            return
        channel = self.bot.get_channel(channel_id)
        if not channel:
            await ctx.send("Channel set not found, please setup channel.")
            return
        try:
            start_time = datetime.datetime.utcfromtimestamp(int(start_time))
        except:
            event_name = start_time + " " + event_name
            start_time = datetime.datetime.utcnow()

        elapsed_time = datetime.datetime.utcnow() - start_time
        embed = discord.Embed(title=event_name, colour=random.choice(basic_colors))
        embed.add_field(
            name="Event time",
            value=start_time.replace(tzinfo=pytz.utc).astimezone(self.timezone).strftime("%b %d, %Y, %H:%M"),
        )
        day_msg = "{} day{},".format(elapsed_time.days, "s" if elapsed_time.days > 1 else "")
        hour_msg = " {} hour{}".format(
            int(elapsed_time.seconds / 60 / 60), "s" if int(elapsed_time.seconds / 60 / 60) > 1 else ""
        )
        if elapsed_time.days > 0 or int(elapsed_time.seconds / 60 / 60) > 0:
            minute_msg = ", and {} minute{}".format(
                int(elapsed_time.seconds / 60 - int(elapsed_time.seconds / 60 / 60) * 60),
                "s" if int(elapsed_time.seconds / 60 - int(elapsed_time.seconds / 60 / 60) * 60) > 1 else "",
            )
        else:
            minute_msg = "{} minute{}".format(
                int(elapsed_time.seconds / 60 - int(elapsed_time.seconds / 60 / 60) * 60),
                "s" if int(elapsed_time.seconds / 60 - int(elapsed_time.seconds / 60 / 60) * 60) > 1 else "",
            )
        msg = "{}{}{}".format(
            day_msg if elapsed_time.days > 0 else "",
            hour_msg if int(elapsed_time.seconds / 60 / 60) > 0 else "",
            minute_msg,
        )
        embed.add_field(name="Elapsed time", value=msg)
        message = await channel.send(embed=embed)
        async with self.config.guild(guild).events() as events:
            new_event = {"start_time": int(start_time.replace(tzinfo=pytz.utc).timestamp()), "name": event_name}
            events[message.id] = new_event
        await ctx.send("Event added!")

    @event.command(name="del")
    async def delevent(self, ctx):
        """
        Delete an event. Interactive deletion, so just run the command.
        """
        guild = ctx.guild
        channel_id = await self.config.guild(guild).channel()
        if channel_id == 0:
            await ctx.send("Channel not setup, use `{}eventset channel` to set channel for events.".format(ctx.prefix))
            return
        channel = self.bot.get_channel(channel_id)
        if not channel:
            await ctx.send("Channel set not found, please setup channel.")
            return

        counter = 0
        msg = "```"
        async with self.config.guild(guild).events() as events:
            for num, event in events.items():
                msg += "{}\t{}\n".format(counter, event["name"])
                if len(msg + "```") + 100 > 2000:
                    msg += "```"
                    await ctx.send(msg)
                    msg = "```"
                counter += 1
            msg += "```"
            await ctx.send(msg)
            await ctx.send("Please choose which event you want to delete. (type number in chat)")

            def m_check(m):
                try:
                    return (
                        m.author.id == ctx.author.id
                        and m.channel.id == ctx.channel.id
                        and int(m.content) <= counter
                        and int(m.content) >= 0
                    )
                except:
                    return False

            try:
                response = await self.bot.wait_for("message", timeout=30, check=m_check)
            except:
                await ctx.send("Timed out, event deletion cancelled.")
                return
            for i, num in enumerate(events.keys()):
                if i == int(response.content):
                    event_num = num
            try:
                message = await channel.fetch_message(event_num)
                await message.delete()
            except:
                await ctx.send("Event message in {} was not found.".format(channel.mention))

            await ctx.send("{} has been deleted!".format(events[event_num]["name"]))
            del events[event_num]

    @event.command(name="list")
    async def listevent(self, ctx):
        """
        List all events for server.
        """
        guild = ctx.guild
        msg = "```\n"
        async with self.config.guild(guild).events() as events:
            if len(events) == 0:
                msg += "None"
            for num, event in events.items():
                msg += "{}\n".format(event["name"])
                if len(msg + "```") + 3 > 2000:
                    msg += "```"
                    await ctx.send(msg)
                    msg = "```"

        msg += "```"
        await ctx.send(msg)

    @commands.group()
    @commands.guild_only()
    @checks.admin_or_permissions(administrator=True)
    async def eventset(self, ctx: commands.Context):
        """Manages event settings"""
        pass

    @eventset.command(name="channel")
    async def _channel_set(self, ctx, channel: discord.TextChannel):
        """
        Set channel to send event messages too
        """
        guild = ctx.guild
        await self.config.guild(guild).channel.set(channel.id)
        await ctx.send("Channel now set to {}".format(channel.mention))

    async def update_events(self):
        while True:
            if self is not self.bot.get_cog("Events"):
                print("events cog has been lost")
                return
            guilds = self.bot.guilds
            for guild in guilds:
                async with self.config.guild(guild).events() as events:
                    channel_id = await self.config.guild(guild).channel()
                    if channel_id == 0:
                        continue
                    channel = self.bot.get_channel(channel_id)
                    if channel is None:
                        continue
                    for message_id, event in events.items():
                        try:
                            message = await channel.fetch_message(message_id)
                        except:
                            continue
                        start_time = datetime.datetime.utcfromtimestamp(event["start_time"])
                        elapsed_time = datetime.datetime.utcnow() - start_time
                        embed = message.embeds[0]
                        embed.clear_fields()
                        embed.add_field(
                            name="Event time",
                            value=start_time.replace(tzinfo=pytz.utc)
                            .astimezone(self.timezone)
                            .strftime("%b %d, %Y, %H:%M"),
                        )
                        day_msg = "{} day{},".format(elapsed_time.days, "s" if elapsed_time.days > 1 else "")
                        hour_msg = " {} hour{}".format(
                            int(elapsed_time.seconds / 60 / 60), "s" if int(elapsed_time.seconds / 60 / 60) > 1 else ""
                        )
                        if elapsed_time.days > 0 or int(elapsed_time.seconds / 60 / 60) > 0:
                            minute_msg = ", and {} minute{}".format(
                                int(elapsed_time.seconds / 60 - int(elapsed_time.seconds / 60 / 60) * 60),
                                "s"
                                if int(elapsed_time.seconds / 60 - int(elapsed_time.seconds / 60 / 60) * 60) > 1
                                else "",
                            )
                        else:
                            minute_msg = "{} minute{}".format(
                                int(elapsed_time.seconds / 60 - int(elapsed_time.seconds / 60 / 60) * 60),
                                "s"
                                if int(elapsed_time.seconds / 60 - int(elapsed_time.seconds / 60 / 60) * 60) > 1
                                else "",
                            )
                        msg = "{}{}{}".format(
                            day_msg if elapsed_time.days > 0 else "",
                            hour_msg if int(elapsed_time.seconds / 60 / 60) > 0 else "",
                            minute_msg,
                        )
                        embed.add_field(name="Elapsed time", value=msg)
                        await message.edit(embed=embed)
            await asyncio.sleep(30)
