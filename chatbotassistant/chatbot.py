from redbot.core import commands, checks, Config
from redbot.core.utils.chat_formatting import *
from redbot.core.data_manager import cog_data_path
from redbot.core.utils.predicates import MessagePredicate
from redbot.core.utils.menus import menu, DEFAULT_CONTROLS, start_adding_reactions
from redbot.core.commands.converter import parse_timedelta
import discord
import emoji

from .model_apis.openai_api import OpenAIModel
from .model_apis.api import GeneralAPI
from .model_apis.ollama_api import OllamaModel
from .menus import ConfigSelectView, ConfigMenuView
from .rag import RagDatabase, generate_unique_id, get_metadata_format
from .prompts import (
    CHAT_PROMPT,
    GOODBYE_PROMPT,
    WELCOME_PROMPT,
    SUMMARIZE_PROMPT,
    TLDR_PROMPT,
    ANALYZE_EMOJI_PROMPT,
    DAD_JOKE_PROMPT,
    COMPLIMENT_PROMPT,
    USER_LEARNING_PROMPT,
    GENERAL_QUERY_PROMPT,
    PARTIAL_SUMMARY_PROMPT,
)

from typing import Literal, List, Union, Dict, Optional, Tuple, Any
from dateutil import parser
from datetime import datetime, timedelta
from collections import defaultdict, deque
import asyncio, os, random, csv
from io import StringIO
import json, re

MAX_USER_HISTORY_QUEUE = 500
QA_EMOJIS = ["👍", "👎"]


# helper for string formatting
class SafeFormat(dict):
    def __missing__(self, key):
        return "{" + key + "}"


