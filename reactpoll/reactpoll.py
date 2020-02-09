from redbot.core.utils.chat_formatting import *
from redbot.core.utils.mod import is_mod_or_superior
from redbot.core import Config, checks, commands, modlog
import discord

import discord
import asyncio
import re
import time
from datetime import datetime, timedelta
from .time_utils import *

# May need to not save on every reaction add if it causes too much lag


class ReactPoll(commands.Cog):

    """Create polls using emoji reactions"""

    def __init__(self, bot):
        super().__init__()
        self.bot = bot
        self.poll_sessions = {}
        self.config = Config.get_conf(self, identifier=9675846083, force_registration=True)
        self.config.register_global(poll_sessions={})

        self.loop = asyncio.get_event_loop()
        self.loop.create_task(self.load_polls())
        self.poll_task = self.loop.create_task(self.poll_closer())

    async def poll_closer(self):
        while True:
            await asyncio.sleep(5)
            now_time = time.time()
            for poll in self.poll_sessions.values():
                if poll.end_time <= now_time:
                    await poll.endPoll()
                    await self.delete_poll(poll)

    async def delete_poll(self, poll):
        async with self.config.poll_sessions() as polls:
            try:
                del polls[str(poll.channel.id)]
            except:
                pass

    async def store_poll(self, poll):
        async with self.config.poll_sessions() as polls:
            polls[str(poll.channel.id)] = poll.as_dict()

    async def load_polls(self):
        await self.bot.wait_until_ready()
        polls = await self.config.poll_sessions()
        if not polls:
            await self.config.poll_sessions.set({})
            return
        else:
            for poll in polls.values():
                load_poll = LoadedPoll(self, poll)
                load_poll.message = await load_poll.channel.fetch_message(load_poll.message)
                if load_poll.valid:
                    self.poll_sessions[str(load_poll.channel.id)] = load_poll
                else:
                    await self.delete_poll(load_poll)

    @commands.command()
    @commands.guild_only()
    @checks.bot_has_permissions(manage_messages=True)
    async def rpoll(self, ctx, *text):
        """Starts/stops a reaction poll
        Usage example (time argument is optional)
        [p]rpoll question;option1;option2...;t=<date to end on or time duration>
        [p]rpoll stop

        Durations look like (must be greater than 10 seconds):
           15s
           5 minutes
           1 minute 30 seconds
           1 hour
           2 days
           5h30m

        times look like:
           February 14 at 6pm EDT
           2019-04-13 06:43:00 PST
           01/20/18 at 21:00:43

       times default to UTC if no timezone provided.
        """
        message = ctx.message
        channel = message.channel
        guild = message.guild
        if len(text) == 1:
            if text[0].lower() == "stop":
                await self.endpoll(message, ctx)
                return
        if not self.getPollByChannel(message):
            p = NewReactPoll(message=message, text=escape(" ".join(text), mass_mentions=True), main=self)
            if p.valid:
                self.poll_sessions[str(channel.id)] = p
                await p.start()
                await self.store_poll(p)
            else:
                await ctx.send_help()
        else:
            await ctx.send("A reaction poll is already ongoing in this channel.")

    async def endpoll(self, message, ctx):
        if self.getPollByChannel(message):
            p = self.getPollByChannel(message)
            if p.author == message.author.id or is_mod_or_superior(self.bot, message.author):
                await p.endPoll()
            else:
                await ctx.send("Only admins and the author can stop the poll.")
        else:
            await ctx.send("There's no reaction poll ongoing in this channel.")

    def getPollByChannel(self, message):
        try:
            return self.poll_sessions[str(message.channel.id)]
        except KeyError:
            return False

    async def check_poll_votes(self, message):
        if message.author.id != self.bot.user.id:
            if self.getPollByChannel(message):
                self.getPollByChannel(message).checkAnswer(message)

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload):
        # parse payload
        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            return
        user = guild.get_member(payload.user_id)
        message = await self.bot.get_channel(payload.channel_id).fetch_message(payload.message_id)
        # Listener is required to remove bad reactions
        if user == self.bot.user or not guild:
            return  # Don't remove bot's own reactions

        emoji = payload.emoji
        p = self.getPollByChannel(message)
        if p:
            if message.id == p.message.id and emoji.is_unicode_emoji() and emoji.name in p.emojis:
                # Valid reaction
                if str(user.id) not in p.already_voted:
                    # First vote
                    p.already_voted[str(user.id)] = str(emoji)
                else:
                    # Allow subsequent vote but remove the previous
                    await message.remove_reaction(p.already_voted[str(user.id)], user)
                    p.already_voted[str(user.id)] = str(emoji)
                await self.store_poll(p)
                return
            # remove any other reaction emojis that arent valid
            elif message.id == p.message.id and (emoji.is_custom_emoji() or emoji.name not in p.emojis):
                await message.remove_reaction(emoji, user)

    def cog_unload(self):
        self.poll_task.cancel()


