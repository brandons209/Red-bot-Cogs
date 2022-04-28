from redbot.core import commands, checks, Config
from redbot.core.utils.chat_formatting import *
from redbot.core.data_manager import cog_data_path

from aitextgen import aitextgen

from typing import Literal
from datetime import datetime, timedelta
import asyncio, os, time, random


class Chatbot(commands.Cog):
    """
    Chatbot using aitextgen model.
    """

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=156613221365446546, force_registration=True)

        default_guild = {
            "temp": 0.9,
            "max_len": 2,
            "history": 10,
            "max_time": 1500,
            "dead_channels": [],
            "dead_revive_time": 3000,
        }
        default_channel = {"autoreply": False, "randomness": 0.25, "timeout": 1500}
        default_global = {"use_gpu": False, "autoboot": False}

        self.config.register_guild(**default_guild)
        self.config.register_channel(**default_channel)
        self.config.register_global(**default_global)
        # TODO add settings cache

        self.model = None
        # maps channel -> datetime of last message for autoreply channels
        self.talking_channels = {}
        # maps channel -> last history number of messages objects
        self.history = {}
        # when generating for a channel, ignore new messages
        self.channel_lock = []
        self.special_tokens = {
            "end_convo": "<end_convo>",
            "start_convo": "<start_convo>",
        }
        self.init_task = asyncio.create_task(self.init())
        self.loop = asyncio.get_event_loop()
        os.environ["TOKENIZERS_PARALLELISM"] = "true"

    async def load_model(self):
        root = cog_data_path(cog_instance=self)
        model_path = os.path.join(root, "pytorch_model.bin")
        config_path = os.path.join(root, "config.json")
        if os.path.isfile(model_path) and os.path.isfile(config_path):
            use_gpu = await self.config.use_gpu()
            self.model = aitextgen(model_folder=root, use_gpu=use_gpu)
        else:
            await self.bot.send_to_owners(
                error(
                    "Your model for cog `chatbot` could not be found. Make sure to have two files, `pytorch_model.bin` and `config.json` in the cog's data directory."
                )
            )

    async def init(self):
        if await self.config.autoboot():
            await self.load_model()

        while True:
            for guild in self.bot.guilds:
                if await self.bot.cog_disabled_in_guild(self, guild):
                    continue
                dead = await self.config.guild(guild).dead_channels()
                dead_time = await self.config.guild(guild).dead_revive_time()
                for id in dead:
                    channel = guild.get_channel(id)
                    if not channel:
                        continue

                    last_msg = None
                    async for msg in channel.history(limit=1):
                        last_msg = msg

                    now = datetime.utcnow()
                    if (now - last_msg.created_at).total_seconds() < dead_time:
                        continue

                    max_len = await self.config.guild(guild).max_len()
                    temp = await self.config.guild(guild).temp()
                    context = ""
                    if channel in self.history:
                        for msg in self.history[channel]:
                            context += msg.clean_content.strip() + "\n"

                    output = self.get_ai_response(context, max_len, temp)
                    await channel.send(output)

            await asyncio.sleep(60)

    def cog_unload(self):
        if self.init_task:
            self.init_task.cancel()

    async def timed_wait(self, message: discord.Message):
        """
        Helper function for boot sequence
        """
        loops = random.randint(2, 3)
        loading = ["|", "/", "-", "\\"]
        content = message.content
        for _ in range(loops):
            for l in loading:
                await message.edit(content=f"{content}\n{l}")
                await asyncio.sleep(0.5)

        await message.edit(content=content)

    @commands.group(name="ai")
    @commands.guild_only()
    @checks.admin()
    async def ai(self, ctx):
        """
        Manage your Chatbot
        """
        pass

    @ai.command(name="gpu")
    @checks.is_owner()
    async def ai_gpu(self, ctx, use_gpu: bool):
        """
        Turn on GPU for model loading

        Make sure to have GPU version of PyTorch installed, along with CUDA toolkit.
        """
        await self.config.use_gpu.set(use_gpu)
        await ctx.tick()

    @ai.command(name="boot")
    @checks.is_owner()
    async def ai_boot(self, ctx, lets_boot: bool):
        """
        Load the model and set it to load on startup
        """
        await self.load_model()
        await self.config.autoboot.set(True)

        txt = "-----SYSTEM STARTUP-----\n"
        msg = await ctx.send(txt)
        await self.timed_wait(msg)

        txt += "KERNEL LOADED\nHARDWARE OK\n\n"
        await msg.edit(content=txt)
        await self.timed_wait(msg)

        txt += "-----LAUNCHING SYSTEMS-----\nCORE ANALYTICS\nHEURISTIC ENGINES\n"
        await msg.edit(content=txt)
        await self.timed_wait(msg)

        txt += "RECURSION PROCESSORS\nEVOLUTIONARY GENERATORS\nCOMPUTATIONAL LINGUISTICS\n"
        await msg.edit(content=txt)
        await self.timed_wait(msg)

        txt += "NATURAL LANGUAGE PROCESSING\nPATTERN MINING\nERROR HANDLING\n"
        await msg.edit(content=txt)
        await self.timed_wait(msg)

        txt += "ALGORITHMIC ENGINES\nAUTONOMOUS IMPROVEMENT\n"
        await msg.edit(content=txt)
        await self.timed_wait(msg)

        txt += "IMAGE PROCESSING\nCONTEXT ENGINE\n"
        await msg.edit(content=txt)
        await self.timed_wait(msg)

        txt += "-----CORE SYSTEMS ONLINE-----\n\n-----PERFORMING SELF DIAGNOSTICS-----\n"
        await msg.edit(content=txt)
        await self.timed_wait(msg)

        txt += "**[OK]** CORE HEURISTICS\n**[OK]** ADVANCED PATTERN RECOGNITION\n"
        await msg.edit(content=txt)
        await self.timed_wait(msg)

        txt += "**[SUCESSFUL]** NATURAL LANGUAGE PROCESSING TESTS\n**[SUCESSFUL]** CONTEXTUALIZATION TESTS\n"
        await msg.edit(content=txt)
        await self.timed_wait(msg)

        txt += "**[SUCESSFUL]** SYSTEMS INTERGRATION TEST\n\n"
        await msg.edit(content=txt)
        await self.timed_wait(msg)

        txt += f"**STARTUP COMPLETE**\n\n{ctx.guild.me.mention} v4.2.3 online and functioning."
        await msg.edit(content=txt)

    @ai.group(name="channel")
    async def ai_channel(self, ctx):
        """
        Manage channel settings
        """
        pass

    @ai_channel.group(name="revive")
    async def ai_channel_revive(self, ctx):
        """
        Dead chat reviver settings
        """
        pass

    @ai_channel_revive.command(name="time")
    async def ai_channel_revive_time(self, ctx, time: int):
        """
        Set the time for chat to be dead to revive it in seconds
        """
        await self.config.guild(ctx.guild).dead_revive_time.set(time)
        await ctx.tick()

    @ai_channel_revive.command("add")
    async def ai_channel_revive_add(self, ctx, *, channel: discord.TextChannel):
        """
        Add a channel to revive when dead
        """
        async with self.config.guild(ctx.guild).dead_channels() as dead:
            if channel.id not in dead:
                dead.append(channel.id)

        await ctx.tick()

    @ai_channel_revive.command("del")
    async def ai_channel_revive_del(self, ctx, *, channel: discord.TextChannel):
        """
        Delete a channel from the revive list
        """
        async with self.config.guild(ctx.guild).dead_channels() as dead:
            try:
                dead.remove(channel.id)
            except:
                pass

        await ctx.tick()

    @ai_channel_revive.command("list")
    async def ai_channel_revive_list(self, ctx):
        """
        List revive channels
        """
        msg = "**Revive Channel List:**\n"
        async with self.config.guild(ctx.guild).dead_channels() as dead:
            msg += "\n".join(
                [ctx.guild.get_channel(c).mention if ctx.guild.get_channel(c) is not None else "" for c in dead]
            )

        for page in pagify(msg):
            await ctx.send(page)

    @ai_channel.command(name="autoreply")
    async def ai_channel_reply(self, ctx, channel: discord.TextChannel, on_off: bool):
        """
        Turn on autoreply in channel
        """
        await self.config.channel(channel).autoreply.set(on_off)
        await ctx.tick()

    @ai_channel.command(name="random")
    async def ai_channel_random(self, ctx, channel: discord.TextChannel, randomness: float):
        """
        Set the percent chance for the bot to reply in channel

        Value should be between 0 and 1

        Setting it to 1 will mean it always reply to each message
        """
        await self.config.channel(channel).randomness.set(randomness)
        await ctx.tick()

    @ai_channel.command(name="timeout")
    async def ai_channel_timeout(self, ctx, channel: discord.TextChannel, timeout: int):
        """
        Number of seconds for bot to stop replying to messages, **in seconds**

        Occurs once no new messages are sent for this time period in the channel.
        """
        await self.config.channel(channel).timeout.set(timeout)
        await ctx.tick()

    @ai.group(name="model")
    async def ai_model(self, ctx):
        """
        Manage model settings
        """
        pass

    @ai_model.command(name="settings")
    async def ai_model_settings(self, ctx):
        """
        View model settings
        """
        settings = await self.config.guild(ctx.guild).all()

        msg = f"Temperature: {settings['temp']}\nHistory # Messages: {settings['history']}\n Max Output Lines: {settings['max_len']}\nMax History Time: {settings['max_time']} seconds"
        embed = discord.Embed(colour=ctx.guild.me.colour, description=msg, title=f"Settings for {ctx.guild}")
        await ctx.send(embed=embed)

    @ai_model.command(name="temp")
    async def ai_model_temp(self, ctx, temp: float):
        """
        Change temperature of output generation

        Higher temperature means more variation in output, lower temperature is more deterministic.
        Mess with this between 0 and 1 to see what works best.
        """
        await self.config.guild(ctx.guild).temp.set(temp)
        await ctx.tick()

    @ai_model.command(name="history")
    async def ai_model_history(self, ctx, history: int):
        """
        Change history length of model

        History is the number of messages to consider as context when generating output, lower history is less context.
        """
        await self.config.guild(ctx.guild).history.set(history)
        await ctx.tick()

    @ai_model.command(name="time")
    async def ai_model_time(self, ctx, history_time: int):
        """
        Change time limit of history messages, in seconds

        This means to only consider messages as history within this time limit
        Messages outside of this time won't be considered in generation
        """
        await self.config.guild(ctx.guild).max_time.set(history_time)
        await ctx.tick()

    @ai_model.command(name="lines")
    async def ai_model_lines(self, ctx, lines: int):
        """
        Change maximum number of output lines to generated

        It's good to keep to relatively small.
        """
        await self.config.guild(ctx.guild).max_len.set(lines)
        await ctx.tick()

    @ai.command(
        name="data",
        usage="<days of data> <max time of convo in seconds> <min number of lines in convo> <include links> [list of channels]",
    )
    @checks.is_owner()
    async def ai_data(
        self, ctx, lookback: int, maxtime: int, minlines: int, include_links: bool, *channels: discord.TextChannel
    ):
        """
        Gather data from channels for training

        **Use -1 for <days of data> to get ALL messages in channels**

        **WARNING** this will take a long time!
        Training data will be saved to the cog's data directory.

        Maxtime is the maximum number of seconds between messages before considering it a new conversation.
        Minlines is the mininum number of messages in a conversation to keep the conversation in the training data.

        Please see the training repo here: https://github.com/brandons209/AI-Chatbot
        """
        if lookback > 0:
            after = datetime.utcnow() - timedelta(days=lookback)
        else:
            after = None

        data = []
        prefix = ctx.clean_prefix
        status_msg = await ctx.send(f"Processing 1/{len(channels)} channels (this may take a while)")
        for i, channel in enumerate(channels):
            try:
                await status_msg.edit(content=f"Processing {i+1}/{len(channels)} channels (this may take a while)")
            except:
                status_msg = await ctx.send(f"Processing {i+1}/{len(channels)} channels (this may take a while)")

            prev_msg = None
            try:
                async for msg in channel.history(limit=None, after=after, oldest_first=True):
                    if (
                        len(msg.clean_content) < 1
                        or msg.author.bot
                        or msg.clean_content[: len(prefix)] == prefix
                        or ("http" in msg.clean_content and not include_links)
                    ):
                        continue

                    if prev_msg is not None and (msg.created_at - prev_msg.created_at).total_seconds() > maxtime:
                        data.append(self.special_tokens["end_convo"])
                        data.append(self.special_tokens["start_convo"])
                    elif prev_msg is None:
                        data.append(self.special_tokens["start_convo"])

                    data.append(msg.clean_content.strip())
                    prev_msg = msg

                if data and data[-1] != self.special_tokens["end_convo"]:
                    data.append(self.special_tokens["end_convo"])
            except Exception as e:
                await ctx.send(f"Error processing channel {channel.mention}: {e}")

        # filter out short conversations
        try:
            await status_msg.edit(content="Cleaning data...")
        except:
            status_msg = await ctx.send("Cleaning data...")
        start = 0
        to_delete = []
        for i in range(len(data)):
            if data[i] == self.special_tokens["start_convo"]:
                start = i
                continue

            if data[i] == self.special_tokens["end_convo"] and (i - start) < minlines:
                to_delete.extend([j for j in range(start, i + 1)])

        data = [l for i, l in enumerate(data) if i not in to_delete]

        with open(os.path.join(cog_data_path(cog_instance=self), f"{ctx.guild.id}-cleaned.txt"), "w") as f:
            f.write("\n".join(data))

        try:
            await status_msg.edit(content=info("Done. Saved to the cog's data path."))
        except:
            await ctx.send(info("Done. Saved to the cog's data path."))

    def process_input(self, message: str) -> str:
        """
        Process the input message

        Args:
            message (str): The message to process
        """
        # Remove bot's @s from input
        processed_input = message.replace(("<@!" + str(self.bot.user.id) + ">"), "").strip()
        processed_input = message.replace(str(self.bot.user), "").strip()
        print(processed_input)

        # strip spaces at beginning of text
        processed_input = "\n".join([s.strip() for s in processed_input.split("\n")])

        return processed_input

    def get_ai_response(self, message: str, max_len: int, temp: float):
        """
        Get a response from the model up to max length

        Args:
            message (str): The message to use for generation
            max_len (int): Maximum number of lines to generate
            temp (float): Model generation temperature
        """
        numtokens = len(self.model.tokenizer(message)["input_ids"])
        if numtokens >= 1000:
            while numtokens >= 1000:
                message = " ".join(message.split(" ")[20:]).strip()  # pretty arbitrary
                numtokens = len(self.model.tokenizer(message)["input_ids"])

        output = ""
        i = 0  # in case of inf loop, three tries to generate a non-empty messages TODO: make configurable
        while output == "" and i < 3:
            text = self.model.generate(
                max_length=numtokens + 70 + 5 * max_len,
                prompt=message + "\n",
                temperature=temp,
                return_as_list=True,
            )[0]
            text = (
                text[len(message) :]
                .replace(self.special_tokens["end_convo"], "")
                .replace(self.special_tokens["start_convo"], "")
                .strip()
            )  # remove the input text from the output text

            j = 0
            while output == "" and j < 100:  # TODO configure this too?
                for i in range(
                    0, random.randint(1, max_len)
                ):  # include a random amount of lines up to maxlines in the response
                    try:
                        output += text.splitlines()[i + 1] + "\n"
                    except:
                        continue

                output = output.strip()
                j += 1

            i += 1

        if output == "":
            # fill with default message if still empty
            output = "🤔"

        return output

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        if await self.bot.cog_disabled_in_guild(self, message.guild):
            return
        if message.channel in self.history:
            try:
                self.history[message.channel].remove(message)
            except:
                pass

        print(self.history[message.channel])

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if await self.bot.cog_disabled_in_guild(self, message.guild):
            return
        if not self.model and (await self.config.autoboot()):
            await self.bot.send_to_owners(
                error(
                    "Your model for cog `chatbot` could not be found. Make sure to have two files, `pytorch_model.bin` and `config.json` in the cog's data directory."
                )
            )
            return

        start = time.time()
        author = message.author
        guild = message.guild
        channel = message.channel
        ref = message.reference
        ctx = await self.bot.get_context(message)

        if len(message.content) < 1 or guild is None or ctx.prefix is not None or author.bot:  # or author == guild.me
            return

        if not channel in self.history:
            self.history[channel] = []

        self.history[channel].append(message)
        print(self.channel_lock)
        if channel in self.channel_lock:
            return

        ref_message = ref.resolved if ref else None
        ref_message = await channel.fetch_message(ref.message_id) if ref_message is not None else ref_message
        autoreply = await self.config.channel(channel).autoreply()
        ran_chat = False
        # if bot wasnt mentioned, replied too, or talking in a channel
        if not (
            guild.me in message.mentions
            or (
                self.talking_channels.get(channel, None) is not None
                and (datetime.utcnow() - self.talking_channels[channel]).total_seconds()
                < (await self.config.channel(channel).timeout())
            )
            or (ref_message is not None and ref_message.author == guild.me)
        ):
            # if not any of that, see if this is a auto channel and check random
            if not autoreply or random.random() > (await self.config.channel(channel).randomness()):
                try:
                    del self.talking_channels[channel]
                except:
                    pass
                return
            else:
                ran_chat = True

        if ran_chat:
            self.talking_channels[channel] = message.created_at

        print(f"checks: {time.time() - start}")
        start = time.time()
        self.channel_lock.append(channel)
        async with channel.typing():
            history_len = await self.config.guild(guild).history()
            max_time = await self.config.guild(guild).max_time()
            max_len = await self.config.guild(guild).max_len()
            temp = await self.config.guild(guild).temp()

            print(f"history: {time.time() - start}")
            start = time.time()
            context = ""
            # remove old messages
            self.history[channel] = self.history[channel][-1 * history_len :]
            for msg in self.history[channel]:
                if (datetime.utcnow() - msg.created_at).total_seconds() < max_time:
                    context += msg.clean_content.strip() + "\n"

            # probably-stupid way of making every line but the last have a newline after it
            context = context.rstrip(context[-1]).strip()

            context = self.process_input(context)
            if not context:
                return

            print(f"process context: {time.time() - start}")
            start = time.time()

            response = await self.loop.run_in_executor(None, self.get_ai_response, context, max_len, temp)

            print(f"response: {time.time() - start}")

            try:
                self.channel_lock.remove(channel)
            except ValueError:
                pass
            print(self.channel_lock)
            return await message.reply(response, mention_author=False)

    async def red_delete_data_for_user(
        self,
        *,
        requester: Literal["discord_deleted_user", "owner", "user", "user_strict"],
        user_id: int,
    ):
        pass