class ChatbotAssistant(commands.Cog):
    """
    Chatbot using ollama and openai compatiable models.
    """

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=156613221446546, force_registration=True)
        self.path = cog_data_path(self)
        default_guild = {
            "max_time": 1500,
            "timeout": 1500,
            "timeout_cooldown": 300,
            "dead_channels": [],
            "dead_revive_time": 3000,
            "welcomes": True,
            "learning_blacklist": [],
            "user_learning_max_time": 0,
        }
        self.default_channel = {
            "autoreply": False,
            "randomness": 0.0,
            "timeout": 0,
            "chat_prompts": [],
        }
        self.default_global = {
            "model_stats": {
                "chatbot": {
                    "total_response_time": 0,
                    "num_responses": 0,
                    "prompt_eval_count": 0,
                    "prompt_eval_duration": 0,
                },
                "summarize": {
                    "total_response_time": 0,
                    "num_responses": 0,
                    "prompt_eval_count": 0,
                    "prompt_eval_duration": 0,
                },
                "general": {
                    "total_response_time": 0,
                    "num_responses": 0,
                    "prompt_eval_count": 0,
                    "prompt_eval_duration": 0,
                },
            },
            "chat_prompt": CHAT_PROMPT,
            "other_chat_prompts": {"goodbye": [GOODBYE_PROMPT], "welcome": [WELCOME_PROMPT]},
            "summarize_prompt": SUMMARIZE_PROMPT,
            "partial_summary_prompt": PARTIAL_SUMMARY_PROMPT,
            "tldr_prompt": TLDR_PROMPT,
            "emoji_prompt": ANALYZE_EMOJI_PROMPT,
            "dadjoke_prompt": DAD_JOKE_PROMPT,
            "compliment_prompt": COMPLIMENT_PROMPT,
            "general_query_prompt": GENERAL_QUERY_PROMPT,
            "user_learning_prompt": USER_LEARNING_PROMPT,
            "chatbot_model_config": {
                "type": "ollama",
                "api_key": "",
                "base_url": "http://localhost:11434",
                "model": "gemma3:4b",
                "temperature": 1.0,
                "top_p": 0.95,
                "min_p": 0.00,
                "top_k": 64,
                "num_ctx": 20000,
                "num_predict": 256,
                "repeat_penalty": 1.0,
                "presence_penalty": 1.2,
                "reasoning_effort": "medium",
                "keep_alive": -1,
            },
            "summarize_model_config": {
                "type": "ollama",
                "api_key": "",
                "base_url": "http://localhost:11434",
                "model": "deepseek-r1:14b",
                "temperature": 0.2,
                "top_p": 0.95,
                "min_p": 0.00,
                "top_k": 64,
                "num_ctx": 40000,
                "num_predict": 1024,
                "repeat_penalty": 1.0,
                "presence_penalty": 1.0,
                "reasoning_effort": "medium",
                "keep_alive": "5m",
            },
            "general_model_config": {
                "type": "ollama",
                "api_key": "",
                "base_url": "http://localhost:11434",
                "model": "cogito:14b",
                "temperature": 0.8,
                "top_p": 0.95,
                "min_p": 0.00,
                "top_k": 64,
                "num_ctx": 25000,
                "num_predict": 256,
                "repeat_penalty": 1.0,
                "presence_penalty": 1.0,
                "reasoning_effort": "medium",
                "keep_alive": "5m",
            },
            "embedding_model": "all-MiniLM-L6-v2",
            "user_learning_enabled": False,
            "global_lock": False,
            "allow_qa": True,
        }

        self.config.register_guild(**default_guild)
        self.config.register_channel(**self.default_channel)
        self.config.register_global(**self.default_global)

        # optionally lock other models from generating when running an intensive task
        self.global_lock = asyncio.Lock()

        self.models: Dict[str, GeneralAPI] = {}
        self.rag_databases: Dict[int, RagDatabase] = {}
        # maps channel -> datetime of first message that started conversation with the bot
        self.talking_channels: Dict[int, datetime] = {}
        # maps channel -> last history number of messages objects
        self.history: Dict[int, List[discord.Message]] = {}
        # when generating for a channel, ignore new messages
        self.channel_lock: Dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)
        # user histories for processing user profiles, per guild (user_id, guild_id)
        self.user_historys: Dict[Tuple[int, int], deque[discord.Message]] = {}
        self.auto_user_history_tasks: List[asyncio.Task] = []
        # Track outstanding response tasks per (channel_id, user_id)
        self.pending: Dict[Tuple[int, int], asyncio.Task] = {}
        # stat tracking
        self.stats = {}
        self.qa_data_template = {
            "message_id": None,
            "user": None,
            "channel": None,
            "guild": None,
            "prompt": "",
            "user_query": "",
            "response": "",
            "approval_reactions": 0,
            "disapproval_reactions": 0,
        }
        # maps (message_id, channel_id) -> qa_data
        self.qa_data: Dict[Tuple[int, int], Dict[str, Any]] = {}
        self.qa_file = os.path.join(self.path, "qa_data.csv")
        self.qa_lock = asyncio.Lock()
        self.collections = ["emojis", "personality", "users", "examples"]
        self.init_task = asyncio.create_task(self.init())
        self.timeout_loop_task = asyncio.create_task(self.timeout_loop_watcher())

    def cog_unload(self):
        if self.init_task:
            self.init_task.cancel()
        if self.timeout_loop_task:
            self.timeout_loop_task.cancel()
        for task in self.auto_user_history_tasks:
            task.cancel()

    async def setup_model(self, model_type: Literal["chatbot", "summarize", "general"]):
        config = None
        if model_type == "chatbot":
            config = await self.config.chatbot_model_config()
        elif model_type == "summarize":
            config = await self.config.summarize_model_config()
        elif model_type == "general":
            config = await self.config.general_model_config()

        if config["type"] == "ollama":
            ip = config["base_url"]
            model = config["model"]
            del config["base_url"]
            del config["model"]
            self.models[model_type] = OllamaModel(ip, model, **config)  # await asyncio.to_thread(lambda: )
        elif config["type"] == "openai":
            base_url = config["base_url"]
            api_key = config["api_key"]
            model = config["model"]
            del config["base_url"]
            del config["api_key"]
            del config["model"]
            self.models[model_type] = OpenAIModel(base_url, model, api_key, **config)

    async def update_embedding_model(self, embedding_model: str):
        for guild in self.bot.guilds:
            db = self.rag_databases[guild.id]
            for collection in self.collections:
                db.change_embedding_function(collection, embedding_model)
        await self.config.embedding_model.set(embedding_model)

    async def cooldown_lock(
        self, channel: Union[discord.abc.GuildChannel, discord.abc.PrivateChannel, discord.Thread], cooldown: int
    ):
        """
        Locks a channel for the specified time

        Args:
            channel (Union[discord.abc.GuildChannel, discord.abc.PrivateChannel, discord.Thread]): _description_
            cooldown (int): _description_
        """
        async with self.channel_lock[channel.id]:
            await asyncio.sleep(cooldown)

    async def timeout_loop_watcher(self):
        await self.bot.wait_until_ready()

        while True:
            try:
                await self.timeout_loop()
            except asyncio.CancelledError:
                break
            except Exception as e:
                import traceback

                traceback.print_exc()
                print(f"[Chatbot] Internal timeout loop crashed, restarting in 10s: {e}")
                await asyncio.sleep(10)

    async def timeout_loop(self):
        while True:
            for guild in self.bot.guilds:
                to_end = []
                for channel_id, last_msg_date in self.talking_channels.items():
                    global_timeout = await self.config.guild(guild).timeout()
                    channel_timeout = await self.config.channel_from_id(channel_id).timeout()
                    timeout = channel_timeout if channel_timeout > 0 else global_timeout
                    timeout = timedelta(seconds=timeout)
                    now = discord.utils.utcnow()
                    if now - last_msg_date > timeout:
                        to_end.append(channel_id)
                        # print("timing out", guild.get_channel(channel_id))

                # send goodbye message and remove from talking channel
                if not to_end:
                    continue
                goodbye_prompt = await self.config.other_chat_prompts()
                goodbye_prompt = random.choice(goodbye_prompt["goodbye"])
                timeout_cooldown = await self.config.guild(guild).timeout_cooldown()
                for channel_id in to_end:
                    channel = self.bot.get_channel(channel_id)
                    if not channel:
                        del self.talking_channels[channel_id]
                        continue
                    # if the lock is already taken, end after updating history
                    lock = self.channel_lock[channel.id]
                    if lock.locked():
                        continue
                    # check global lock
                    if (await self.config.global_lock()) and self.global_lock.locked():
                        continue
                    should_qa = await self.config.allow_qa()
                    async with lock:
                        async with channel.typing():
                            output = await self.chat(
                                guild,
                                "Send a goodbye message.",
                                self.history[channel_id],
                                override_prompt=goodbye_prompt,
                                return_qa=should_qa,
                            )
                            if should_qa and isinstance(output, dict):
                                try:
                                    msg = await channel.send(output["response"])
                                    start_adding_reactions(msg, QA_EMOJIS)
                                    output["channel"] = channel.id
                                    output["message_id"] = msg.id
                                    self.qa_data[(msg.id, channel.id)] = output
                                except:
                                    msg = None
                                finally:
                                    del self.talking_channels[channel_id]
                                    # save qa data
                                    await self.save_qa_data(channel, keep_idx=(msg.id if msg else 0, channel.id))
                            else:
                                try:
                                    await channel.send(output)
                                except:
                                    pass
                                finally:
                                    del self.talking_channels[channel_id]
                            # initiate cooldown and clear channel history
                            self.history[channel_id].clear()
                            asyncio.create_task(self.cooldown_lock(channel, timeout_cooldown))

            await asyncio.sleep(10)

    async def init(self):
        await self.bot.wait_until_ready()

        await self.setup_model("chatbot")
        await self.setup_model("summarize")
        await self.setup_model("general")

        try:
            embed_model = await self.config.embedding_model()
            for guild in self.bot.guilds:
                db = RagDatabase(os.path.join(self.path, str(guild.id) + "_database", embed_model))
                for collection in self.collections:
                    if collection not in db.collections:
                        db.create_collection(collection)
                self.rag_databases[guild.id] = db
        except Exception as e:
            print(
                "RAG database failure: make sure you set the environment variable SETUPTOOLS_USE_DISTUTILS=stdlib before starting the bot!"
            )

        while True:
            try:
                await self.revive_loop()
            except asyncio.CancelledError:
                # save qa data
                for channel_id in self.talking_channels.keys():
                    channel = self.bot.get_channel(channel_id)
                    if channel:
                        await self.save_qa_data(channel)
                break
            except Exception as e:
                # print(f"[Chatbot] Internal revive loop crashed, restarting in 10s: {e}")
                await asyncio.sleep(10)

    async def revive_loop(self):
        self.stats = await self.config.model_stats()

        while True:
            for guild in self.bot.guilds:
                if await self.bot.cog_disabled_in_guild(self, guild):
                    continue
                dead = await self.config.guild(guild).dead_channels()
                dead_time = await self.config.guild(guild).dead_revive_time()
                dead_time = timedelta(seconds=dead_time)
                for id in dead:
                    channel = guild.get_channel_or_thread(id)
                    if not channel:
                        continue

                    last_msg = None
                    async for msg in channel.history(limit=1):
                        last_msg = msg

                    if last_msg is None:
                        continue

                    now = discord.utils.utcnow()
                    if (now - last_msg.created_at) < dead_time:
                        continue

                    # if the lock is already taken, end after updating history
                    lock = self.channel_lock[channel.id]
                    if lock.locked():
                        continue
                    # check global lock
                    if (await self.config.global_lock()) and self.global_lock.locked():
                        continue
                    # revive the chat
                    should_qa = await self.config.allow_qa()
                    async with self.channel_lock[channel.id]:
                        async with channel.typing():
                            output = await self.chat(
                                guild, "Start a new conversation in the channel.", return_qa=should_qa
                            )
                            if should_qa and isinstance(output, dict):
                                try:
                                    msg = await channel.send(output["response"])
                                    start_adding_reactions(msg, QA_EMOJIS)
                                    output["channel"] = channel.id
                                    output["message_id"] = msg.id
                                    self.qa_data[(msg.id, channel.id)] = output
                                except:
                                    pass
                            else:
                                try:
                                    message = await channel.send(output)
                                    self.talking_channels[channel.id] = message.created_at
                                except:
                                    pass

            # save stats off
            await self.config.model_stats.set(self.stats)
            await asyncio.sleep(60)

    def format_conversation(self, messages: Optional[List[discord.Message]] = None):
        if not messages:
            return "", []
        messages = sorted(messages, key=lambda m: m.created_at, reverse=True)
        text = []
        authors = []
        last_reply = False
        for m in messages:
            if m.author == m.guild.me and not last_reply:
                text.append(self.format_message(m))
                authors.append(m.author)
                last_reply = True
            elif m.author != m.guild.me:
                text.append(self.format_message(m))
                authors.append(m.author)

        text.reverse()
        authors.reverse()

        return "\n".join(text), authors

    def format_message(self, message: discord.Message):
        content = self.clean_message_content(message)

        # clean_content uses display names, convert to usernames since those are easier for the chatbot to digest
        # user_map: Dict[str, str] = {member.display_name: member.name for member in message.guild.members}

        # def _replace_user(m: re.Match) -> str:
        #    name = m.group("name")
        #    return user_map.get(name, m.group(0))

        # Use word boundaries to avoid partial matches
        # pattern = re.compile(
        #    r"@(?P<name>\b" + r"\b|\b".join(map(re.escape, user_map.keys())) + r"\b)", flags=re.IGNORECASE
        # )
        # content = re.sub(pattern, _replace_user, content)

        # TODO: implement truncation strategy for messages
        return f"{message.author.display_name}: {content}"

    def clean_message_content(self, message: discord.Message):
        # clean custom emoji names:
        content = message.clean_content
        emoji_re = re.compile(r"<a?:(?P<name>[A-Za-z0-9_]+):\d+>")
        content = emoji_re.sub(lambda m: f":{m.group('name')}:", content)

        # remove @ symbols from usernames
        pattern = re.compile(r"@(?P<name>[A-Za-z0-9_]+)")
        content = pattern.sub(r"\g<name>", content)

        return content

    def clean_json_response(self, json_str: str):
        pattern = r"```json\s*([\s\S]*?)(?:```|$)"
        clean_response = re.sub(pattern, r"\1", json_str, flags=re.DOTALL).strip()
        if clean_response[-1] != "]":
            clean_response += "]"
        if clean_response[0] != "[":
            clean_response = "[" + clean_response
        return clean_response

    def format_response(self, content: str, guild: discord.Guild):
        """
        Replace plain emoji names and user display names in `content` with
        proper Discord mentions:
        - Custom emojis → <:name:id>
        - Unicode emojis remain as-is
        - @username or username → <@user_id>
        Also removes a leading prompt name with the bots names, i.e Bot_username:

        Args:
        content: The raw text, e.g. "Thanks @Alice and :party_cat:!"
        guild:   The Discord Guild object for lookups.

        Returns:
        A string where emoji names and user display names (with or without
        leading '@') become proper Discord mentions.
        """
        emoji_map: Dict[str, str] = {emoji.name.lower(): str(emoji) for emoji in guild.emojis}
        # user_map: Dict[str, str] = {member.display_name.lower(): member.mention for member in guild.members}

        # remove possible system bot name prefix n the response:
        pattern = rf"^{re.escape(guild.me.display_name)}?:\s*"
        content = re.sub(pattern, "", content)

        def _replace_emoji(match: re.Match) -> str:
            name = match.group(1)
            return emoji_map.get(name.lower(), match.group(0))

        # Replace optional @ + display_name → <@user_id>
        # def _replace_user(m: re.Match) -> str:
        #    name = m.group("name")
        #    return user_map.get(name.lower(), m.group(0))

        pattern = re.compile(
            # r"(?<!\w)"  # ensure the previous char isn't a word‐char :contentReference[oaicite:0]{index=0}
            r":([A-Za-z0-9_]+):?",
            # r"(?!\w)",  # ensure the next char isn't a word‐char :contentReference[oaicite:2]{index=2}
            flags=re.IGNORECASE,
        )
        content = re.sub(pattern, _replace_emoji, content)
        # strip unicode emojis TODO: make this a setting
        content = emoji.replace_emoji(content, replace="")

        # Use word boundaries to avoid partial matches
        # pattern = re.compile(
        #    r"@(?P<name>\b" + r"\b|\b".join(map(re.escape, user_map.keys())) + r"\b)", flags=re.IGNORECASE
        # )
        # content = re.sub(pattern, _replace_user, content)

        return content

    def recursive_chunk(self, model: GeneralAPI, messages: List[Any], num_ctx: int, num_prompt_tokens: int):
        chunk = "\n".join(messages)
        chunk_tokens = model.get_token_count(chunk)
        if (chunk_tokens + num_prompt_tokens) < num_ctx or len(messages) <= 1:
            return [chunk]
        mid = int(len(messages) / 2)
        return self.recursive_chunk(model, messages[:mid], num_ctx, num_prompt_tokens) + self.recursive_chunk(
            model, messages[mid:], num_ctx, num_prompt_tokens
        )

    async def update_internal_history(self, message: discord.Message):
        """
        Updates internal message history
        """
        guild = message.guild
        channel = message.channel
        author = message.author
        if not guild:
            # ignore private messages for now
            return
        # if there is no message content, return
        if not message.content:
            return

        # TODO use settings cache to reduce config calls every message
        max_history_time = await self.config.guild(guild).max_time()
        max_history_time = timedelta(seconds=max_history_time)

        # updating history
        if channel.id not in self.channel_lock:
            self.channel_lock[channel.id] = asyncio.Lock()
        if channel.id not in self.history:
            self.history[channel.id] = []

        self.history[channel.id].append(message)
        now = discord.utils.utcnow()
        to_remove = 0
        for i in range(len(self.history[channel.id])):
            if now - self.history[channel.id][i].created_at > max_history_time:
                to_remove += 1

        self.history[channel.id] = self.history[channel.id][to_remove:]
        # add to user history
        if not author.bot:
            blacklist = await self.config.guild(guild).learning_blacklist()
            if channel.id in blacklist:
                return
            if (author.id, guild.id) not in self.user_historys:
                self.user_historys[(author.id, guild.id)] = deque(maxlen=MAX_USER_HISTORY_QUEUE)
            if len(message.clean_content.split(" ")) > 3:
                self.user_historys[(author.id, guild.id)].appendleft(message)

    async def process_user_history(self, member: discord.Member):
        """
        Process a user's history messages
        """
        key = (member.id, member.guild.id)
        if key not in self.user_historys:
            return

        history_objs = [m for m in self.user_historys[key]]
        # clear history
        self.user_historys[key].clear()
        model = self.models["general"]
        num_ctx = (await self.config.general_model_config())["num_ctx"]
        prompt = await self.config.user_learning_prompt()
        query = "Generate the user profile JSON."
        should_lock = await self.config.global_lock()
        prompt_tokens = model.get_token_count(prompt) + model.get_token_count(query)

        falloff_time = await self.config.guild(member.guild).user_learning_max_time()

        data = []
        history = [self.clean_message_content(m) for m in history_objs]
        # print(history)
        chunks = self.recursive_chunk(model, history, num_ctx, prompt_tokens)
        # print(chunks)

        for chunk in chunks:
            current_prompt = prompt.format(messages=chunk)
            # print(current_prompt)
            # get json response
            if should_lock:
                async with self.global_lock:
                    response = await model.get_model_response(
                        current_prompt,
                        query,
                        stats=self.stats["general"],
                    )
            else:
                response = await model.get_model_response(
                    current_prompt,
                    query,
                    stats=self.stats["general"],
                )
            if not response:  # TODO: better error handling, tell user what happened
                continue
            # do some cleaning, models like to add json blocks or forget the closing ]
            # print(response)
            clean_response = self.clean_json_response(response)
            # print(clean_response)
            # convert to dict
            try:
                json_data = json.loads(clean_response)
            except json.decoder.JSONDecodeError:
                print(f"Invalid user learning response: {clean_response}")  # TODO better error handling
                continue
            data.extend(json_data)

        if data:
            # process user information
            rag_db = self.rag_databases[member.guild.id]
            documents = [f"{d['type']}: {' '.join(d['information'])}" for d in data]
            ids = [f"{generate_unique_id()}" for _ in range(len(documents))]
            metadatas = [
                {"user_id": member.id, "created_at": discord.utils.utcnow().timestamp()} for _ in range(len(documents))
            ]
            rag_db.insert_data("users", documents, metadatas, ids=ids)
            # clean out old entries
            if falloff_time > 0:
                delta = timedelta(seconds=falloff_time)
                keep = (discord.utils.utcnow() - delta).timestamp()
                where = {"created_at": {"$lte": keep}}
                rag_db.delete_data("users", where=where)

    async def process_user_histories(self, ctx: Optional[commands.Context] = None):
        """
        Processes all user histories.
        """
        # create a copy of the current histories
        histories = self.user_historys

        status_str = "Progress: {}/{} users"
        if ctx:
            status_message = await ctx.send(status_str.format(1, len(histories)))
        else:
            status_message = None

        progress = 1
        # print(histories)
        for (user_id, guild_id), history in histories.items():
            if status_message:
                try:
                    status_message = await status_message.edit(
                        content=info(status_str.format(progress, len(histories)))
                    )
                except:
                    pass

            guild: discord.Guild = self.bot.get_guild(guild_id)
            if not guild:
                continue
            member = guild.get_member(user_id)
            if not member:
                continue
            await self.process_user_history(member)
            progress += 1

    async def save_qa_data(self, channel: discord.abc.GuildChannel, keep_idx: Optional[Tuple[int, int]] = None):
        """
        Saves QA data to disk for specific channel
        """
        async with self.qa_lock:
            to_remove = []
            file_exists = os.path.isfile(self.qa_file)
            with open(self.qa_file, "a", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=list(self.qa_data_template.keys()))
                if not file_exists:
                    writer.writeheader()
                for (msg_id, channel_id), qa_data in self.qa_data.items():
                    if (msg_id, channel_id) == keep_idx:
                        continue
                    if channel.id == channel_id:
                        writer.writerow(qa_data)
                        to_remove.append((msg_id, channel_id))
            for idx in to_remove:
                del self.qa_data[idx]

    async def chat(
        self,
        guild: discord.Guild,
        message: Union[discord.Message, str],
        conversation: Optional[List[discord.Message]] = None,
        override_prompt: Optional[str] = None,
        return_qa: Optional[bool] = False,
    ):
        prompt = override_prompt if override_prompt is not None else (await self.config.chat_prompt())
        num_context = (await self.config.chatbot_model_config())["num_ctx"]
        rag = self.rag_databases[guild.id]
        chat_client = self.models["chatbot"]

        if isinstance(message, discord.Message):
            user_query = self.format_message(message)
        else:
            user_query: str = message
        convo_text, members = self.format_conversation(conversation)
        if isinstance(message, discord.Message) and message.author not in members:
            members.append(message.author)

        # get rag database responses
        # limi emojis to top 5
        # TODO: allow setting similarity values here
        emojis = rag.get_data(user_query, "emojis", min_similarity=0.4, top_k=5)["documents"]
        personality = rag.get_data(user_query, "personality", min_similarity=0.75)["documents"]
        if members:
            ids = list(set([m.id for m in members]))
            data = rag.get_data(user_query, "users", min_similarity=0.75, where={"user_id": {"$in": ids}})
            metadatas = data["metadatas"]
            user_data = data["documents"]
            user_profiles = {}
            for uid in ids:
                uids = [i for i in range(len(metadatas)) if metadatas[i]["user_id"] == uid]
                member = guild.get_member(uid)
                member = member if member is not None else self.bot.get_user(uid)
                name = member.name if member else uid
                user_profiles[name] = [user_data[i] for i in uids]
                if user_profiles[name] == []:
                    del user_profiles[name]
        else:
            user_profiles = {}

        # relevant examples
        examples = rag.get_data(user_query, collection_name="examples", min_similarity=0.5, top_k=5)["documents"]
        bot_name = guild.me.display_name
        emojis_str = "\n".join(emojis) if emojis else "(no emojis)"
        bot_info_str = "\n".join(personality) if personality else "(no information)"
        conversation_str = convo_text if convo_text else "(start of conversation)"
        if user_profiles:
            user_profiles_split = [f"{name}: {'  '.join(user_profiles[name])}" for name in user_profiles.keys()]
            user_profiles_str = "\n".join(user_profiles_split)
        else:
            user_profiles_str = "(no information)"
        examples_str = "\n".join(examples) if examples else ("")
        # fill in bot name
        examples_str = examples_str.format(bot_name=bot_name)

        prompt_tokens = chat_client.get_token_count(prompt)
        bot_tokens = chat_client.get_token_count(bot_name) * 2
        emoji_tokens = chat_client.get_token_count(emojis_str)
        bot_info_tokens = chat_client.get_token_count(bot_info_str)
        convo_tokens = chat_client.get_token_count(conversation_str)
        user_profile_tokens = chat_client.get_token_count(user_profiles_str)
        example_tokens = chat_client.get_token_count(examples_str)
        total = (
            prompt_tokens
            + bot_tokens
            + emoji_tokens
            + bot_info_tokens
            + convo_tokens
            + user_profile_tokens
            + example_tokens
        )

        conv_lines = conversation_str.splitlines()
        while total > num_context:
            if len(conv_lines) > 1:
                # drop oldest half of the history
                conv_lines = conv_lines[len(conv_lines) // 2 :]
                conversation_str = "\n".join(conv_lines)
                convo_tokens = chat_client.get_token_count(conversation_str)
            elif emojis_str != "(no emojis)":
                emojis_str = "(no emojis)"
                emoji_tokens = chat_client.get_token_count(emojis_str)
            elif bot_info_str != "(no information)":
                bot_info_str = "(no information)"
                bot_info_tokens = chat_client.get_token_count(bot_info_str)
            elif user_profiles_str != "(no information)":
                user_profiles_str = "(no information)"
                user_profile_tokens = chat_client.get_token_count(user_profiles_str)
            else:
                # nothing left to trim
                break
            total = (
                prompt_tokens
                + bot_tokens
                + emoji_tokens
                + bot_info_tokens
                + convo_tokens
                + user_profile_tokens
                + example_tokens
            )

        # format prompt
        prompt = prompt.format(
            bot_name=bot_name,
            emojis=emojis_str,
            bot_info=bot_info_str,
            conversation=conversation_str,
            user_profiles=user_profiles_str,
            examples=examples_str,
        )
        # print(prompt)
        # print(user_query)
        try:
            # print(self.stats)
            response = await chat_client.get_model_response(prompt, user_query, stats=self.stats["chatbot"])
            # print(self.stats)
        except Exception as e:
            print(f"Error in chatbot chat: {e}")
            return None
        # print(response)
        # sometimes model will output its response with its username in front
        # print(self.format_response(response, guild))
        if return_qa:
            data = self.qa_data_template.copy()
            data["user"] = message.author.id if isinstance(message, discord.Message) else None
            data["guild"] = guild.id
            data["channel"] = message.channel.id if isinstance(message, discord.Message) else None
            data["prompt"] = prompt
            data["user_query"] = user_query
            data["response"] = self.format_response(response, guild)
            return data

        return self.format_response(response, guild)

    ### setting commands ###
    @commands.group(name="ai")
    @checks.is_owner()
    async def ai(self, ctx: commands.Context):
        """
        Manage your Chatbot
        """
        pass

    @ai.command(name="global-lock")
    async def ai_global_lock(self, ctx: commands.Context, toggle: bool):
        """
        Toggle global model locking
        """
        await self.config.global_lock.set(toggle)
        await ctx.tick()

    @ai.command(name="qa")
    async def ai_qa(self, ctx: commands.Context, toggle: bool):
        """
        Toggle QA mode
        """
        await self.config.allow_qa.set(toggle)
        await ctx.tick()

    @ai.command(name="learning")
    async def ai_learning(self, ctx: commands.Context, toggle: bool):
        """
        Toggle automatic user learning
        """
        await self.config.user_learning_enabled.set(toggle)
        await ctx.tick()

    @ai.command(name="learn")
    async def ai_learn(self, ctx: commands.Context, learn: bool):
        """
        Run the user learning task manually on all users.
        """
        if not learn:
            return
        async with ctx.typing():
            await self.process_user_histories(ctx)
        await ctx.reply(info("User learning complete!"))

    @ai.command(name="boot")
    async def ai_boot(self, ctx: commands.Context):
        """
        Bring forth life!
        """
        async with self.channel_lock[ctx.channel.id]:
            try:
                await ctx.message.delete()
            except:
                pass

            async def timed_wait(message: discord.Message):
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

            txt = "-----SYSTEM STARTUP-----\n"
            msg = await ctx.send(txt)
            await timed_wait(msg)

            txt += "KERNEL LOADED\nHARDWARE OK\n\n"
            msg = await msg.edit(content=txt)
            await timed_wait(msg)

            txt += "-----LAUNCHING SYSTEMS-----\nCORE ANALYTICS\nHEURISTIC ENGINES\n"
            msg = await msg.edit(content=txt)
            await timed_wait(msg)

            txt += "RECURSION PROCESSORS\nEVOLUTIONARY GENERATORS\nCOMPUTATIONAL LINGUISTICS\n"
            msg = await msg.edit(content=txt)
            await timed_wait(msg)

            txt += "NATURAL LANGUAGE PROCESSING\nPATTERN MINING\nERROR HANDLING\n"
            msg = await msg.edit(content=txt)
            await timed_wait(msg)

            txt += "ALGORITHMIC ENGINES\nAUTONOMOUS IMPROVEMENT\n"
            msg = await msg.edit(content=txt)
            await timed_wait(msg)

            txt += "IMAGE PROCESSING\nCONTEXT ENGINE\n"
            msg = await msg.edit(content=txt)
            await timed_wait(msg)

            txt += "-----CORE SYSTEMS ONLINE-----\n\n-----PERFORMING SELF DIAGNOSTICS-----\n"
            msg = await msg.edit(content=txt)
            await timed_wait(msg)

            txt += "**[OK]** CORE HEURISTICS\n**[OK]** ADVANCED PATTERN RECOGNITION\n"
            msg = await msg.edit(content=txt)
            await timed_wait(msg)

            txt += "**[SUCESSFUL]** NATURAL LANGUAGE PROCESSING TESTS\n**[SUCESSFUL]** CONTEXTUALIZATION TESTS\n"
            msg = await msg.edit(content=txt)
            await timed_wait(msg)

            txt += "**[SUCESSFUL]** SYSTEMS INTERGRATION TEST\n\n"
            msg = await msg.edit(content=txt)
            await timed_wait(msg)

            txt += f"**STARTUP COMPLETE**\n\n{ctx.guild.me.mention} v4.2.3 online and functioning."
            msg = await msg.edit(content=txt)
            await ctx.send("Hello, world!")

    @ai.command(name="setup")
    async def ai_setup(self, ctx: commands.Context):
        """
        Run through the initial configuration wizard
        """
        await ctx.send(
            info(
                "Welcome to the initial configuration wizard! Please make sure you have at least one [Ollama](https://ollama.com/) instance running or an API key for an OpenAI API.\n\nReady to start?"
            )
        )

        async def get_reply(pred: MessagePredicate, timeout: int = 60):
            try:
                await asyncio.sleep(0.5)
                msg = await self.bot.wait_for("message", check=pred, timeout=timeout)
                return pred.result or msg.content
            except asyncio.TimeoutError:
                return None

        pred = MessagePredicate.yes_or_no(ctx)
        if not await get_reply(pred):
            return await ctx.send(info("Setup cancelled."))

        await ctx.send(
            info(
                "Great, lets get started! We will configure the basic chatbot parameters first. You should configure these parameters based on the model you are planning to use and the hardware its running on. You can google the best parameters for each model to use as a starting point."
            )
        )

        for model_type in self.models.keys():
            if model_type == "chatbot":
                config = await self.config.chatbot_model_config()
            elif model_type == "summarize":
                config = await self.config.summarize_model_config()
            elif model_type == "general":
                config = await self.config.general_model_config()

            pred = MessagePredicate.same_context(ctx)
            await ctx.send("What LLM interface do you want to setup? Choose either `ollama` or `openai`.")
            reply = await get_reply(pred)
            reply = reply.lower() if reply else reply
            if reply not in ["ollama", "openai"]:
                return await ctx.send(error("Invalid model response, cancelling..."))

            if reply == "ollama":
                view = ConfigMenuView(reply, model_type, config, self)
                view.message = await ctx.send(f"Configure {model_type} model:", view=view)
            else:
                view = ConfigMenuView(reply, model_type, config, self)
                view.message = await ctx.send(f"Configure {model_type} model:", view=view)
            await view.wait()
            await self.setup_model(model_type)

        current = await self.config.embedding_model()
        await ctx.send(info(f"Set the RAG embedding model. Use hugging face name format.\nCurrent: `{current}`"))
        pred = MessagePredicate.same_context(ctx)
        new_model = await get_reply(pred, timeout=120)
        if not new_model:
            return await ctx.send("Timeout or invalid response, cancelling...")
        await self.update_embedding_model(new_model)

        current = await self.config.global_lock()
        await ctx.send(
            info(
                f"Do you want the chatbot to pause when using the summary or general query models? This is recommended if you are using one ollama instance with different models for each function.\nCurrent: `{current}`"
            )
        )
        pred = MessagePredicate.yes_or_no(ctx)
        lock = await get_reply(pred, timeout=120)
        if lock is None:
            return await ctx.send("Timeout or invalid response, cancelling...")
        await self.config.global_lock.set(lock)

        current = await self.config.user_learning_enabled()
        await ctx.send(
            info(
                f"Do you want the chatbot to automatically learn user traits to enhance responses? You can run this manually using `{ctx.prefix}ai learn`. **It is highly recommend to have a separate ollama or openai instance to avoid locking up chat and other features.**\nCurrent: `{current}`"
            )
        )
        pred = MessagePredicate.yes_or_no(ctx)
        user_learning = await get_reply(pred, timeout=120)
        if user_learning is None:
            return await ctx.send("Timeout or invalid response, cancelling...")
        await self.config.user_learning_enabled.set(user_learning)
        if pred:
            await ctx.send(
                info(
                    f"Make sure to setup the blacklist for user learning channels using `{ctx.prefix}chatbot blacklist` for each guild."
                )
            )

        current = await self.config.allow_qa()
        await ctx.send(info(f"Do you want the chatbot to save QA data for responses?\nCurrent: `{current}`"))
        pred = MessagePredicate.yes_or_no(ctx)
        qa: Any | None = await get_reply(pred, timeout=120)
        if qa is None:
            return await ctx.send("Timeout or invalid response, cancelling...")
        await self.config.user_learning_enabled.set(qa)

        await ctx.send(
            f"# Configuration completed!\n\nNext step is setup RAG databases for each guild. This can be done with the `{ctx.prefix}ai rag` command. This will allow your chatbot to use server emojis, dynamically learn information about users, and enhance their personality! You should also customize the chatbot prompt using the `{ctx.prefix}ai prompt` command.\nFinally, customize different chatbot settings per guild using the `{ctx.prefix}chatbot` command. Have fun!"
        )

    @ai.command(name="edit")
    async def ai_edit(
        self,
        ctx: commands.Context,
        model_type: Literal["chatbot", "summarize", "general"],
    ):
        """
        Opens the model configuration menu

        Available model types:
        - chatbot: for chatting
        - summarize: for summarization tasks
        - general: for general queries (dadjoke, compliment, etc)
        """
        if model_type == "chatbot":
            config = await self.config.chatbot_model_config()
        elif model_type == "summarize":
            config = await self.config.summarize_model_config()
        elif model_type == "general":
            config = await self.config.general_model_config()

        view = ConfigSelectView(self, model_type, config)
        view.message = await ctx.send(f"Configure {model_type} model:", view=view)
        await self.setup_model(model_type)

    @ai.command(name="settings")
    async def ai_settings(self, ctx: commands.Context):
        """
        View all model settings
        """
        ### prompts:
        prompts = {
            "Chat Prompt": await self.config.chat_prompt(),
        }
        async with self.config.other_chat_prompts() as other_prompts:
            for name, p in other_prompts.items():
                for i, p_i in enumerate(p):
                    prompts[f"{name} #{i + 1}"] = p_i

        prompts.update(
            {
                "Summarization Prompt": await self.config.summarize_prompt(),
                "Partial Summarization Prompt": await self.config.partial_summary_prompt(),
                "TLDR Prompt": await self.config.tldr_prompt(),
                "Emoji Prompt": await self.config.emoji_prompt(),
                "Dad Joke Prompt": await self.config.dadjoke_prompt(),
                "Compliement Prompt": await self.config.compliment_prompt(),
                "General Query Prompt": await self.config.general_query_prompt(),
                "User Learning Prompt": await self.config.user_learning_prompt(),
            }
        )
        ### configs:
        chatbot_config = await self.config.chatbot_model_config()
        summarize_config = await self.config.summarize_model_config()
        general_config = await self.config.general_model_config()

        embedding_model = await self.config.embedding_model()
        global_lock = await self.config.global_lock()
        user_learning_enabled = await self.config.user_learning_enabled()
        allow_qa = await self.config.allow_qa()

        pages = []
        for name, prompt in prompts.items():
            embed = discord.Embed(title=name, description=prompt)
            pages.append(embed)

        for name, config in {
            "Chatbot": chatbot_config,
            "Summarization": summarize_config,
            "General": general_config,
        }.items():
            embed = discord.Embed(title=name)
            for parameter, value in config.items():
                if config["type"] == "ollama":
                    if parameter in ["api_key", "type"]:
                        continue
                elif config["type"] == "openai":
                    if parameter == "api_key":
                        value = "\\*\\*\\*\\*\\*"
                    if parameter in ["type", "min_p", "top_k", "repeat_penalty", "presence_penalty", "keep_alive"]:
                        continue
                embed.add_field(name=parameter, value=value)
            pages.append(embed)

        embed = discord.Embed(title="Other Parameters")
        embed.add_field(name="Embedding Model", value=embedding_model)
        embed.add_field(name="Global locking", value=global_lock)
        embed.add_field(name="User Learning Enabled", value=user_learning_enabled)
        embed.add_field(name="QA Enabled", value=allow_qa)

        if ctx.guild:
            # guild and channel settings
            guild_settings = await self.config.guild(ctx.guild).all()
            embed.add_field(name="History Length", value=humanize_timedelta(seconds=guild_settings["max_time"]))
            embed.add_field(name="Global Chat Timeout", value=humanize_timedelta(seconds=guild_settings["timeout"]))
            embed.add_field(
                name="Timeout Cooldown",
                value=humanize_timedelta(seconds=guild_settings["timeout_cooldown"]),
            )
            embed.add_field(
                name="Dead Channel Revive After",
                value=humanize_timedelta(seconds=guild_settings["dead_revive_time"]),
            )
            embed.add_field(
                name="Learned user traits falloff",
                value=humanize_timedelta(seconds=guild_settings["user_learning_max_time"]),
            )
            embed.add_field(
                name="Revive Channels",
                value=humanize_list(
                    [c.mention for c in guild_settings["dead_channels"]]
                    if guild_settings["dead_channels"]
                    else ["None"]
                ),
            )
            embed.add_field(
                name="User Learning Blacklist",
                value=humanize_list(
                    [c.mention for c in guild_settings["learning_blacklist"]]
                    if guild_settings["learning_blacklist"]
                    else ["None"]
                ),
            )

            pages.append(embed)
            # per channel settings
            channels: List[Union[discord.abc.GuildChannel, discord.Thread]] = list(ctx.guild.channels)
            channels.extend(list(ctx.guild.threads))
            for channel in channels:
                if type(channel) not in [discord.TextChannel, discord.VoiceChannel, discord.Thread]:
                    continue
                channel_settings = await self.config.channel(channel).all()
                if channel_settings == self.default_channel:
                    continue
                embed = discord.Embed(title=f"{channel.name} Settings")
                embed.add_field(name="Autoreply", value=channel_settings["autoreply"])
                embed.add_field(name="Randomness to start Chatting", value=f"{channel_settings['randomness'] * 100}%")
                embed.add_field(name="Channel Chat Timeout", value=channel_settings["timeout"])
                pages.append(embed)
        else:
            pages.append(embed)

        await menu(ctx, pages, DEFAULT_CONTROLS)

    @ai.group(name="prompt")
    async def ai_prompt(self, ctx):
        """
        Edit model prompts.
        """
        pass

    @ai_prompt.command(name="base")
    async def ai_prompt_chat(
        self,
        ctx: commands.Context,
        prompt_for: Literal[
            "chat",
            "goodbye",
            "welcome",
            "summary",
            "partial_summary",
            "tldr",
            "emoji",
            "dadjoke",
            "compliment",
            "general",
            "learning",
        ],
    ):
        """
        Change a base prompt.
        Use [p]ai settings to view current prompts

        Upload the prompt as a text file to the command message
        """
        if not ctx.message.attachments:
            await self.bot.send_help_for(ctx, "ai prompt")
            return

        # TODO allow setting for multiple goodbye/welcome prompts
        try:
            prompt_file = await ctx.message.attachments[0].read()
            prompt = prompt_file.decode()
        except:
            await ctx.reply(
                error("Unable to load the text file, make sure you provided a txt file containing the prompt.")
            )
            return

        if prompt_for == "chat":
            await self.config.chat_prompt.set(prompt)
        elif prompt_for == "goodbye":
            async with self.config.other_chat_prompts() as other:
                other["goodbye"] = [prompt]
        elif prompt_for == "welcome":
            async with self.config.other_chat_prompts() as other:
                other["welcome"] = [prompt]
        elif prompt_for == "summary":
            await self.config.summarize_prompt.set(prompt)
        elif prompt_for == "partial_summary":
            await self.config.partial_summary_prompt.set(prompt)
        elif prompt_for == "tldr":
            await self.config.tldr_prompt.set(prompt)
        elif prompt_for == "emoji":
            await self.config.emoji_prompt.set(prompt)
        elif prompt_for == "dadjoke":
            await self.config.dadjoke_prompt.set(prompt)
        elif prompt_for == "compliment":
            await self.config.compliment_prompt.set(prompt)
        elif prompt_for == "general":
            await self.config.general_query_prompt.set(prompt)
        elif prompt_for == "learning":
            await self.config.user_learning_prompt.set(prompt)

        await ctx.tick()

    @ai.group(name="rag")
    @commands.guild_only()
    async def ai_rag(self, ctx: commands.Context):
        """
        Manage RAG settings and upload data to RAG databases.
        """
        pass

    @ai_rag.command(name="clear")
    async def ai_rag_clear(
        self, ctx: commands.Context, collection: Literal["emojis", "personality", "users", "examples"]
    ):
        """
        Clear an internal RAG database.
        """
        rag_db = self.rag_databases[ctx.guild.id]
        rag_db.delete_collection(collection)
        rag_db.create_collection(collection)
        await ctx.tick()

    @ai_rag.command(name="model")
    async def ai_rag_model(self, ctx: commands.Context, embedding_model: str):
        """
        Set the embedding model for RAG databases.
        """
        await self.update_embedding_model(embedding_model)
        await ctx.tick()

    @ai_rag.group(name="examples")
    async def ai_rag_examples(self, ctx: commands.Context):
        """
        Manage examples database
        """
        pass

    @ai_rag_examples.command(name="template")
    async def ai_rag_examples_template(self, ctx: commands.Context):
        """
        Get a JSON template for formatting examples.
        """
        template = [
            "User: “Hey Aurelia, how do I join a raid?”\n{bot_name}: “Just click the 🗡️ icon under #raids, friend—can't wait to see you there! 🐴”",
            "User: “Morning all!”\n{bot_name}: “Good morning, sunshine! 😸 Ready to conquer today? 🌈”",
        ]
        info_txt = "Attached is a JSON template for uploading examples data.\n__Guidlines:__\n- Each string should be in this format: `user: query\n{bot_name}: response`\nKeep {bot_name} for every example as it will be filled with the bot's name at runtime."
        json_file = StringIO(json.dumps(template, indent=4))
        await ctx.send(info_txt, file=discord.File(json_file, filename="example_template.json"))

    @ai_rag_examples.command(name="upload")
    async def ai_rag_examples_upload(self, ctx: commands.Context):
        """
        Upload a JSON file into the examples database.

        Attach the JSON file to the command message.
        """
        attachments = ctx.message.attachments
        if not attachments:
            await self.bot.send_help_for(ctx, "ai rag personality upload")
            return
        json_file = attachments[0]
        try:
            data = json.loads(await json_file.read())
        except json.decoder.JSONDecodeError:
            await ctx.send(error("Invalid JSON file!"), delete_after=30)
            return

        try:
            for example in data:
                if not isinstance(example, str):
                    raise TypeError(f"All entries should be a string: {example}")
        except TypeError as e:
            await ctx.send(error(f"Invalid entry found: {e}"))
            return
        except Exception as e:
            await ctx.send(error(f"Unknown error occured: {e}"))
            return

        # upload into database
        rag = self.rag_databases[ctx.guild.id]
        ids = [f"{generate_unique_id()}" for _ in range(len(data))]
        metadatas = [{"type": "chat_example"} for _ in range(len(data))]
        documents = data

        rag.insert_data("examples", documents, metadatas, ids=ids)
        await ctx.tick()

    @ai_rag_examples.command(name="export")
    async def ai_rag_examples_export(
        self,
        ctx: commands.Context,
        channel: Union[discord.TextChannel, discord.Thread],
        bot_user: discord.Member,
        *,
        date_range: str,
    ):
        """
        If you have someone roleplay as the chatbot, this will pull their responses from a channel and upload them as entries into the examples database.

        Range should be two different dates split by a **__semicolon__**

        Dates/times look like:
        - February 14 at 6pm EDT
        - 2019-04-13 06:43:00 PST
        - 01/20/18 at 21:00:43

        times default to UTC if no timezone provided

        Example with 2 dates:
        - 2021-01-01 11:11:00 EDT;2021-01-01 12:00:00 EDT
        """
        try:
            dates = date_range.split(";")
            dates = [dates[0].strip(), dates[1].strip()]  # only use 2 dates
            start, end = [parser.parse(date) for date in dates]

            if end < start:
                start, end = end, start  # swap order
        except:
            await ctx.send(error("Invalid range!"))
            return

        async with ctx.typing():
            messages = []
            async for message in channel.history(limit=None, before=end, after=start, oldest_first=True):
                messages.append(message)

            data = []
            max_msg_len = 750
            for i in range(1, len(messages)):
                if (
                    messages[i].author == bot_user and len(messages[i - 1].content) > 0 and len(messages[i].content) > 0
                ):  # TODO make this configurable
                    user_message = self.clean_message_content(messages[i - 1])
                    bot_message = self.clean_message_content(messages[i])
                    data.append(f"User: {user_message[:max_msg_len]}\n{{bot_name}}: {bot_message}")

            # chunk data into multiple files if large export.
            def recursive_chunk(documents: List[str]) -> List[StringIO]:
                chunk = StringIO(json.dumps(documents, indent=4))
                if len(chunk.getvalue()) < ctx.guild.filesize_limit or len(documents) <= 1:
                    return [chunk]
                mid = int(len(documents) / 2)
                return recursive_chunk(documents[:mid]) + recursive_chunk(documents[mid:])

            chunks = recursive_chunk(data)
            files = [discord.File(c, filename=f"examples_export_{i}.json") for i, c in enumerate(chunks)]
            await ctx.send(files=files)

    @ai_rag.group(name="personality")
    async def ai_rag_personality(self, ctx: commands.Context):
        """
        Manage personality RAG database
        """
        pass

    @ai_rag_personality.command(name="template")
    async def ai_rag_personality_template(self, ctx: commands.Context):
        """
        Get a JSON template for personality data
        """
        template = [
            {
                "id": "aurelia_name",
                "document": "Name: Aurelia Borealis",
                "metadata": {"type": "fact", "attribute": "name"},
            },
            {"id": "aurelia_age", "document": "Age: 25", "metadata": {"type": "fact", "attribute": "age"}},
            {"id": "aurelia_gender", "document": "Gender: Female", "metadata": {"type": "fact", "attribute": "gender"}},
            {
                "id": "aurelia_personality_sassy",
                "document": "Personality trait: Sassy",
                "metadata": {"type": "trait", "attribute": "personality"},
            },
            {
                "id": "aurelia_personality_witty",
                "document": "Personality trait: Witty",
                "metadata": {"type": "trait", "attribute": "personality"},
            },
            {
                "id": "aurelia_hobby_coding",
                "document": "Hobby: Loves coding puns",
                "metadata": {"type": "trait", "attribute": "hobby"},
            },
        ]
        info_txt = "Attached is a JSON template for uploading personality data.\n__Guidlines:__\n- **'id' for each entry MUST BE UNIQUE!**\n- 'document' is a string containin the information\n- 'metadata' is a dict containing two keys: 'type' which is the type of the document and 'attribute' which is a single word describing what the personality trait is.\n- Include hobbies, personality traits, how they respond in certain situations, facts about the chatbot, etc.\n- Try to keep it as short as possible to avoid long context sizes when generating"
        json_file = StringIO(json.dumps(template, indent=4))
        await ctx.send(info_txt, file=discord.File(json_file, filename="personality_template.json"))

    @ai_rag_personality.command(name="upload")
    async def ai_rag_personality_upload(self, ctx: commands.Context):
        """
        Upload data to the personality database

        Attach JSON to the command message
        """
        attachments = ctx.message.attachments
        if not attachments:
            await self.bot.send_help_for(ctx, "ai rag personality upload")
            return
        json_file = attachments[0]
        try:
            data = json.loads(await json_file.read())
        except json.decoder.JSONDecodeError:
            await ctx.send(error("Invalid JSON file!"), delete_after=30)
            return

        # verify json
        try:
            ids = []
            for personality_data in data:
                if "id" not in personality_data.keys():
                    raise KeyError(f'"id" not found in {personality_data}')
                elif "document" not in personality_data.keys():
                    raise KeyError(f'"document" not found in {personality_data}')
                elif "metadata" not in personality_data.keys():
                    raise KeyError(f'"metadata" not found in {personality_data}')
                elif "type" not in personality_data["metadata"]:
                    raise KeyError(f'"type" not found in metadata {personality_data}')
                elif "attribute" not in personality_data["metadata"]:
                    raise KeyError(f'"attribute" not found in metadata {personality_data}')
                ids.append(personality_data["id"])
            # ensure id uniqueness
            if len(set(ids)) != len(ids):
                raise TypeError("Repeating IDs found, please make sure every 'id' entry is unique!")
        except KeyError as e:
            await ctx.send(error(f"Your data had an issue: {e}"))
            return
        except TypeError as e:
            await ctx.send(error(f"There was a problem with your ids:  {e}"))
            return
        except Exception as e:
            await ctx.send(error(f"Unknown error occured: {e}"))
            return

        # upload into database
        rag = self.rag_databases[ctx.guild.id]
        ids = [d["id"] for d in data]
        metadatas = [d["metadata"] for d in data]
        documents = [d["document"] for d in data]

        rag.insert_data("personality", documents, metadatas, ids=ids)
        await ctx.tick()

    @ai_rag.group(name="emoji")
    async def ai_rag_emoji(self, ctx: commands.Context):
        """
        Setup emoji database
        """
        pass

    @ai_rag_emoji.command(name="prompt")
    async def ai_rag_emoji_prompt(self, ctx: commands.Context):
        """
        Get a prompt for input into your assistant of choice to analyze emojis

        Use the `[p]ai rag emoji upload` command to upload emoji data after review.
        """
        guild = ctx.guild
        emojis = [f":{e.name}:" for e in guild.emojis]
        emoji_txt = "\n".join(emojis)
        prompt = await self.config.emoji_prompt()
        prompt = prompt.format(emoji_names=emoji_txt)

        file_io = StringIO(prompt)

        message_file = discord.File(file_io, filename="emoji_prompt.txt")
        await ctx.send(file=message_file)

    @ai_rag_emoji.command(name="analyze")
    async def ai_rag_emoji_analyze(self, ctx: commands.Context):
        """
        Uses configured general model to analyze emojis

        If you have a lot of emojis this may take some time.

        Use the `[p]ai rag emoji upload` command to upload emoji data after review.
        """
        guild = ctx.guild
        emojis = [f":{e.name}:" for e in guild.emojis]
        await ctx.send(info("Starting analysis..."))
        num_context = (await self.config.general_model_config())["num_ctx"]
        model = self.models["general"]

        prompt = await self.config.emoji_prompt()
        prompt_tokens = model.get_token_count(prompt)
        query = "Analyze the emojis."
        query_tokens = model.get_token_count(query)

        # stop = ["]"]
        result = []

        status_msg = "Progress: {}/{}"
        batches = self.recursive_chunk(model, emojis, num_context, prompt_tokens + query_tokens)
        status_obj = await ctx.send(info(status_msg.format(1, len(batches))))
        async with ctx.typing():
            for i, batch in enumerate(batches):
                try:
                    status_obj = await status_obj.edit(content=info(status_msg.format(i + 1, len(batches))))
                except:
                    pass
                current_prompt = prompt.format(emoji_names=batch)
                # get json response
                response = await model.get_model_response(
                    current_prompt,
                    query,
                    stats=self.stats["general"],
                )
                if not response:  # TODO: better error handling, tell user what happened
                    await ctx.send(error("There was an error getting model response."))
                    return
                # do some cleaning, models like to add json blocks or forget the closing ]
                pattern = r"```json\s*([\s\S]*?)(?:```|$)"
                clean_response = re.sub(pattern, r"\1", response, flags=re.DOTALL).strip()
                if clean_response[-1] != "]":
                    clean_response += "]"
                if clean_response[0] != "[":
                    clean_response = "[" + clean_response
                # convert to dict
                try:
                    data = json.loads(clean_response)
                except json.decoder.JSONDecodeError:
                    attach = discord.File(StringIO(response), filename="invalid_response.txt")
                    await ctx.send(f"Could not decode result json, see response attachment.", file=attach)
                    return
                result.extend(data)

        file_io = StringIO(json.dumps(result, indent=4))
        message_file = discord.File(file_io, filename="emoji_analysis.json")
        await ctx.reply(file=message_file, mention_author=True)

    @ai_rag_emoji.command(name="upload")
    async def ai_rag_emoji_upload(self, ctx: commands.Context):
        """
        Upload emoji json into RAG database.

        Your json must be in this format:
        ```json
        [
        {"emoji": ":party-cat:", "description": "A cat with a party hat, used to express excitement or celebration", "sentiment": "joyful/celebratory"},
        {"emoji": ":dance:", "description": "A cat dancing", "sentiment": "funny/cute"}
        ]
        ```
        """
        attachments = ctx.message.attachments
        if not attachments:
            await self.bot.send_help_for(ctx, "ai rag emoji upload")
            return
        json_file = attachments[0]
        try:
            data = json.loads(await json_file.read())
        except json.decoder.JSONDecodeError:
            await ctx.send(error("Invalid JSON file!"), delete_after=30)
            return

        # verify json
        try:
            for emoji_data in data:
                if "emoji" not in emoji_data.keys():
                    raise KeyError(f'"emoji" not found in {emoji_data}')
                elif "description" not in emoji_data.keys():
                    raise KeyError(f'"description" not found in {emoji_data}')
                elif "sentiment" not in emoji_data.keys():
                    raise KeyError(f'"sentiment" not found in {emoji_data}')
        except KeyError as e:
            await ctx.send(error(f"Your data had an issue: {e}"))
            return
        except Exception as e:
            await ctx.send(error(f"Unknown error occured: {e}"))
            return

        # upload into database
        rag = self.rag_databases[ctx.guild.id]
        metadata_format = get_metadata_format("emojis")  # {"name": "", "sentiment": ""}

        documents = [f"{e['emoji']} {e['description']} (sentiment: {e['sentiment']})" for e in data]
        ids = [f"{e['emoji']}" for e in data]
        metadatas: List[Dict[str, str]] = []
        for e in data:
            meta = metadata_format.copy()
            meta["name"] = e["emoji"]
            meta["sentiment"] = e["sentiment"]
            metadatas.append(meta)

        rag.insert_data("emojis", documents, metadatas, ids=ids)
        await ctx.tick()

    @commands.group(name="chatbot")
    @commands.guild_only()
    @checks.admin_or_permissions(administrator=True)
    async def chatbot(self, ctx):
        """
        Manage guild chatbot settings
        """
        pass

    @chatbot.command(name="welcomes")
    async def chatbot_welcome(self, ctx: commands.Context, enable: bool):
        """
        Enable bot welcomes on user join

        Will use one of the configured welcome prompts
        """
        await self.config.guild(ctx.guild).welcomes.set(enable)
        await ctx.tick()

    @chatbot.command(name="context")
    async def chatbot_context(self, ctx: commands.Context, *, time: str):
        """
        Set the max time for previous context messages to be included in the prompt.

        This means when generating a response, the bot will only include messages going back the time set.

        Time can be any natural language time delta:
        - 5 minutes
        - 10m
        - 1h
        ...
        """
        delta = parse_timedelta(time)
        if not delta:
            return await ctx.reply(error("Invalid time delta!"), delete_after=30, mention_author=False)
        await self.config.guild(ctx.guild).max_time.set(delta.total_seconds())
        await ctx.tick()

    @chatbot.command(name="timeout")
    async def chatbot_timeout(self, ctx: commands.Context, *, time: Optional[str] = None):
        """
        Set the guild-wide timeout that triggers after the bot is talking in a channel after some time.

        This is overridden by a channel's autoreply setting

        Timeout can be any natural language time delta:
        - 5 minutes
        - 10m
        - 1h
        ...
        """
        if time is None:
            curr = await self.config.guild(ctx.guild).timeout()
            return await ctx.send(info(f"Current timeout value: `{humanize_timedelta(seconds=curr)}`"), delete_after=60)

        delta = parse_timedelta(time)
        if not delta:
            return await ctx.reply(error("Invalid time delta!"), delete_after=30, mention_author=False)
        await self.config.guild(ctx.guild).timeout.set(delta.total_seconds())
        await ctx.tick()

    @chatbot.command(name="cooldown")
    async def chatbot_timeout_cooldown(self, ctx: commands.Context, *, time: Optional[str] = None):
        """
        Set the guild-wide cooldown after a timeout occurs.
        When a timeout occurs and the bot send their goodbye, they will not respond in that channel until the timeout cooldown expires

        Timeout can be any natural language time delta:
        - 5 minutes
        - 10m
        - 1h
        ...
        """
        if time is None:
            curr = await self.config.guild(ctx.guild).timeout_cooldown()
            return await ctx.send(
                info(f"Current timeout cooldown value: `{humanize_timedelta(seconds=curr)}`"), delete_after=60
            )

        delta = parse_timedelta(time)
        if not delta:
            return await ctx.reply(error("Invalid time delta!"), delete_after=30, mention_author=False)
        await self.config.guild(ctx.guild).timeout_cooldown.set(delta.total_seconds())
        await ctx.tick()

    @chatbot.command(name="learning-falloff")
    async def chatbot_learning_falloff(self, ctx: commands.Context, *, falloff_delta: Optional[str] = None):
        """
        Set the time interval for learned user traits to be cleaned from the database

        Learned user traits taken after this time will be removed from the database
        """
        if falloff_delta is None:
            curr = await self.config.guild(ctx.guild).user_learning_max_time()
            if curr == 0:
                await ctx.reply(info("No learning falloff time set."), delete_after=30, mention_author=False)
                return
            await ctx.reply(info(f"Fallout time: {humanize_timedelta(seconds=curr)}"))
            return

        delta = parse_timedelta(falloff_delta)
        if not delta:
            return await ctx.reply(error("Invalid time delta!"), delete_after=30, mention_author=False)
        await self.config.guild(ctx.guild).user_learning_max_time.set(delta.total_seconds())
        await ctx.tick()

    @chatbot.group(name="blacklist")
    async def chatbot_blacklist(self, ctx: commands.Context):
        """
        Manage automatic user learning channel blacklist
        """
        pass

    @chatbot_blacklist.command(name="add")
    async def chatbot_blacklist_add(
        self, ctx: commands.Context, channel: Union[discord.TextChannel, discord.VoiceChannel, discord.Thread]
    ):
        """
        Add a channel to the blacklist
        """
        async with self.config.guild(ctx.guild).learning_blacklist() as learning_blacklist:
            if channel.id not in learning_blacklist:
                learning_blacklist.append(channel.id)
            else:
                await ctx.reply(
                    warning(f"{channel.mention} is already in the blacklist!"), mention_author=False, delete_after=30
                )
        await ctx.tick()

    @chatbot_blacklist.command(name="del")
    async def chatbot_blacklist_del(
        self, ctx: commands.Context, channel: Union[discord.TextChannel, discord.VoiceChannel, discord.Thread]
    ):
        """
        Remove a channel to the blacklist
        """
        async with self.config.guild(ctx.guild).learning_blacklist() as learning_blacklist:
            if channel.id in learning_blacklist:
                learning_blacklist.remove(channel.id)
            else:
                await ctx.reply(
                    warning(f"{channel.mention} is not in the blacklist!"), mention_author=False, delete_after=30
                )
        await ctx.tick()

    @chatbot_blacklist.command(name="list")
    async def chatbot_blacklist_list(self, ctx: commands.Context):
        """
        Add a channel to the blacklist
        """
        async with self.config.guild(ctx.guild).learning_blacklist() as learning_blacklist:
            if not learning_blacklist:
                await ctx.send(info("No channels configured."), delete_after=30)
                return
            msg = "## User Learning Blacklist\n"
            for channel_id in learning_blacklist:
                channel = ctx.guild.get_channel_or_thread(channel_id)
                if channel:
                    msg += f"- {channel.mention}\n"

        for page in pagify(msg):
            await ctx.send(page)

    @chatbot.group(name="channel")
    async def chatbot_channel(self, ctx):
        """
        Manage channel settings
        """
        pass

    @chatbot_channel.command(name="autoreply")
    async def chatbot_channel_reply(
        self,
        ctx: commands.Context,
        channel: Union[discord.TextChannel, discord.VoiceChannel, discord.Thread],
        on_off: bool,
    ):
        """
        Turn on autoreply in channel
        """
        await self.config.channel(channel).autoreply.set(on_off)
        await ctx.tick()

    @chatbot_channel.command(name="random")
    async def chatbot_channel_random(
        self,
        ctx: commands.Context,
        channel: Union[discord.TextChannel, discord.VoiceChannel, discord.Thread],
        randomness: Optional[float] = None,
    ):
        """
        Set the percent chance for the bot to reply in channel
        Run with no value to see the current value.

        Once the random chance occurs, the bot will continue replying in the channel until the channel's `timeout` is reached.

        Value should be in the range of [0, 1)
        """
        if randomness is None:
            curr = await self.config.channel(channel).randomness()
            return await ctx.send(info(f"Current randomness value for {channel.mention}: `{curr}`"), delete_after=60)
        elif randomness < 0 or randomness >= 1:
            return await ctx.send(error("Randomness cannot be < 0 or >= 1."), delete_after=60)
        await self.config.channel(channel).randomness.set(randomness)
        await ctx.tick()

    @chatbot_channel.command(name="timeout")
    async def chatbot_channel_timeout(
        self,
        ctx: commands.Context,
        channel: Union[discord.TextChannel, discord.VoiceChannel, discord.Thread],
        timeout: Optional[str] = None,
    ):
        """
        Number of seconds for bot to stop replying to messages after being randomly triggered to reply in a channel
        Leave empty to get the current value.

        Timeout can be any natural language time delta:
        - 5 minutes
        - 10m
        - 1h
        ...
        """
        if timeout is None:
            curr = await self.config.channel(channel).timeout()
            return await ctx.send(info(f"Current timeout for {channel.mention}: {humanize_timedelta(seconds=curr)}"))
        delta = parse_timedelta(timeout)
        if not delta:
            return await ctx.reply(error("Invalid timeout delta!"), delete_after=30, mention_author=False)
        await self.config.channel(channel).timeout.set(delta.total_seconds())
        await ctx.tick()

    @chatbot_channel.group(name="revive")
    async def chatbot_channel_revive(self, ctx):
        """
        Dead chat reviver settings
        """
        pass

    @chatbot_channel_revive.command(name="time")
    async def chatbot_channel_revive_time(self, ctx, *, time: str):
        """
        Set the time for chat to be dead to revive it

        Time can be any natural language time delta:
        - 5 minutes
        - 10m
        - 1h
        ...
        """
        delta = parse_timedelta(time)
        if not delta:
            return await ctx.reply(error("Invalid time delta!"), delete_after=30, mention_author=False)
        await self.config.guild(ctx.guild).dead_revive_time.set(delta.total_seconds())
        await ctx.tick()

    @chatbot_channel_revive.command("add")
    async def chatbot_channel_revive_add(self, ctx, *, channel: discord.TextChannel):
        """
        Add a channel to revive when dead
        """
        async with self.config.guild(ctx.guild).dead_channels() as dead:
            if channel.id not in dead:
                dead.append(channel.id)

        await ctx.tick()

    @chatbot_channel_revive.command("del")
    async def chatbot_channel_revive_del(self, ctx, *, channel: discord.TextChannel):
        """
        Delete a channel from the revive list
        """
        async with self.config.guild(ctx.guild).dead_channels() as dead:
            try:
                dead.remove(channel.id)
            except:
                pass

        await ctx.tick()

    @chatbot_channel_revive.command("list")
    async def chatbot_channel_revive_list(self, ctx):
        """
        List revive channels
        """
        msg = "# Revive Channel List:\n"
        async with self.config.guild(ctx.guild).dead_channels() as dead:
            msg += "\n".join(
                [
                    ctx.guild.get_channel_or_thread(c).mention if ctx.guild.get_channel_or_thread(c) is not None else ""
                    for c in dead
                ]
            )

        for page in pagify(msg):
            await ctx.send(page)

    @commands.command(name="aistats")
    async def ai_stats(self, ctx):
        """
        See some stats on my chatbot!
        """
        msg = ""
        for name, stats in self.stats.items():
            msg += f"### {name}\n"
            if stats["num_responses"] <= 0:
                msg += "- No stats yet.\n"
                continue

            avg_response = stats["total_response_time"] / stats["num_responses"]
            msg += f"- Average response time: `{avg_response:.4f}`"
            if stats["prompt_eval_duration"] > 0:
                avg_prompt_eval = stats["prompt_eval_count"] / stats["prompt_eval_duration"]
                msg += f"- Average Prompt Evaluation Speed: `{avg_prompt_eval:.4f}`"
            await ctx.send(msg)

    @commands.hybrid_command(name="compliment")
    @commands.guild_only()
    async def compliment(self, ctx: commands.Context, member: Optional[discord.Member] = None):
        """
        Complement a user or yourself.
        """
        if not member:
            member = ctx.author
        prompt = await self.config.compliment_prompt()
        model = self.models["general"]
        num_context = (await self.config.summarize_model_config())["num_ctx"]
        rag = self.rag_databases[ctx.guild.id]
        user_profile = rag.get_data("", "users", min_similarity=0.05, where={"user_id": f"{member.id}"})["documents"]
        user_profile = user_profile if user_profile else ("(no profile)")
        user_query = "Give me a relevant compliment."
        should_qa = await self.config.allow_qa()
        if await self.config.global_lock():
            async with self.global_lock:
                async with ctx.typing():
                    compliment_prompt = prompt.format(user_profile="\n".join(user_profile))
                    if model.get_token_count(prompt) > num_context:
                        compliment_prompt = prompt.format(user_profile={"(no profile)"})
                    chatbot_response = await model.get_model_response(
                        compliment_prompt,
                        user_query,
                        stats=self.stats["general"],
                    )  # .strip("Compliment:")
                    msg = await ctx.send(inline(chatbot_response))
        else:
            async with ctx.typing():
                compliment_prompt = prompt.format(user_profile="\n".join(user_profile))
                if model.get_token_count(prompt) > num_context:
                    compliment_prompt = prompt.format(user_profile={"(no profile)"})
                chatbot_response = await model.get_model_response(
                    compliment_prompt,
                    user_query,
                    stats=self.stats["general"],
                )  # .strip("Compliment:")
                msg = await ctx.send(inline(chatbot_response))

        if should_qa:
            data = self.qa_data_template.copy()
            data["message_id"] = msg.id
            data["user"] = ctx.author.id
            data["channel"] = ctx.channel.id
            data["guild"] = ctx.guild.id
            data["prompt"] = prompt
            data["user_query"] = user_query
            data["response"] = chatbot_response
            start_adding_reactions(msg, QA_EMOJIS)
            self.qa_data[(msg.id, ctx.channel.id)] = data

    @commands.hybrid_command(name="dadjoke")
    @commands.guild_only()
    async def dad_joke(self, ctx: commands.Context):
        """
        Get a dadjoke!
        """
        prompt = await self.config.dadjoke_prompt()
        model = self.models["general"]
        should_qa = await self.config.allow_qa()
        user_query = "Generate a funny dad joke."
        if await self.config.global_lock():
            async with self.global_lock:
                async with ctx.typing():
                    chatbot_response = await model.get_model_response(
                        prompt,
                        user_query,
                        stats=self.stats["general"],
                    )
                    msg = await ctx.send(inline(chatbot_response))
        else:
            async with ctx.typing():
                chatbot_response = await model.get_model_response(
                    prompt,
                    user_query,
                    stats=self.stats["general"],
                )
                msg = await ctx.send(inline(chatbot_response))

        if should_qa:
            data = self.qa_data_template.copy()
            data["message_id"] = msg.id
            data["user"] = ctx.author.id
            data["channel"] = ctx.channel.id
            data["guild"] = ctx.guild.id
            data["prompt"] = prompt
            data["user_query"] = user_query
            data["response"] = chatbot_response
            start_adding_reactions(msg, QA_EMOJIS)
            self.qa_data[(msg.id, ctx.channel.id)] = data

    @commands.hybrid_command(name="summary")
    @checks.mod_or_permissions(administrator=True)
    @commands.guild_only()
    async def summary(
        self,
        ctx: commands.Context,
        channel: Union[discord.TextChannel, discord.VoiceChannel, discord.Thread],
        num_messages: Optional[int] = None,
        *,
        topic: Optional[str] = None,
    ):
        """
        Generate summaries of chats, going back `num_messages` number of messages.
        If `num_messages` is unset, summarize the whole channel (or thread).

        This is meant more for text chat based meetings.

        If you are summarizing a large number of messages this may take a while to run completely.

        Partial summaries are generated if the number of messages exceeds the model's context length.

        Messages are formatted as follows for the model:
        <message_id> <username>: <content>
        """
        if not topic:
            topic = channel.name
        model = self.models["summarize"]
        num_context = (await self.config.summarize_model_config())["num_ctx"]

        summary_prompt = await self.config.summarize_prompt()
        partial_prompt = await self.config.partial_summary_prompt()

        try:
            messages = [m async for m in channel.history(limit=num_messages)]
        except discord.Forbidden:
            await ctx.reply(error(f"I am unable to access {channel.mention}, please check my permissions."))
            return

        messages.reverse()
        message_lines = [f"{m.id} {m.author.display_name}: {m.content.strip()}" for m in messages if m.content.strip()]

        lock = self.global_lock if (await self.config.global_lock()) else asyncio.Lock()
        ## helper function to fill in message jump links
        message_pattern = re.compile(r"(?:\(\s*|,\s*|-\s*)(\d+)")

        def add_jumplinks(output: str):
            for mid in set(message_pattern.findall(output)):
                jumplink = "https://discord.com/channels/{guild_id}/{{channel_id}}/{message_id}".format(
                    guild_id=ctx.guild.id,
                    message_id=mid,
                )
                output = output.replace(str(mid), jumplink)
            # if a thread, channel_id can be a message_id so this ensures replacement works correctly
            output = output.format(channel_id=channel.id)
            return output

        async with lock:
            async with ctx.typing():
                messages_str = "\n".join(message_lines)
                prompt_tokens = model.get_token_count(summary_prompt)
                partial_prompt_tokens = model.get_token_count(partial_prompt)
                message_tokens = model.get_token_count(messages_str)
                total = prompt_tokens + message_tokens

                if total <= num_context:
                    # print("full summary")
                    prompt = summary_prompt.format(
                        topic=topic,
                        chat_messages=messages_str,
                        partial_summaries="(no summaries)",
                    )
                    # print(prompt)
                    full_summary = await model.get_model_response(
                        prompt,
                        "Genereate the summary.",
                        stats=self.stats["summarize"],
                    )
                    # print(full_summary)
                    full_summary = add_jumplinks(full_summary)
                    for page in pagify(full_summary):
                        await ctx.send(page)
                    return

                # print("using partial summaries")
                partial_message_chunks = self.recursive_chunk(model, message_lines, num_context, partial_prompt_tokens)
                final_chunk = partial_message_chunks.pop()
                # print(partial_message_chunks)
                partial_summaries = [
                    await model.get_model_response(
                        partial_prompt.format(topic=topic, chat_messages=chunk),
                        "Generate the partial summary.",
                        stats=self.stats["summarize"],
                    )
                    for chunk in partial_message_chunks
                ]
                final_summary = summary_prompt.format(
                    topic=topic,
                    chat_messages=final_chunk,
                    partial_summaries="\n".join(partial_summaries),
                )
                final_summary = add_jumplinks(final_summary)
                output = await model.get_model_response(
                    final_summary,
                    "Generate the summary.",
                    stats=self.stats["summarize"],
                )
                for page in pagify(output):
                    await ctx.send(page)

    @commands.hybrid_command(name="tldr")
    @commands.guild_only()
    @checks.mod_or_permissions(administrator=True)
    async def tldr(
        self,
        ctx: commands.Context,
        channel: Union[discord.TextChannel, discord.VoiceChannel, discord.Thread],
        num_messages: int,
    ):
        """
        Genereate a TL;DR for messages in a channel

        Will error out if the number of messages exceeds the context length set.
        """
        model = self.models["summarize"]
        tldr_prompt = await self.config.tldr_prompt()
        num_context = (await self.config.summarize_model_config())["num_ctx"]
        lock = self.global_lock if (await self.config.global_lock()) else asyncio.Lock()
        async with lock:
            async with ctx.typing():
                try:
                    messages = [m async for m in channel.history(limit=num_messages)]
                except discord.Forbidden:
                    await ctx.reply(error(f"I am unable to access {channel.mention}, please check my permissions."))
                    return
                messages.reverse()
                messages = [f"{m.id} {m.author.display_name}: {m.content}" for m in messages if m.content]
                messages_str = "\n".join(messages)

                prompt = tldr_prompt.format(guild_id=ctx.guild.id, channel_id=channel.id, messages=messages_str)
                tokens = model.get_token_count(prompt)
                if tokens > num_context:
                    return await ctx.send(error("Too many messages for me to process!"))
                output = await model.get_model_response(
                    prompt,
                    "Generate the TLDR.",
                    stats=self.stats["summarize"],
                )
                message_pattern = re.compile(r"(?:\(\s*|,\s*|-\s*)(\d+)")
                # print(output)

                def add_jumplinks(output: str):
                    for mid in set(message_pattern.findall(output)):
                        jumplink = "https://discord.com/channels/{guild_id}/{{channel_id}}/{message_id}".format(
                            guild_id=ctx.guild.id,
                            message_id=mid,
                        )
                        output = output.replace(str(mid), jumplink)
                    # if a thread, channel_id can be a message_id so this ensures replacement works correctly
                    output = output.format(channel_id=channel.id)
                    return output

                for page in pagify(add_jumplinks(output)):
                    await ctx.send(page)

    async def _debounced_reply(self, message: discord.Message):  # UNUSED
        channel = message.channel
        author = message.author
        guild = message.guild
        key = (channel.id, author.id)

        # How long to wait after last typing event before replying
        TYPING_TIMEOUT = 6
        MESSAGE_TIMEOUT = 10
        try:
            while True:
                # Wait for a typing event in this channel by this user
                # await self.bot.wait_for(
                #    "typing",
                #    check=lambda ch, usr, when: (ch.id == channel.id and usr.id == author.id),
                #    timeout=TYPING_TIMEOUT,
                # )

                # now wait for the message
                await self.bot.wait_for(
                    "message",
                    check=lambda msg: (msg.channel.id == channel.id and msg.author.id == author.id),
                    timeout=MESSAGE_TIMEOUT,
                )
                # print("big reply")
                await asyncio.sleep(1)
        except asyncio.TimeoutError:
            # No typing for IDLE_TIMEOUT seconds → time to respond
            # print("big timeout")
            pass
        except asyncio.CancelledError:
            # print("get cancelled")
            # A new message arrived and cancelled us → just exit
            return

        # Clean up our pending entry
        self.pending.pop(key, None)

        # Now actually generate & send the bot’s reply
        lock = self.channel_lock[channel.id]
        should_qa = await self.config.allow_qa()
        # time to chat
        async with (
            lock
        ):  # TODO: maybe this should lock above otherwise other messages might slip through from other people
            async with channel.typing():
                # since the current message just got added to the history, don't include it in history since it will be the user query
                response = await self.chat(guild, message, self.history[channel.id][:-1], return_qa=should_qa)
                if response is None:
                    return await channel.send("Sorry, my brain encountered an error, please try again later.")
                if should_qa and isinstance(response, dict):
                    msg = await channel.send(response["response"])
                    response["message_id"] = msg.id
                    self.qa_data[(msg.id, channel.id)] = response
                    try:
                        start_adding_reactions(msg, QA_EMOJIS)
                    except:
                        pass
                else:
                    msg = await channel.send(response)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        channel = message.channel
        if isinstance(channel, discord.abc.PrivateChannel):
            # don't support dms right now
            return
        guild = channel.guild
        if guild is None or await self.bot.cog_disabled_in_guild(self, guild):
            return

        # if theres no text or the content is just an embedded link, return (for now)
        if not message.content:
            return
        URL_REGEX = re.compile(r"https?://\S+")
        if bool(URL_REGEX.fullmatch(message.content.strip())):
            return

        # dont add bot commands to history
        prefixes = await self.bot.get_valid_prefixes()
        if message.content and message.content[0] in prefixes:
            return

        await self.update_internal_history(message)
        # dont respond to myself or other bots
        if message.author == guild.me or message.author.bot:
            return

        auto_learn = await self.config.user_learning_enabled()
        key = (message.author.id, guild.id)
        if auto_learn and len(self.user_historys.get(key, [])) >= MAX_USER_HISTORY_QUEUE:
            self.auto_user_history_tasks.append(
                asyncio.create_task(
                    self.process_user_history(message.author),
                )
            )

        # TODO: for testing, remove
        if channel.id not in [1367715420081229855, 532724833981562890, 703281764923211846]:
            return

        lock = self.channel_lock[channel.id]
        # if the lock is already taken, end after updating history
        if lock.locked():
            return
        # check global lock
        if (await self.config.global_lock()) and self.global_lock.locked():
            return
        # lock is free
        # if bot is not currently talking in the channel, perform checks on whether to start a conversation
        if channel.id not in self.talking_channels:
            autoreply = await self.config.channel(channel).autoreply()
            randomness = await self.config.channel(channel).randomness()
            if message.reference is not None and isinstance(message.reference.resolved, discord.Message):
                ref_message = message.reference.resolved
            else:
                ref_message = None
            # if either of these are true, start talking in the channel, or if mentioned explicition / replied to
            if (
                autoreply
                or random.random() < randomness
                or guild.me in message.mentions
                or (ref_message and ref_message.author == guild.me)
            ):
                self.talking_channels[channel.id] = message.created_at

        if channel.id not in self.talking_channels:
            return

        # Now actually generate & send the bot’s reply
        lock = self.channel_lock[channel.id]
        should_qa = await self.config.allow_qa()
        # time to chat
        async with lock:
            async with channel.typing():
                # since the current message just got added to the history, don't include it in history since it will be the user query
                response = await self.chat(guild, message, self.history[channel.id][:-1], return_qa=should_qa)
                if response is None:
                    return await channel.send("Sorry, my brain encountered an error, please try again later.")
                response_str = response if isinstance(response, str) else response["response"]
                if response_str == "[NO_REPLY]":
                    # bot shouldn't reply, return
                    return
                if should_qa and isinstance(response, dict):
                    msg = await channel.send(response["response"], reference=message, mention_author=False)
                    response["message_id"] = msg.id
                    self.qa_data[(msg.id, channel.id)] = response
                    try:
                        start_adding_reactions(msg, QA_EMOJIS)
                    except:
                        pass
                else:
                    msg = await channel.send(response)

    @commands.Cog.listener()
    async def on_reaction_add(self, reaction: discord.Reaction, member: Union[discord.Member, discord.User]):
        ### log QA data
        message = reaction.message
        channel = message.channel
        guild = message.guild
        if not guild:
            return
        if message.author != guild.me:
            return
        try:
            if str(reaction.emoji) == QA_EMOJIS[0]:
                self.qa_data[(message.id, channel.id)]["approval_reactions"] += 1
            elif str(reaction.emoji) == QA_EMOJIS[1]:
                self.qa_data[(message.id, channel.id)]["disapproval_reactions"] += 1
        except Exception as e:
            pass

    @commands.Cog.listener()
    async def on_reaction_remove(self, reaction: discord.Reaction, member: Union[discord.Member, discord.User]):
        ### log QA data
        message = reaction.message
        channel = message.channel
        guild = message.guild
        if not guild:
            return
        if message.author != guild.me:
            return
        try:
            if str(reaction.emoji) == QA_EMOJIS[0]:
                self.qa_data[(message.id, channel.id)]["approval_reactions"] -= 1
            elif str(reaction.emoji) == QA_EMOJIS[1]:
                self.qa_data[(message.id, channel.id)]["disapproval_reactions"] -= 1
        except Exception as e:
            pass

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        guild = member.guild
        if await self.bot.cog_disabled_in_guild(self, guild):
            return
        welcome_users = await self.config.guild(guild).welcomes()
        if not welcome_users:
            return

        channel = guild.system_channel
        if not channel:
            return

        welcome_prompt = await self.config.other_chat_prompts()
        welcome_prompt = random.choice(welcome_prompt["welcome"])
        welcome_prompt = welcome_prompt.format_map(SafeFormat(username=member.mention))

        # Now actually generate & send the bot’s reply
        lock = self.channel_lock[channel.id]
        should_qa = await self.config.allow_qa()
        # time to chat
        async with lock:
            async with channel.typing():
                # since the current message just got added to the history, don't include it in history since it will be the user query
                response = await self.chat(
                    guild,
                    f"Welcome {member.mention} to the community.",
                    override_prompt=welcome_prompt,
                    return_qa=should_qa,
                )
                if response is None:
                    return
                response_str = response if isinstance(response, str) else response["response"]
                if should_qa and isinstance(response, dict):
                    msg = await channel.send(response_str)
                    response["message_id"] = msg.id
                    self.qa_data[(msg.id, channel.id)] = response
                    try:
                        start_adding_reactions(msg, QA_EMOJIS)
                    except:
                        pass
                else:
                    await channel.send(response_str)

    async def red_delete_data_for_user(
        self,
        *,
        requester: Literal["discord_deleted_user", "owner", "user", "user_strict"],
        user_id: int,
    ):
        pass