class NewReactPoll:
    def __init__(self, message=None, text=None, main=None):
        self.channel = message.channel
        self.author = message.author.id
        self.client = main.bot
        self.main = main
        self.poll_sessions = main.poll_sessions
        self.duration = 60  # Default duration
        msg = [ans.strip() for ans in text.split(";")]
        # Detect optional duration parameter
        if len(msg[-1].strip().split("t=")) == 2:
            dur_s = msg[-1].strip().split("t=")[1]
            dur = parse_timedelta(dur_s)
            if not dur:
                try:
                    dur = parse_time(dur_s) - datetime.utcnow()
                except:
                    dur = None
            if dur and dur.total_seconds() > 5:
                self.duration = int(dur.total_seconds())
            else:
                self.duration = 60
            msg.pop()
        else:
            self.duration = 60
        # Reaction poll supports maximum of 9 answers and minimum of 2
        if len(msg) < 2 or len(msg) > 10:
            self.valid = False
            return None
        else:
            self.valid = True

        self.end_time = time.time() + self.duration
        self.already_voted = {}
        self.question = msg[0]
        msg.remove(self.question)
        self.answers = {}  # Made this a dict to make my life easier for now
        self.emojis = []
        i = 1
        # Starting codepoint for keycap number emojis (\u0030... == 0)
        base_emoji = [ord("\u0030"), ord("\u20E3")]
        for answer in msg:  # {id : {answer, votes}}
            base_emoji[0] += 1
            self.emojis.append(chr(base_emoji[0]) + chr(base_emoji[1]))
            answer = self.emojis[i - 1] + " " + answer
            self.answers[str(i)] = {"ANSWER": answer, "VOTES": 0}
            i += 1
        self.message = None

    def as_dict(self):
        return {
            "author": self.author,
            "channel": self.channel.id,
            "message": self.message.id,
            "question": self.question,
            "answers": self.answers,
            "emojis": self.emojis,
            "end_time": self.end_time,
            "already_voted": self.already_voted,
        }

    async def start(self):
        msg = "**POLL STARTED!**\n\n{}\n\n".format(self.question)
        for id, data in self.answers.items():
            msg += "{}\n".format(data["ANSWER"])

        end_time = datetime.utcnow() + timedelta(seconds=self.duration)
        if self.duration // 60 < 1:  # less than a minute
            conj = "in"
            dur = int(self.duration)
            unit = "seconds"
        elif self.duration // 60 >= 1 and self.duration // 3600 < 1:  # between 1 minute and 1 hour
            conj = "in"
            dur = int(self.duration // 60)
            unit = "minutes" if self.duration // 60 > 1 else "minute"
        elif self.duration // 3600 >= 1 and self.duration // 86400 < 1:  # 1 hour and 1 day
            conj = "in"
            dur = int(self.duration // 3600)
            unit = "hours" if self.duration // 3600 > 1 else "hour"
        elif self.duration // 86400 == 1:
            conj = "in"
            dur = 1
            unit = "day"
        else:
            conj = "on"
            dur = str(self.end_time.strftime("%m/%d/%Y at %I:%M%p") + " UTC")
            unit = ""

        msg += "\nSelect the number to vote!" "\nPoll closes {} {} {}.".format(conj, dur, unit)
        self.message = await self.channel.send(msg)
        for emoji in self.emojis:
            await self.message.add_reaction(emoji)
            await asyncio.sleep(0.5)

    async def endPoll(self):
        self.valid = False

        # Need a fresh message object
        self.message = await self.channel.fetch_message(self.message.id)
        msg = "**POLL ENDED!**\n\n{}\n\n".format(self.question)
        for reaction in self.message.reactions:
            if reaction.emoji in self.emojis:
                self.answers[str(ord(reaction.emoji[0]) - 48)]["VOTES"] = reaction.count - 1
        await self.message.clear_reactions()
        cur_max = 0  # Track the winning number of votes
        # Double iteration probably not the fastest way, but works for now
        for data in self.answers.values():
            if data["VOTES"] > cur_max:
                cur_max = data["VOTES"]
        for data in self.answers.values():
            if cur_max > 0 and data["VOTES"] == cur_max:
                msg += "**{} - {} votes**\n".format(data["ANSWER"], str(data["VOTES"]))
            else:
                msg += "*{}* - {} votes\n".format(data["ANSWER"], str(data["VOTES"]))
        await self.channel.send(msg)
        del self.poll_sessions[str(self.channel.id)]
        await self.main.delete_poll(self)


class LoadedPoll(NewReactPoll):
    """A reaction poll loaded from disk"""

    def __init__(self, main, data):
        self.main = main
        self.client = main.bot
        self.poll_sessions = main.poll_sessions
        self.author = data["author"]
        self.channel = self.client.get_channel(data["channel"])
        self.message = data["message"]
        self.question = data["question"]
        self.answers = data["answers"]
        self.emojis = data["emojis"]
        self.end_time = data["end_time"]
        self.already_voted = data["already_voted"]
        if self.end_time <= time.time():
            self.valid = False
        else:
            self.valid = True
