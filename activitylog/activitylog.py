# redbot/discord
from tokenize import String
from discord.user import User
from discord.member import Member
from networkx import Graph
from redbot.core.utils.chat_formatting import *
from redbot.core import Config, checks, commands, modlog, bank
from redbot.core.data_manager import cog_data_path
from redbot.core.utils.mod import is_mod_or_superior
from redbot.core.utils.predicates import MessagePredicate
from redbot.core.commands.converter import parse_timedelta
import discord

from .utils import *
from .database import DatabaseHandler
from .export import ChatHTMLExporter
from .data import (
    plot_voice_time_by_channel,
    plot_text_activity_over_time,
    plot_guild_joins_and_leaves,
    plot_users_in_voice_channel,
    plot_hourly_heatmap,
    plot_retention,
    build_interaction_graph,
)
from .menus import LogView, GraphView
from datetime import datetime, timedelta
from dateutil.tz import tzlocal
from glob import glob
import time
import os
import asyncio
from typing import Literal, Optional, Union, Any, Sequence, List, Deque
from collections import deque
from io import BytesIO, StringIO
import csv
import re

AUDIT_QUEUE_LEN = 100
LOG_MSG = "[Activitylog] {}"
ID_FINDER = re.compile(r"\(id\s*(\d+)\)")


class ActivityLogger(commands.Cog):
    """Log all activities seen by bot"""

    __version__ = "1.1.0"

    def __init__(self, bot):
        super().__init__()
        self.data_path = cog_data_path(cog_instance=self)

        self.bot = bot
        self.config = Config.get_conf(self, identifier=9584736583, force_registration=True)
        default_global = {
            "attrs": {
                "attachments": False,
                "default": False,
                "direct": False,
                "everything": False,
                "check_audit": True,
            },
            "database_config": {
                "backend": "sqlite",
                "username": None,
                "password": None,
                "host": "localhost",
                "port": 3306,
            },
        }
        self.default_guild = {
            "all_s": False,
            "voice": False,
            "events": False,
            "attachment_channel": None,
            "prefixes": [],
            "corr_weights": {
                "reply": 1,
                "messages": [
                    1,
                    0.8,
                    0.6,
                    0.4,
                    0.2,
                    0.1,
                ],  # in order of closest to farthest
                "vc_per_minute": 1,
                "vc_people_multiplier": 0.5,
            },
        }
        self.default_channel = {"enabled": False}
        default_user = {"past_names": []}
        default_member = {
            "stats": {
                "total_msg": 0,
                "bot_cmd": 0,
                "avg_len": 0.0,
                "vc_time_sec": 0.0,
                "last_vc_time": None,
            }
        }
        self.config.register_global(**default_global)
        self.config.register_guild(**self.default_guild)
        self.config.register_channel(**self.default_channel)
        self.config.register_user(**default_user)
        self.config.register_member(**default_member)

        self.database_handlers: Dict[Union[int, str], DatabaseHandler] = {}
        # used to store what we should log to avoid constant config calls
        self.cache = {}
        # used to cache audit log entries seen by the bot for logging purposes
        self.audit_logs: Dict[int, Deque[discord.AuditLogEntry]] = {}

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

        # remove userinfo since we are replacing it
        self.bot.remove_command("userinfo")
        self.is_initalized = False
        self.load_task = asyncio.create_task(self.initialize())

    def cog_unload(self):
        try:
            self.load_task.cancel()
        except:
            pass
        for handler in self.database_handlers.values():
            try:
                handler.close()
            except Exception as e:
                print(LOG_MSG.format(f"Failed to close database handler: {e}"))

    def initialize_databases(self, conf: dict):
        # key ids for these should be ints
        self.is_initalized = False
        for guild in self.bot.guilds:
            try:
                if conf["backend"] == "sqlite":
                    handler = DatabaseHandler(str(guild.id), data_path=str(self.data_path))
                elif conf["backend"] == "mysql":
                    handler = DatabaseHandler(str(guild.id), **conf)
                else:  # shouldn't happen
                    handler = None
                self.database_handlers[guild.id] = handler
                self.audit_logs[guild.id] = deque(maxlen=AUDIT_QUEUE_LEN)
            except Exception as e:
                print(LOG_MSG.format(f"Failed to load database for {guild}! {e}"))
                return False
        try:
            # add handler for global bot logs
            if conf["backend"] == "sqlite":
                handler = DatabaseHandler(str("global"), data_path=str(self.data_path))
            elif conf["backend"] == "mysql":
                handler = DatabaseHandler(str("global"), **conf)
            else:
                handler = None
            self.database_handlers["global"] = handler
        except Exception as e:
            print(LOG_MSG.format(f"Failed to load database for global! {e}"))
            return False

        self.is_initalized = True
        return True

    async def initialize(self):
        await self.bot.wait_until_ready()
        database_conf = await self.config.database_config()
        self.initialize_databases(database_conf)

        self.cache = await self.config.attrs()
        guild_data = await self.config.all_guilds()
        channel_data = await self.config.all_channels()

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

    async def get_audit_entry(
        self, guild: Union[discord.Guild, None], *conditions
    ) -> Union[discord.AuditLogEntry, None]:
        if guild is None:
            return None
        cached_entries = self.audit_logs[guild.id]
        # it seems that cached entries wont contain the updated audit event right when it happens, it seems to fire after the event handler that is in question, may help with high traffic bots though
        for entry in cached_entries:
            if entry is not None:
                if all(cond(entry) for cond in conditions):
                    return entry

        # fallback to look at audit log for qthe guild
        # print("firing get_audit_entry")
        # print(len(conditions))
        if self.cache["check_audit"]:
            # try:
            async for entry in guild.audit_logs(limit=3):
                # print(entry)
                # for i, cond in enumerate(conditions):
                # print(str(i), cond(entry))
                if all(cond(entry) for cond in conditions):
                    return entry
            # except discord.Forbidden:
            #    return None
            # except discord.HTTPException:
            #    return None
            # finally:
            #    return None
        else:
            return None

    def update_cache(
        self,
        attr: str,
        value: Any,
        level: Union[discord.Guild, discord.abc.GuildChannel, str] = "global",
    ):
        """
        Updates cache with new configuration entry

        Args:
            attr (str): name of the config option
            value (Any): value to set
            level (Union[discord.Guild, discord.abc.GuildChannel, str], optional): Level to save to. Defaults to "global".
        """
        if isinstance(level, str) and level == "global":
            self.cache[attr] = value
        if isinstance(level, discord.Guild):
            self.cache[level.id][attr] = value
        if isinstance(level, discord.abc.GuildChannel):
            self.cache[level.id][attr] = value

    def should_log(
        self,
        location: Union[
            discord.Guild,
            discord.ForumChannel,
            discord.abc.GuildChannel,
            discord.DMChannel,
            discord.Thread,
            discord.User,
        ],
    ) -> bool:
        if not self.cache or not self.is_initalized:
            # cache is empty, still booting
            return False

        if self.cache.get("everything", False):
            return True

        default = self.cache.get("default", False)

        if type(location) is discord.Guild:
            loc = self.cache[location.id]
            return loc.get("all_s", False) or loc.get("events", default)

        elif type(location) is discord.TextChannel or type(location) is discord.Thread:
            if type(location) == discord.Thread:
                location = location.parent
            loc = self.cache[location.guild.id]
            opts = [
                loc.get("all_s", False),
                self.cache[location.id].get("enabled", default),
            ]
            return any(opts)

        elif type(location) is discord.VoiceChannel:
            loc = self.cache[location.guild.id]
            opts = [loc.get("all_s", False), loc.get("voice", False)]

            return any(opts)

        elif isinstance(location, discord.abc.PrivateChannel) or isinstance(location, discord.User):
            return self.cache.get("direct", default)

        else:  # can't log other types
            return False

    def should_download(self, msg: discord.Message, check_guild_attach_channel: Optional[bool] = False) -> bool:
        """
        Checks if we should download the attachment in a message

        Args:
            msg (discord.Message): Message containing attachments
            check_guild_attach_channel (bool, optional): Check if there is a guild attachments channel to save to. Defaults to False.

        Returns:
            bool: Whether downloads are enabled or not
        """
        if check_guild_attach_channel:
            if not msg.guild:
                return False
            return (
                self.should_log(msg.channel)
                and self.cache.get(msg.guild.id, {}).get("attachment_channel", None) is not None
                and msg.channel.id != self.cache.get(msg.guild.id, {}).get("attachment_channel", None)
            )
        else:
            return self.should_log(msg.channel) and self.cache.get("attachments", False)

    async def process_attachments(self, message: discord.Message):
        """
        Processes attachments in a message, and saves attachments if enabled

        Args:
            message (discord.Message): Message to process attachment for
            a (discord.Attachment): Message attachment to process

        Returns:

        """
        channel = message.channel
        attachments = message.attachments
        path = self.data_path

        if type(channel) in [discord.TextChannel, discord.VoiceChannel, discord.Thread]:
            guildid = channel.guild.id
        elif isinstance(channel, discord.abc.PrivateChannel):
            guildid = "direct"
        else:
            guildid = None

        if guildid is None:
            print(LOG_MSG.format(f"Unable to get guildid in process_attachments. Type of channel: {type(channel)}"))
            return []

        data = {
            "id": None,
            "message_id": message.id,
            "attachment_message_id": None,
            "url": None,
            "filepath": None,
        }
        all_data = []
        for att in attachments:
            full_path = None
            url = None
            attachment_message_id = None
            if self.should_download(message):
                filepath = os.path.join(path, str(guildid), str(channel.id) + "_attachments")
                os.makedirs(filepath, exist_ok=True)
                filename = str(att.id) + "_" + att.filename
                full_path = os.path.join(filepath, filename)
                with open(full_path, "wb") as f:
                    try:
                        await att.save(f)
                    except:
                        pass  # TODO put error handling
            if self.should_download(message, True):
                save_channel_id: int = self.cache.get(guildid, {}).get("attachment_channel", None)
                channel = message.guild.get_channel_or_thread(save_channel_id)
                if channel and type(channel) not in [discord.ForumChannel, discord.CategoryChannel]:
                    try:
                        f = await att.to_file()
                        download_msg = await channel.send(file=f)
                        url = download_msg.attachments[0].url
                        attachment_message_id = download_msg.id
                    except Exception as e:
                        print(LOG_MSG.format(f"Error sending file to guild channel attachment holder! {e}"))
                        url = att.url
                else:
                    url = att.url
            else:
                url = att.url

            new_data = data.copy()
            new_data["id"] = att.id
            new_data["url"] = url
            new_data["filepath"] = full_path
            new_data["attachment_message_id"] = attachment_message_id
            all_data.append(new_data)
        # process stickers
        for sticker in message.stickers:
            # ids can duplicate so generated a new one
            new_data = data.copy()
            new_data["id"] = generate_unique_id()
            new_data["url"] = sticker.url
            all_data.append(new_data)
        return all_data

    async def process_message(
        self,
        message: discord.Message,
        after: Optional[discord.Message] = None,
        deleted_by: Optional[discord.Member] = None,
    ):
        """
        Processes a message for logging
        """
        attachments_rows = await self.process_attachments(message)
        channel = message.channel
        author = message.author

        if message.reference:
            reference_id = message.reference.message_id
        else:
            reference_id = None

        # Update member stats -- don't calculate bot stats and make sure this isnt dm message
        if message.author.id != self.bot.user.id and isinstance(message.author, discord.Member):
            is_bot_msg = False
            async with self.config.member(message.author).stats() as stats:
                stats["total_msg"] += 1
                content = after.content if after is not None else message.content
                if len(content) > 0:
                    for prefix in self.cache[message.guild.id]["prefixes"]:
                        if prefix == content[: len(prefix)]:
                            stats["bot_cmd"] += 1
                            is_bot_msg = True
                            break
                    if not is_bot_msg:
                        stats["avg_len"] += len(content.split(" "))

        msg_data = {
            "message_id": message.id,
            "channel_id": channel.id,
            "author_id": author.id,
            "datetime": message.created_at,
            "edited_datetime": after.edited_at if after else None,
            "content": message.content,
            "edited_content": after.content if after else None,
            "reference_id": reference_id,
            "deleted_by_id": deleted_by.id if deleted_by else None,
        }
        return msg_data, attachments_rows

    async def process_voice(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        action = None
        state = None
        moved_to_id = None
        channel = before.channel if before.channel is not None else after.channel

        if before.channel != after.channel:
            if before.channel:
                async with self.config.member(member).stats() as stats:
                    if stats["last_vc_time"]:  # incase someone joins when bot is offline
                        stats["vc_time_sec"] += time.time() - stats["last_vc_time"]
                        stats["last_vc_time"] = None
                action = "leave"
                if after.channel:
                    action = "move"
                    moved_to_id = after.channel.id
                state = True
            elif after.channel:
                action = "join"
                async with self.config.member(member).stats() as stats:
                    stats["last_vc_time"] = time.time()
                state = True
        else:
            # there should only be one updated flag
            action, state = get_voice_flags(before, after)

        voice_data = {
            "datetime": discord.utils.utcnow(),
            "author_id": member.id,
            "channel_id": channel.id,
            "action_type": action,
            "state": state,
            "moved_to_id": moved_to_id,
        }

        return voice_data

    def process_audit(
        self,
        action: str,
        category: str,
        author: Union[discord.Member, discord.User, int],
        attribute: str,
        before: Any,
        after: Any,
        audit: Optional[discord.AuditLogEntry] = None,
        force_new_id: Optional[bool] = False,
    ):
        audit_data = {
            # always generate a new id because of issues with duplicate audit ids from discord
            "id": generate_unique_id(),  # audit.id if audit and not force_new_id else generate_unique_id(),
            "datetime": audit.created_at if audit else discord.utils.utcnow(),
            "action": action,
            "category": category,
            "author_id": author if isinstance(author, int) else author.id,
            "attribute": attribute,
            "before": before,
            "after": after,
            "extra": str(audit.extra) if audit and audit.extra else None,
            "reason": audit.reason if audit and audit.reason else None,
        }
        return audit_data

    async def log(
        self,
        log_type: Literal["message", "voice", "audit", "global"],
        global_table: Optional[str] = "message",
        guild: Optional[Union[discord.Guild, None]] = None,
        update: Optional[bool] = False,
        safe_insert: Optional[bool] = False,
        **kwargs,
    ):
        """
        Logs message to database
        """
        # insert into the database
        if log_type == "global":
            handler = self.database_handlers["global"]
        elif guild:
            handler = self.database_handlers[guild.id]
        else:
            handler = None

        if not handler:
            # should log should of been checked already, so we are missing a database handler!
            print(
                LOG_MSG.format(
                    f"No database handler exists for guild {guild}! Called with this state: log_type: `{log_type}`, global_table: `{global_table}`, update: `{update}`, safe_insert: `{safe_insert}`, kwargs: {kwargs}"
                )
            )
            return  # TODO error handling

        if log_type == "message" or (log_type == "global" and global_table == "message"):
            msg_data, att_data = await self.process_message(**kwargs)
            if update:
                await handler.run_in_thread(handler.update, "messages", msg_data)
            else:
                if safe_insert:
                    await handler.run_in_thread(handler.safe_insert, "messages", msg_data)
                else:
                    await handler.run_in_thread(handler.insert, "messages", msg_data)
            for a in att_data:
                if safe_insert:
                    await handler.run_in_thread(handler.safe_insert, "attachments", a)
                else:
                    await handler.run_in_thread(handler.insert, "attachments", a)
        elif log_type == "voice":
            voice_data = await self.process_voice(**kwargs)
            if safe_insert:
                await handler.run_in_thread(handler.safe_insert, "voice", voice_data)
            else:
                await handler.run_in_thread(handler.insert, "voice", voice_data)
        elif log_type == "audit" or (log_type == "global" and global_table == "audit"):
            audit_data = self.process_audit(**kwargs)
            if safe_insert:
                await handler.run_in_thread(handler.safe_insert, "audit", audit_data)
            else:
                await handler.run_in_thread(handler.insert, "audit", audit_data)

    ### Configuration Commands ###
    @commands.group()
    @checks.admin_or_permissions(administrator=True)
    async def logset(self, ctx):
        """
        Change activity logging settings
        """
        pass

    @logset.command(name="audit")
    @checks.is_owner()
    async def set_audit_check(self, ctx, on_off: Optional[bool] = None):
        """
        Set whether to access audit logs to get authors of audit actions

        Turning this off means audit actions are **saved** but **who** did those actions are not saved.
        This should be turned off for bots in large amount of servers since you will hit global ratelimits very quickly.
        """
        if on_off is not None:
            async with self.config.attrs() as attrs:
                attrs["check_audit"] = on_off
            self.update_cache("check_audit", on_off, "global")

        async with self.config.attrs() as attrs:
            status = attrs["check_audit"]

        if status:
            await ctx.send("Checking audit logs is enabled.")
        else:
            await ctx.send("Checking audit logs is disabled.")

    @logset.command(name="everything", aliases=["global"])
    @checks.is_owner()
    async def set_everything(self, ctx, on_off: Optional[bool] = None):
        """
        Global override for all logging
        """
        if on_off is not None:
            async with self.config.attrs() as attrs:
                attrs["everything"] = on_off
            self.update_cache("everything", on_off, "global")

        async with self.config.attrs() as attrs:
            status = attrs["everything"]
        if status:
            await ctx.send("Global logging override is enabled.")
        else:
            await ctx.send("Global logging override is disabled.")

    @logset.command(name="default")
    @checks.is_owner()
    async def set_default(self, ctx, on_off: Optional[bool] = None):
        """
        Sets whether logging is on or off where unset

        guild overrides, global override, and attachments don't use this.
        """
        if on_off is not None:
            async with self.config.attrs() as attrs:
                attrs["default"] = on_off
            self.update_cache("default", on_off, "global")

        async with self.config.attrs() as attrs:
            status = attrs["default"]
        if status:
            await ctx.send("Logging is enabled by default.")
        else:
            await ctx.send("Logging is disabled by default.")

    @logset.command(name="dm")
    @checks.is_owner()
    async def set_direct(self, ctx, on_off: Optional[bool] = None):
        """
        Set logging direct messages to the bot
        """
        if on_off is not None:
            async with self.config.attrs() as attrs:
                attrs["direct"] = on_off
            self.update_cache("direct", on_off, "global")

        async with self.config.attrs() as attrs:
            status = attrs["direct"]
        if status:
            await ctx.send("Logging of direct messages is enabled.")
        else:
            await ctx.send("Logging of direct messages is disabled.")

    @logset.command(name="attachments")
    @checks.is_owner()
    async def set_attachments(self, ctx, on_off: Optional[bool] = None):
        """
        Download message attachments?

        This can use a lot of disk space. If not turned on attachments are saved by their url only
        """
        if on_off is not None:
            async with self.config.attrs() as attrs:
                attrs["attachments"] = on_off
            self.update_cache("attachments", on_off, "global")

        async with self.config.attrs() as attrs:
            status = attrs["attachments"]
        if status:
            await ctx.send("Downloading of attachments is enabled.")
        else:
            await ctx.send("Downloading of attachments is disabled.")

    @logset.command(name="backend")
    @checks.is_owner()
    async def set_backend(self, ctx: commands.Context, backend: Optional[Literal["sqlite", "mysql"]] = None):
        """
        Set the backend database for activitylogger

        Right now I support sqlite and mysql
        """
        curr = await self.config.database_config()
        if backend is None:
            await ctx.send(info(f"Current backend is {curr['backend']}."))
            return

        if backend == curr["backend"]:
            await ctx.send(warning(f"The backend is already set to {curr['backend']}."))
            return

        await ctx.send(
            warning(
                "Data will not be imported from the old backend, you must do so manually. This will be supported in the future. Continue?"
            )
        )
        pred = MessagePredicate.yes_or_no(ctx)
        try:
            await self.bot.wait_for("message", check=pred, timeout=60)
        except asyncio.TimeoutError:
            return await ctx.send("Cancelled.", delete_after=30)
        if not pred.result:
            return await ctx.send("Cancelled.", delete_after=30)

        async with self.config.database_config() as database_config:
            if backend == "sqlite":
                temp = {"backend": "sqlite", "username": None, "password": None, "host": "localhost", "port": 3306}
                success = self.initialize_databases(temp)
                if success:
                    await ctx.send(
                        info(
                            "Backend is now sqlite, if starting fresh make sure to run [p]logset sync to sync the guild data to the database."
                        )
                    )
                    for k, v in temp.items():
                        database_config[k] = v
                else:
                    return await ctx.send(error("There was an error setting up the databases. Please check bot logs."))
            elif backend == "mysql":
                pred = MessagePredicate.same_context(ctx)

                def pred2(m):
                    try:
                        if int(m.content) > 65535 or int(m.content) < 1:
                            return False
                        if int(m.content):
                            return True
                        return False
                    except ValueError:
                        return False

                msg = await ctx.send(
                    info(
                        "What is the server IP address? Do not include the port. Before continuing, make sure I will have full permissions on the database server."
                    )
                )
                try:
                    resp = await ctx.bot.wait_for("message", timeout=60, check=pred)
                except asyncio.TimeoutError:
                    return await ctx.send(warning("Timed out, canceling..."), reference=ctx.message)
                ip = resp.content
                try:
                    await msg.delete()
                    await resp.delete()
                except:
                    pass

                msg = await ctx.send(info("What is the server port?"))
                try:
                    resp = await ctx.bot.wait_for("message", timeout=60, check=lambda m: pred2(m) and pred(m))
                except asyncio.TimeoutError:
                    return await ctx.send(warning("Timed out, canceling..."), reference=ctx.message)
                port = int(resp.content)
                try:
                    await msg.delete()
                    await resp.delete()
                except:
                    pass

                msg = await ctx.send(info("What is the username?"))
                try:
                    resp = await ctx.bot.wait_for("message", timeout=60, check=pred)
                except asyncio.TimeoutError:
                    return await ctx.send(warning("Timed out, canceling..."), reference=ctx.message)
                username = resp.content
                try:
                    await msg.delete()
                    await resp.delete()
                except:
                    pass

                msg = await ctx.send(info("What is the password?"))
                try:
                    resp = await ctx.bot.wait_for("message", timeout=60, check=pred)
                except asyncio.TimeoutError:
                    return await ctx.send(warning("Timed out, canceling..."), reference=ctx.message)
                password = resp.content
                try:
                    await msg.delete()
                    await resp.delete()
                except:
                    pass

                temp = {
                    "backend": "mysql",
                    "username": username,
                    "password": password,
                    "host": ip,
                    "port": port,
                }
                success = self.initialize_databases(temp)
                if success:
                    await ctx.send(
                        info(
                            "Backend is now mysql, if starting fresh make sure to run [p]logset sync to sync the guild data to the database."
                        )
                    )
                    for k, v in temp.items():
                        database_config[k] = v
                else:
                    return await ctx.send(error("There was an error setting up the databases. Please check bot logs."))

    @logset.command(name="sync")
    @commands.guild_only()
    @checks.bot_has_permissions(administrator=True)
    async def sync_guild(self, ctx: commands.Context):
        """
        Sync all channels to the internal database. Configure what you want to log first before running.

        Audit logs are NOT synced, this will come in a future update. This will also pull some data from the older version logs.
        """
        await ctx.send(
            warning(
                "This is an intensive operation that will take a long time. I will only sync based on my settings, so make sure those are set how you want first. Proceed?"
            )
        )
        pred = MessagePredicate.yes_or_no(ctx)
        try:
            await self.bot.wait_for("message", check=pred, timeout=60)
        except asyncio.TimeoutError:
            return
        if not pred.result:
            return

        guild = ctx.guild
        await ctx.send(f"🔄 Starting full sync for **{guild.name}**...")
        update_message = info("Processing {} channels... \nProgress: {}")

        ## helper functions
        async def sync_channel(channel: Union[discord.TextChannel, discord.VoiceChannel, discord.Thread]):
            """
            Fetches messages from a channel or thread and logs them.
            """
            if not (self.should_log(channel) or self.should_log(channel.guild)):
                return
            try:
                async for message in channel.history(limit=None, oldest_first=True):
                    try:
                        await self.log("message", guild=channel.guild, update=False, safe_insert=True, message=message)
                    except Exception as e:
                        print(f"Failed to log message {message.id} in {channel.name}: {e}")
            except discord.Forbidden:
                print(f"Skipping {channel.name} — missing permissions.")
            except Exception as e:
                print(f"Error fetching {channel.name}: {e}")

        update_m = await ctx.send(update_message.format(len(guild.channels), "N/A"))
        start = time.perf_counter()
        total = len(guild.channels)
        for i, channel in enumerate(guild.channels):
            if isinstance(channel, discord.TextChannel) or isinstance(channel, discord.VoiceChannel):
                await sync_channel(channel)

                # Sync threads within the text channel
                if isinstance(channel, discord.TextChannel):
                    threads = channel.threads
                    async for thread in channel.archived_threads(private=True, joined=True, limit=None):
                        threads.append(thread)
                    for thread in threads:
                        await sync_channel(thread)

            elif isinstance(channel, discord.ForumChannel):
                threads = channel.threads
                async for thread in channel.archived_threads(limit=None):
                    threads.append(thread)
                for thread in threads:
                    await sync_channel(thread)

            now = time.perf_counter()
            elapsed = now - start
            avg = elapsed / i if i > 0 else 0
            remaining = (total - i) * avg

            hrs, rem = divmod(remaining, 3600)
            mins, secs = divmod(rem, 60)
            eta_str = f"{int(hrs)}:{int(mins):02d}:{secs:04.1f}"
            progress_string = f"Iter {i+1}/{total} — elapsed {elapsed:.1f}s — ETA {eta_str}"

            try:
                update_m = await update_m.edit(content=update_message.format(total, progress_string))
            except:
                update_m = await ctx.send(update_message.format(total, progress_string))

        # sync member join/leaves from old files
        files = sorted(glob(os.path.join(self.data_path, str(guild.id), "*guild.log")))
        for path in files:
            with open(path, "r") as f:
                data = f.readlines()
            for line in data:
                if "Member join" in line or "Member leave" in line:
                    id = re.search(ID_FINDER, line)
                    if id:
                        uid = int(id.group(1))
                        if "Member join" in line:
                            await self.log(
                                "audit",
                                guild=guild,
                                update=False,
                                audit=None,
                                action="member_join",
                                category="create",
                                author=uid,
                                attribute="join",
                                before=None,
                                after=uid,
                            )
                        else:
                            await self.log(
                                "audit",
                                guild=guild,
                                update=False,
                                audit=None,
                                action="member_leave",
                                category="create",
                                author=uid,
                                attribute="leave",
                                before=uid,
                                after=None,
                            )

        await ctx.send("✅ Full guild sync complete!")

    @logset.command(name="channel")
    @commands.guild_only()
    async def set_channel(self, ctx, on_off: bool, channel: Optional[discord.abc.GuildChannel] = None):
        """
        Sets channel logging on or off (channel optional)
        This will also log all threads under this channel

        To enable or disable all channels at once, use `logset server`.
        """
        if channel is None:
            channel: discord.abc.GuildChannel = ctx.channel

        self.update_cache("enabled", on_off, level=channel)
        await self.config.channel(channel).enabled.set(on_off)

        if on_off:
            await ctx.send("Logging enabled for %s" % channel.mention)
        else:
            await ctx.send("Logging disabled for %s" % channel.mention)

    @logset.command(name="attachment-channel")
    @commands.guild_only()
    async def set_attachment_channel(self, ctx, channel: Union[discord.TextChannel, str]):
        """
        Sets channel to log attachments to in your server.
        Attachments from messages will be uploaded here and will be linked when gettings logs.

        Pass `disable` to disable this feature.
        """
        if isinstance(channel, str) and channel.lower() == "disable":
            await self.config.guild(ctx.guild).attachment_channel.clear()
            await ctx.tick()
            return
        elif isinstance(channel, str):
            await ctx.send(error("Invalid channel!"), delete_after=30, reference=ctx.message)
            return

        self.update_cache("attachment_channel", channel.id, level=ctx.guild)
        await self.config.guild(ctx.guild).attachment_channel.set(channel.id)
        await ctx.tick()

    @logset.command(name="server")
    @commands.guild_only()
    async def set_guild(self, ctx, on_off: bool):
        """
        Sets logging on or off for all channels and server events
        """
        guild = ctx.guild

        await self.config.guild(guild).all_s.set(on_off)
        self.update_cache("all_s", on_off, level=guild)

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

        await self.config.guild(guild).voice.set(on_off)
        self.update_cache("voice", on_off, level=guild)

        if on_off:
            await ctx.send("Voice event logging enabled for %s" % guild)
        else:
            await ctx.send("Voice event logging disabled for %s" % guild)

    @logset.command(name="events")
    @commands.guild_only()
    async def set_events(self, ctx, on_off: bool):
        """
        Sets logging on or off for guild audit events
        """
        guild = ctx.guild

        await self.config.guild(guild).events.set(on_off)
        self.update_cache("events", on_off, level=guild)

        if on_off:
            await ctx.send("Logging enabled for guild events in %s" % guild)
        else:
            await ctx.send("Logging disabled for guild events in %s" % guild)

    @logset.command(name="prefixes")
    @commands.guild_only()
    async def set_prefixes(self, ctx, *, prefixes: Optional[str] = None):
        """
        Set list of prefixes to mark messages as bot commands for user stats.
        Seperate prefixes with spaces
        """
        if prefixes is None:
            curr = [f"`{p}`" for p in await self.config.guild(ctx.guild).prefixes()]
            if not curr:
                await ctx.send("No prefixes set, setting this bot's prefix.")
                await self.config.guild(ctx.guild).prefixes.set([ctx.clean_prefix])
                return
            await ctx.send("Current Prefixes: " + humanize_list(curr))
            return

        new_prefixes = [p.strip() for p in prefixes.split(" ")]
        self.update_cache("prefixes", new_prefixes, level=ctx.guild)
        await self.config.guild(ctx.guild).prefixes.set(new_prefixes)
        new_prefixes = [f"`{p}`" for p in prefixes]
        await ctx.send("Prefixes set to: " + humanize_list(new_prefixes))

    ### User Commands ###
    @commands.hybrid_command(aliases=["uinfo"])
    @commands.guild_only()
    @commands.cooldown(rate=1, per=5, type=commands.BucketType.user)
    async def userinfo(self, ctx: commands.Context, *, member: Optional[discord.Member] = None):
        """
        Show information about a user.

        Pass with no arguments to get information about yourself
        """
        author = ctx.author
        guild = ctx.guild
        if not isinstance(author, discord.Member) or not guild:
            await ctx.send(error("This command can only run in a guild!"), delete_after=30, reference=ctx.message)
            return

        is_mod = await is_mod_or_superior(self.bot, author)

        if not member or not is_mod:
            user = author
        else:
            user = member

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

            if user.display_avatar:
                avatar = user.display_avatar.url
                data.set_author(name=name, url=avatar)
                data.set_thumbnail(url=avatar)
            else:
                data.set_author(name=name)

            user_flags = user.public_flags
            flags = [f.name for f in user_flags.all()]
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
                        emoji = self.badge_emojis.get(badge, None)
                    if emoji:
                        badges += f"{emoji} {badge.replace('_', ' ').title()}\n"
                    else:
                        badges += f"\N{BLACK QUESTION MARK ORNAMENT}\N{VARIATION SELECTOR-16} {badge.replace('_', ' ').title()}\n"
                    badge_count += 1
            if badges:
                data.add_field(name="Badges" if badge_count > 1 else "Badge", value=badges)
            if user_flags.spammer:
                data.add_field(name="Suspected Spammer", value="True")
            if "Economy" in self.bot.cogs:
                bankstat = f"**Bank**: {str(humanize_number(await bank.get_balance(user)))} {await bank.get_currency_name(guild)}\n"
                data.add_field(name="Balance", value=bankstat)

            if is_mod:
                try:
                    await ctx.send(embed=data, allowed_mentions=discord.AllowedMentions.all())
                except discord.HTTPException:
                    await ctx.send(
                        error("I need the `Embed links` permission to send this!"),
                        delete_after=30,
                        reference=ctx.message,
                    )
            else:
                try:
                    await author.send(embed=data)
                    await ctx.reply(info("I sent your info to your DMs!"), delete_after=30)
                except discord.HTTPException:
                    await ctx.reply(
                        error("Please allow messages from server members to get your info."),
                        delete_after=30,
                        reference=ctx.message,
                    )
                except Exception as e:
                    print(LOG_MSG.format(f"Error in userinfo: {e}"))

    async def userstats(self, guild: discord.Guild, user: discord.Member):
        """
        Get stats on a user about how active they are in the guild
        """
        stats = await self.config.member(user).stats()
        names = []
        async with self.config.user(user).past_names() as past_names:
            if not past_names:
                # query global logs for names
                handler = self.database_handlers["global"]
                data = await handler.run_in_thread(
                    handler.query,
                    "audit",
                    ["before", "after"],
                    {"action": "user_update", "author_id": user.id, "attribute": "username"},
                )
                names = []
                for row in data:
                    names.append(row["before"])
                    names.append(row["after"])
                names = list(set(names))
            else:
                names = past_names
            past_names = names

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
            minutes if minutes <= 120 else hours,
            "minutes" if minutes <= 120 else "hours",
        )
        msg += f"Bans: `{bans}`, Kicks: `{kicks}`, Mutes: `{mutes}`, Warnings: `{warns}`"
        warnings = self.bot.get_cog("Warnings_Custom")
        if warnings:
            warn_points = await warnings.get_warnining_points(user)
            msg += f" Warn Points: `{warn_points}`"
        if len(names) > 1:
            return msg, humanize_list(names)

        return msg, None

    ### Generating Logs ###.
    async def voice_log_sender(
        self,
        ctx: commands.Context,
        channel: Union[discord.VoiceChannel, discord.StageChannel],
        start_time: datetime,
        end_time: Optional[datetime] = None,
        member: Optional[discord.Member] = None,
    ):
        if end_time is None:
            end_time = discord.utils.utcnow()
        wait_msg = await ctx.send(warning("**__Generating logs, please wait...__**"))
        guild = channel.guild
        async with ctx.typing():
            handler = self.database_handlers[guild.id]

            columns = [
                "datetime",
                "author_id",
                "channel_id",
                "action_type",
                "state",
                "moved_to_id",
            ]

            filter: Dict[str, Any] = {"datetime": {"lte": end_time}}
            if start_time:
                filter["datetime"]["gte"] = start_time
            if member:
                filter["author_id"] = member.id
            data = await handler.run_in_thread(handler.query, "voice", columns, filters=filter)
            data = sorted(data, key=lambda r: r["datetime"])

            for row in data:
                author = (
                    guild.get_member(row["author_id"])
                    or self.bot.get_user(row["author_id"])
                    or await guild.fetch_member(row["author_id"])
                )
                curr_channel = guild.get_channel(row["channel_id"]) or self.bot.get_channel(row["channel_id"])
                if author:
                    row["author_id"] = author.display_name
                if curr_channel:
                    row["channel_id"] = channel.name

            # export audit data as csv:
            output_file = StringIO()
            writer = csv.DictWriter(output_file, fieldnames=columns)
            writer.writeheader()
            writer.writerows(data)
            data_str = output_file.getvalue()
            output_io = BytesIO()
            output_io.write(data_str.encode())
            output_io.seek(0)
            output_attachment = discord.File(output_io, filename=f"{channel.name}_export.csv")
            await ctx.send(file=output_attachment, reference=ctx.message)
            try:
                await wait_msg.edit(content=info("**__Log file Generated!__**"))
            except:
                pass

    async def audit_log_sender(
        self,
        ctx: commands.Context,
        guild: Union[discord.Guild, Literal["global"]],
        start_time: datetime,
        end_time: Optional[datetime] = None,
        member: Optional[discord.Member] = None,
    ):
        if end_time is None:
            end_time = discord.utils.utcnow()
        wait_msg = await ctx.send(warning("**__Generating logs, please wait...__**"))
        async with ctx.typing():
            if isinstance(guild, discord.Guild):
                handler = self.database_handlers[guild.id]
            else:
                handler = self.database_handlers["global"]

            columns = [
                "id",
                "datetime",
                "action",
                "category",
                "author_id",
                "attribute",
                "before",
                "after",
                "extra",
                "reason",
            ]

            filter: Dict[str, Any] = {"datetime": {"lte": end_time}}
            if start_time:
                filter["datetime"]["gte"] = start_time
            if member:
                filter["author_id"] = member.id
            data = await handler.run_in_thread(handler.query, "audit", columns, filters=filter)
            data = sorted(data, key=lambda r: r["datetime"])
            for row in data:
                author = self.bot.get_user(row["author_id"])
                if isinstance(guild, discord.Guild) and author is None:
                    try:
                        author = guild.get_member(row["author_id"]) or await guild.fetch_member(row["author_id"])
                        if author:
                            row["author_id"] = author.display_name
                    except discord.HTTPException:
                        pass

                action = row.get("action")
                attr = row.get("attribute")
                before = row.get("before")
                after = row.get("after")

                before_resolved = before
                after_resolved = after

                # === User or Member ===
                if attr in ("owner", "author", "ban", "unban", "kick", "leave", "join"):
                    before_resolved = await resolve_user(self.bot, before)
                    after_resolved = await resolve_user(self.bot, after)

                # === Role ===
                elif attr == "role":
                    before_resolved = await resolve_role(guild, before)
                    after_resolved = await resolve_role(guild, after)

                # === Channel/Thread ===
                elif attr == "channel" or attr == "thread":
                    before_resolved = resolve_channel(guild, before)
                    after_resolved = resolve_channel(guild, after)

                # === Emoji ===
                elif attr == "emoji":
                    before_resolved = resolve_emoji(self.bot, before)
                    after_resolved = resolve_emoji(self.bot, after)

                # === Sticker ===
                elif attr == "sticker":
                    before_resolved = resolve_sticker(guild, before)
                    after_resolved = resolve_sticker(guild, after)

                # === Event (Scheduled Event) ===
                elif attr == "event":
                    before_resolved = resolve_event(guild, before)
                    after_resolved = resolve_event(guild, after)

                # === Soundboard Sound ===
                elif attr == "sound":
                    before_resolved = resolve_sound(guild, before)
                    after_resolved = resolve_sound(guild, after)

                # === Invite ===
                elif attr == "invite":
                    # Invite codes are often already strings
                    before_resolved = before
                    after_resolved = after

                # === Misc known formatting (like permissions, category_id, etc.) ===
                if isinstance(before, int) and "category_id" in attr:
                    before_resolved = resolve_channel(guild, before)
                if isinstance(after, int) and "category_id" in attr:
                    after_resolved = resolve_channel(guild, after)

                row["before"] = before_resolved
                row["after"] = after_resolved

            # export audit data as csv:
            output_file = StringIO()
            writer = csv.DictWriter(output_file, fieldnames=columns)
            writer.writeheader()
            writer.writerows(data)
            data_str = output_file.getvalue()
            output_io = BytesIO()
            output_io.write(data_str.encode())
            output_io.seek(0)
            output_attachment = discord.File(
                output_io, filename=f"{guild.name if isinstance(guild, discord.Guild) else guild}_audit_export.csv"
            )
            await ctx.send(file=output_attachment, reference=ctx.message)
            try:
                await wait_msg.edit(content=info("**__Log file Generated!__**"))
            except:
                pass

    async def chat_log_sender(
        self,
        ctx: commands.Context,
        channel_or_member: Union[discord.TextChannel, discord.VoiceChannel, discord.Thread, discord.Member],
        start_time: datetime,
        end_time: Optional[datetime] = None,
    ):
        if end_time is None:
            end_time = discord.utils.utcnow()
        wait_msg = await ctx.send(warning("**__Generating logs, please wait...__**"))
        async with ctx.typing():
            if not ctx.guild:
                await ctx.send("Fetching Private Channels is not support currently.")
                try:
                    await wait_msg.delete()
                except:
                    pass
                return
                handler = self.database_handlers["global"]
            else:
                handler = self.database_handlers[ctx.guild.id]
            columns = [
                "message_id",
                "channel_id",
                "author_id",
                "datetime",
                "edited_datetime",
                "content",
                "edited_content",
                "reference_id",
                "deleted_by_id",
            ]
            attach_columns = [
                "id",
                "message_id",
                "attachment_message_id",
                "url",
                "filepath",
            ]

            filter: Dict[str, Any] = {"datetime": {"lte": end_time}}
            if type(channel_or_member) in [discord.TextChannel, discord.VoiceChannel, discord.Thread]:
                filter["channel_id"] = channel_or_member.id
            else:
                filter["author_id"] = channel_or_member.id
            if start_time:
                filter["datetime"]["gte"] = start_time
            messages = await handler.run_in_thread(handler.query, "messages", columns, filters=filter)
            attach_filter = {"message_id": {"in": [r["message_id"] for r in messages]}}
            attachments = await handler.run_in_thread(
                handler.query, "attachments", attach_columns, filters=attach_filter
            )

            if not messages:
                await ctx.send(error("No messages found for that time period!"), delete_after=30, reference=ctx.message)
                try:
                    await wait_msg.delete()
                except:
                    pass
                return

            exporter = ChatHTMLExporter(self.bot, ctx.guild)
            exporter.ingest_messages(messages)
            exporter.ingest_attachments(attachments)
            output = BytesIO()
            if type(channel_or_member) in [discord.TextChannel, discord.VoiceChannel, discord.Thread]:
                output_io = await exporter.export_channel(channel_or_member.id)
            else:
                output_io = await exporter.export_user(channel_or_member.id, output, include_dm_name=True)
            output_attachments = [
                discord.File(o, filename=f"{channel_or_member.name}_export_{i}.html") for i, o in enumerate(output_io)
            ]
            for output_att in output_attachments:
                await ctx.send(file=output_att, reference=ctx.message)
            try:
                await wait_msg.edit(content=info("**__Log file Generated!__**"))
            except:
                pass

    def interval_parser(self, till: str):
        try:
            dates = till.split(";")
            dates = [dates[0].strip(), dates[1].strip()]  # only use 2 dates
            start, end = [parse_time(date) for date in dates]

            if end < start:
                start, end = end, start  # swap order
            return start, end
        except:
            pass

        interval = parse_timedelta(till)
        date = None
        if not interval:
            try:
                date = parse_time(till)
            except:
                return None, None
            if not date:
                return None, None

        if interval:
            start_time = discord.utils.utcnow() - interval
        else:
            start_time = date

        return start_time, discord.utils.utcnow()

    @commands.group(aliases=["log"], invoke_without_command=True)
    @commands.guild_only()
    @checks.mod_or_permissions(administrator=True)
    async def logs(self, ctx: commands.Context):
        """
        Download chat logs for your server

        Run with no subcommand to use the menu
        """
        if ctx.invoked_subcommand is None:
            view = LogView(ctx, self)
            view.message = await ctx.send(
                "Configure your logging request, don't forget to submit either a time delta or a date range using the buttons:",
                view=view,
            )

    @logs.command(name="from")
    async def logs_channel_interval(
        self,
        ctx,
        channel: Union[discord.TextChannel, discord.VoiceChannel, discord.Thread],
        *,
        till: str,
    ):
        """
        Logs for an entire channel going back to a specific interval or date/time.

        `till` can be a date, an interval, or two different dates split by a **__semicolon__**

        Dates/times look like:
        - February 14 at 6pm EDT
        - 2019-04-13 06:43:00 PST
        - 01/20/18 at 21:00:43

        times default to UTC if no timezone provided

        Example with 2 dates:
        - 2021-01-01 11:11:00 EDT;2021-01-01 12:00:00 EDT

         Intervals look like:
            5 minutes
            1 minute 30 seconds
            1 hour
            2 days
            30 days
            5h30m
        """
        start_time, end_time = self.interval_parser(till)
        if not start_time:
            await ctx.send(error("Invalid date or interval! Try again."), delete_after=30, reference=ctx.message)
            return

        await self.chat_log_sender(ctx, channel, start_time, end_time=end_time)

    @logs.command(name="user")
    async def logs_users_channel_interval(self, ctx, user: discord.Member, *, till: str):
        """
        User's messages accross the guild going back to a specific interval or date/time.

         `till` can be a date, an interval, or two different dates split by a **__semicolon__**

        Dates/times look like:
        - February 14 at 6pm EDT
        - 2019-04-13 06:43:00 PST
        - 01/20/18 at 21:00:43

        times default to UTC if no timezone provided

        Example with 2 dates:
        - 2021-01-01 11:11:00 EDT;2021-01-01 12:00:00 EDT

         Intervals look like:
            5 minutes
            1 minute 30 seconds
            1 hour
            2 days
            30 days
            5h30m
        """
        start_time, end_time = self.interval_parser(till)
        if not start_time:
            await ctx.send(error("Invalid date or interval! Try again."), delete_after=30, reference=ctx.message)
            return

        await self.chat_log_sender(ctx, user, start_time, end_time=end_time)

    @logs.command(name="voice")
    async def logs_voice_from(self, ctx, channel: Union[discord.VoiceChannel, discord.StageChannel], *, till: str):
        """
        Logs for a voice channel going back the specified interval.

        `till` can be a date, an interval, or two different dates split by a **__semicolon__**

        Dates/times look like:
        - February 14 at 6pm EDT
        - 2019-04-13 06:43:00 PST
        - 01/20/18 at 21:00:43

        times default to UTC if no timezone provided

        Example with 2 dates:
        - 2021-01-01 11:11:00 EDT;2021-01-01 12:00:00 EDT

         Intervals look like:
            5 minutes
            1 minute 30 seconds
            1 hour
            2 days
            30 days
            5h30m
        """
        start_time, end_time = self.interval_parser(till)
        if not start_time:
            await ctx.send(error("Invalid date or interval! Try again."), delete_after=30, reference=ctx.message)
            return

        await self.voice_log_sender(ctx, channel, start_time, end_time=end_time)

    @logs.group(name="audit")
    async def logs_audit(self, ctx):
        """Gets audit logs"""
        pass

    @logs_audit.command(name="from")
    async def logs_audit_from(self, ctx: commands.Context, *, till: str):
        """
        Audit logs for server going back a time or to a specific data.
        Gets all role and name changes, mutes, etc.
        Also gets audit actions (deleting messages, bans, etc)

        `till` can be a date, an interval, or two different dates split by a **__semicolon__**

        Dates/times look like:
        - February 14 at 6pm EDT
        - 2019-04-13 06:43:00 PST
        - 01/20/18 at 21:00:43

        times default to UTC if no timezone provided

        Example with 2 dates:
        - 2021-01-01 11:11:00 EDT;2021-01-01 12:00:00 EDT

         Intervals look like:
            5 minutes
            1 minute 30 seconds
            1 hour
            2 days
            30 days
            5h30m
        """
        start_time, end_time = self.interval_parser(till)
        if not start_time:
            await ctx.send(error("Invalid date or interval! Try again."), delete_after=30, reference=ctx.message)
            return

        await self.audit_log_sender(ctx, ctx.guild, start_time=start_time, end_time=end_time)

    @logs_audit.command(name="user")
    async def logs_audit_user_from(self, ctx, user: discord.Member, *, till: str):
        """
        Audit logs for server from user going back a time or to a specified date.
        Gets all role and name changes, mutes, etc.
        Also gets audit actions (deleting messages, bans, etc)

        `till` can be a date, an interval, or two different dates split by a **__semicolon__**

        Dates/times look like:
        - February 14 at 6pm EDT
        - 2019-04-13 06:43:00 PST
        - 01/20/18 at 21:00:43

        times default to UTC if no timezone provided

        Example with 2 dates:
        - 2021-01-01 11:11:00 EDT;2021-01-01 12:00:00 EDT

         Intervals look like:
            5 minutes
            1 minute 30 seconds
            1 hour
            2 days
            30 days
            5h30m
        """
        start_time, end_time = self.interval_parser(till)
        if not start_time:
            await ctx.send(error("Invalid date or interval! Try again."), delete_after=30, reference=ctx.message)
            return

        await self.audit_log_sender(ctx, ctx.guild, start_time=start_time, member=user, end_time=end_time)

    ### Graphing ###
    @commands.group(name="graphstats", invoke_without_command=True)
    @checks.mod_or_permissions(administrator=True)
    @commands.guild_only()
    async def graphstats(self, ctx):
        """
        Generate graphs for users and guild.
        """
        if ctx.invoked_subcommand is None:
            view = GraphView(ctx, self)
            view.message = await ctx.send(
                "Configure your graph request:",
                view=view,
            )

    @graphstats.command(name="correlation")
    async def graphstats_correlation(self, ctx: commands.Context):
        """
        Generate a correlation graph between all users in your server.

        It is best visualized using Gephi, import the generated CSV using that program for easy visualization!
        """
        await ctx.send(
            warning(
                "This is an intensive operation, querying large amounts of data. Are you sure you want to continue?"
            )
        )
        pred = MessagePredicate.yes_or_no(ctx)
        try:
            await self.bot.wait_for("message", check=pred, timeout=60)
        except asyncio.TimeoutError:
            return
        if not pred.result:
            return

        user_map = {u.id: u.name for u in ctx.guild.members}
        handler = self.database_handlers[ctx.guild.id]
        # get logs
        voice_columns = [
            "datetime",
            "author_id",
            "channel_id",
            "action_type",
            "state",
            "moved_to_id",
        ]
        text_columns = ["message_id", "channel_id", "author_id", "datetime", "reference_id"]
        async with ctx.typing():
            voice_data = await handler.run_in_thread(handler.query, "voice", voice_columns)
            text_data = await handler.run_in_thread(handler.query, "messages", text_columns)
            voice_data = sorted(voice_data, key=lambda r: r["datetime"])
            text_data = sorted(text_data, key=lambda r: r["datetime"])

            data_file, analysis_file, summary_file, figure_file = await asyncio.to_thread(
                build_interaction_graph,
                ctx.guild,
                text_data,
                voice_data,
                user_lookup=user_map,
            )

            files = [
                discord.File(data_file, filename=f"{ctx.guild.name}_correlation_data.csv"),
                discord.File(analysis_file, filename=f"{ctx.guild.name}_user_analysis.csv"),
                discord.File(summary_file, filename=f"{ctx.guild.name}_summary_explaination.csv"),
                discord.File(figure_file, filename=f"{ctx.guild.name}_correlation_graph.png"),
            ]

            await ctx.send(files=files, reference=ctx.message)

    @graphstats.command(name="retention")
    async def graphstats_retention(self, ctx: commands.Context):
        """
        Graph a histogram of how long members have been in the guild
        """
        data_file, figure_file = await asyncio.to_thread(plot_retention, ctx.guild.members)
        files = [
            discord.File(data_file, filename="retention_graph_data.csv"),
            discord.File(figure_file, filename="retention_voice_graph.png"),
        ]

        await ctx.send(files=files, reference=ctx.message)

    @graphstats.group(name="voice")
    async def graphstats_voice(self, ctx: commands.Context):
        """
        Graph voice stats for a guild
        """
        pass

    @graphstats_voice.command(name="user")
    async def graphstats_voice_user(self, ctx: commands.Context, member: discord.Member, *, till: str):
        """
        Create a graph of user activity in voice channels.

        `till` can be a date, an interval, or two different dates split by a **__semicolon__**

        **Times in graph are all in UTC**

        Dates/times look like:
        - February 14 at 6pm EDT
        - 2019-04-13 06:43:00 PST
        - 01/20/18 at 21:00:43

        times default to UTC if no timezone provided

        Example with 2 dates:
        - 2021-01-01 11:11:00 EDT;2021-01-01 12:00:00 EDT

         Intervals look like:
            5 minutes
            1 minute 30 seconds
            1 hour
            2 days
            30 days
            5h30m
        """
        start_time, end_time = self.interval_parser(till)
        if not start_time:
            await ctx.send(error("Invalid date or interval! Try again."), delete_after=30, reference=ctx.message)
            return

        handler = self.database_handlers[ctx.guild.id]
        # get logs
        columns = [
            "datetime",
            "author_id",
            "channel_id",
            "action_type",
            "state",
            "moved_to_id",
        ]
        filters = {
            "datetime": {"gte": start_time, "lte": end_time},
            "author_id": member.id,
            "action_type": {"in": ["join", "leave", "move"]},
        }
        async with ctx.typing():
            data = await handler.run_in_thread(handler.query, "voice", columns, filters=filters)
            data = sorted(data, key=lambda r: r["datetime"])

            data_file, figure_file = await asyncio.to_thread(plot_voice_time_by_channel, data, ctx.guild, member)
            if not data_file or not figure_file:
                await ctx.send(
                    warning("No data found for that user and time period."), delete_after=30, reference=ctx.author
                )
                return

            files = [
                discord.File(data_file, filename=f"{member.display_name}_graph_data.csv"),
                discord.File(figure_file, filename=f"{member.display_name}_voice_graph.png"),
            ]

            await ctx.send(files=files, reference=ctx.message)

    @graphstats_voice.command(name="channel")
    async def graphstats_users_voice(
        self,
        ctx,
        channel: Union[discord.VoiceChannel, discord.StageChannel],
        *,
        till: str,
    ):
        """
        Gives activity in minutes of every user in a voice channel for a specific time period

        `till` can be a date, an interval, or two different dates split by a **__semicolon__**

        **Times in graph are all in UTC**

        Dates/times look like:
        - February 14 at 6pm EDT
        - 2019-04-13 06:43:00 PST
        - 01/20/18 at 21:00:43

        times default to UTC if no timezone provided

        Example with 2 dates:
        - 2021-01-01 11:11:00 EDT;2021-01-01 12:00:00 EDT

         Intervals look like:
            5 minutes
            1 minute 30 seconds
            1 hour
            2 days
            30 days
            5h30m
        """
        start_time, end_time = self.interval_parser(till)
        if not start_time:
            await ctx.send(error("Invalid date or interval! Try again."), delete_after=30, reference=ctx.message)
            return

        handler = self.database_handlers[ctx.guild.id]
        # get logs
        columns = [
            "datetime",
            "author_id",
            "channel_id",
            "action_type",
            "state",
            "moved_to_id",
        ]
        filters = {
            "datetime": {"gte": start_time, "lte": end_time},
            "action_type": {"in": ["join", "leave", "move"]},
            "or": [{"channel_id": channel.id}, {"moved_to_id": channel.id}],
        }
        async with ctx.typing():
            data = await handler.run_in_thread(handler.query, "voice", columns, filters=filters)
            data = sorted(data, key=lambda r: r["datetime"])

            data_file, figure_file = await asyncio.to_thread(plot_users_in_voice_channel, data, self.bot, channel)
            if not data_file or not figure_file:
                await ctx.send(
                    warning("No data found for that channel and time period."), delete_after=30, reference=ctx.author
                )
                return

            files = [
                discord.File(data_file, filename=f"{channel.name}_graph_data.csv"),
                discord.File(figure_file, filename=f"{channel.name}_voice_graph.png"),
            ]

            await ctx.send(files=files, reference=ctx.message)

    @graphstats.command(name="text")
    async def user_stats_graph(self, ctx: commands.Context, member: discord.Member, split: str, *, till: str):
        """
        Create a graph of a users activity over time for text channels.

        `split` is how to split the data on the graph, like per hour, per day, etc.
        Possible values are:
        - "h" for hourly
        - "d" for daily
        - "w" for weekly
        - "m" for monthly
        - "y" for yearly

        `till` can be a date, an interval, or two different dates split by a **__semicolon__**

        **Times in graph are all in UTC**

        Dates/times look like:
        - February 14 at 6pm EDT
        - 2019-04-13 06:43:00 PST
        - 01/20/18 at 21:00:43

        times default to UTC if no timezone provided

        Example with 2 dates:
        - 2021-01-01 11:11:00 EDT;2021-01-01 12:00:00 EDT

         Intervals look like:
            5 minutes
            1 minute 30 seconds
            1 hour
            2 days
            30 days
            5h30m
        """
        start_time, end_time = self.interval_parser(till)
        if not start_time:
            await ctx.send(error("Invalid date or interval! Try again."), delete_after=30, reference=ctx.message)
            return
        handler = self.database_handlers[ctx.guild.id]
        columns = [
            "message_id",
            "channel_id",
            "author_id",
            "datetime",
        ]

        filters = {
            "datetime": {"gte": start_time, "lte": end_time},
            "author_id": member.id,
        }
        async with ctx.typing():
            data = await handler.run_in_thread(handler.query, "messages", columns, filters=filters)
            data = sorted(data, key=lambda r: r["datetime"])

            data_file, figure_file = await asyncio.to_thread(
                plot_text_activity_over_time,
                data,
                ctx.guild,
                member=member,
                top_n_channels=5,
                date_granularity=split.lower(),
            )
            if not data_file or not figure_file:
                await ctx.send(
                    warning("No data found for that user and time period."), delete_after=30, reference=ctx.author
                )
                return

            files = [
                discord.File(data_file, filename=f"{member.display_name}_graph_data.csv"),
                discord.File(figure_file, filename=f"{member.display_name}_text_graph.png"),
            ]

            await ctx.send(files=files, reference=ctx.message)

    @graphstats.command(name="leaves")
    async def graphstats_leaves(self, ctx: commands.Context, split: str, *, till: str):
        """
        Plot server joins and leaves for time period.

        `split` is how to split the data on the graph, like per hour, per day, etc.
        Possible values are:
        - "h" for hourly
        - "d" for daily
        - "w" for weekly
        - "m" for monthly
        - "y" for yearly

        `till` can be a date, an interval, or two different dates split by a **__semicolon__**

        **Times in graph are all in UTC**

        Dates/times look like:
        - February 14 at 6pm EDT
        - 2019-04-13 06:43:00 PST
        - 01/20/18 at 21:00:43

        times default to UTC if no timezone provided

        Example with 2 dates:
        - 2021-01-01 11:11:00 EDT;2021-01-01 12:00:00 EDT

         Intervals look like:
            5 minutes
            1 minute 30 seconds
            1 hour
            2 days
            30 days
            5h30m
        """
        start_time, end_time = self.interval_parser(till)
        if not start_time:
            await ctx.send(error("Invalid date or interval! Try again."), delete_after=30, reference=ctx.message)
            return

        handler = self.database_handlers[ctx.guild.id]
        columns = [
            "id",
            "datetime",
            "action",
            "author_id",
        ]
        filters = {
            "datetime": {"gte": start_time, "lte": end_time},
            "action": {"in": ["member_join", "member_leave", "kick", "ban"]},
        }
        async with ctx.typing():
            data = await handler.run_in_thread(handler.query, "audit", columns, filters=filters)
            data = sorted(data, key=lambda r: r["datetime"])
            data_file, figure_file = await asyncio.to_thread(plot_guild_joins_and_leaves, data, split.lower())
            if not data_file or not figure_file:
                await ctx.send(
                    warning("No data found for that user and time period."), delete_after=30, reference=ctx.author
                )
                return

            files = [
                discord.File(data_file, filename=f"retention_graph_data.csv"),
                discord.File(figure_file, filename=f"retention_graph.png"),
            ]

            await ctx.send(files=files, reference=ctx.message)

    @graphstats.command(name="activity")
    async def graphstats_activity(self, ctx: commands.Context, split: str, *, till: str):
        """
        Create a graph that shows per channel activity

        `split` is how to split the data on the graph, like per hour, per day, etc.
        Possible values are:
        - "h" for hourly
        - "d" for daily
        - "w" for weekly
        - "m" for monthly
        - "y" for yearly

        `till` can be a date, an interval, or two different dates split by a **__semicolon__**

        **Times in graph are all in UTC**

        Dates/times look like:
        - February 14 at 6pm EDT
        - 2019-04-13 06:43:00 PST
        - 01/20/18 at 21:00:43

        times default to UTC if no timezone provided

        Example with 2 dates:
        - 2021-01-01 11:11:00 EDT;2021-01-01 12:00:00 EDT

         Intervals look like:
            5 minutes
            1 minute 30 seconds
            1 hour
            2 days
            30 days
            5h30m
        """
        start_time, end_time = self.interval_parser(till)
        if not start_time:
            await ctx.send(error("Invalid date or interval! Try again."), delete_after=30, reference=ctx.message)
            return

        handler = self.database_handlers[ctx.guild.id]
        columns = [
            "message_id",
            "channel_id",
            "author_id",
            "datetime",
        ]

        filters = {
            "datetime": {"gte": start_time, "lte": end_time},
        }
        async with ctx.typing():
            data = await handler.run_in_thread(handler.query, "messages", columns, filters=filters)
            data = sorted(data, key=lambda r: r["datetime"])

            data_file, figure_file = await asyncio.to_thread(
                plot_text_activity_over_time,
                data,
                ctx.guild,
                top_n_channels=5,
                date_granularity=split.lower(),
            )
            if not data_file or not figure_file:
                await ctx.send(warning("No data found for that time period."), delete_after=30, reference=ctx.author)
                return

            files = [
                discord.File(data_file, filename=f"{ctx.guild.name}_graph_data.csv"),
                discord.File(figure_file, filename=f"{ctx.guild.name}_text_graph.png"),
            ]

            await ctx.send(files=files, reference=ctx.message)

    @graphstats.group(name="hours")
    async def graphstats_hours(self, ctx):
        """
        Show activate hours for a channel or entire guild.
        """
        pass

    @graphstats_hours.command(name="channel")
    async def graphstats_hours_channel(
        self,
        ctx: commands.Context,
        channel: Union[discord.TextChannel, discord.VoiceChannel, discord.Thread],
        *,
        till: str,
    ):
        """
        Show active hours for specific text channel.

        `till` can be a date, an interval, or two different dates split by a **__semicolon__**

        **Times in graph are all in UTC**

        Dates/times look like:
        - February 14 at 6pm EDT
        - 2019-04-13 06:43:00 PST
        - 01/20/18 at 21:00:43

        times default to UTC if no timezone provided

        Example with 2 dates:
        - 2021-01-01 11:11:00 EDT;2021-01-01 12:00:00 EDT

         Intervals look like:
            5 minutes
            1 minute 30 seconds
            1 hour
            2 days
            30 days
            5h30m
        """
        start_time, end_time = self.interval_parser(till)
        if not start_time:
            await ctx.send(error("Invalid date or interval! Try again."), delete_after=30, reference=ctx.message)
            return

        handler = self.database_handlers[ctx.guild.id]
        # get logs
        columns = [
            "message_id",
            "channel_id",
            "author_id",
            "datetime",
        ]

        filters = {
            "datetime": {"gte": start_time, "lte": end_time},
            "channel_id": channel.id,
        }
        async with ctx.typing():
            data = await handler.run_in_thread(handler.query, "messages", columns, filters=filters)
            data = sorted(data, key=lambda r: r["datetime"])

            data_file, figure_file = await asyncio.to_thread(plot_hourly_heatmap, data, channel)
            if not data_file or not figure_file:
                await ctx.send(warning("No data found for that time period."), delete_after=30, reference=ctx.author)
                return

            files = [
                discord.File(data_file, filename=f"{channel.name}_activity_graph_data.csv"),
                discord.File(figure_file, filename=f"{channel.name}_activity_graph.png"),
            ]

            await ctx.send(files=files, reference=ctx.message)

    @graphstats_hours.command(name="guild")
    async def graphstats_hours_guild(self, ctx: commands.Context, *, till: str):
        """
        Show active hours for entire guild.

        `till` can be a date, an interval, or two different dates split by a **__semicolon__**

        **Times in graph are all in UTC**

        Dates/times look like:
        - February 14 at 6pm EDT
        - 2019-04-13 06:43:00 PST
        - 01/20/18 at 21:00:43

        times default to UTC if no timezone provided

        Example with 2 dates:
        - 2021-01-01 11:11:00 EDT;2021-01-01 12:00:00 EDT

         Intervals look like:
            5 minutes
            1 minute 30 seconds
            1 hour
            2 days
            30 days
            5h30m
        """
        start_time, end_time = self.interval_parser(till)
        if not start_time:
            await ctx.send(error("Invalid date or interval! Try again."), delete_after=30, reference=ctx.message)
            return

        handler = self.database_handlers[ctx.guild.id]
        # get logs
        columns = [
            "message_id",
            "channel_id",
            "author_id",
            "datetime",
        ]

        filters = {
            "datetime": {"gte": start_time, "lte": end_time},
        }
        async with ctx.typing():
            data = await handler.run_in_thread(handler.query, "messages", columns, filters=filters)
            data = sorted(data, key=lambda r: r["datetime"])

            data_file, figure_file = await asyncio.to_thread(plot_hourly_heatmap, data, ctx.guild)
            if not data_file or not figure_file:
                await ctx.send(warning("No data found for that time period."), delete_after=30, reference=ctx.author)
                return

            files = [
                discord.File(data_file, filename=f"{ctx.guild.name}_activity_graph_data.csv"),
                discord.File(figure_file, filename=f"{ctx.guild.name}_activity_graph.png"),
            ]

            await ctx.send(files=files, reference=ctx.message)

    ### Listeners ###
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if await self.bot.cog_disabled_in_guild(self, message.guild):
            return
        if not (self.should_log(message.channel) or self.should_log(message.guild)):
            return
        if type(message.channel) in [discord.abc.PrivateChannel, discord.channel.DMChannel] or message.guild is None:
            await self.log("global", global_table="message", update=False, message=message)
        else:
            await self.log("message", guild=message.guild, update=False, message=message)

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        if await self.bot.cog_disabled_in_guild(self, after.guild):
            return
        if not (self.should_log(after.channel) or self.should_log(after.guild)):
            return
        if type(before.channel) in [discord.abc.PrivateChannel, discord.channel.DMChannel] or before.guild is None:
            await self.log("global", global_table="message", update=True, message=before, after=after)
        else:
            await self.log("message", guild=before.guild, update=True, message=before, after=after)

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        if await self.bot.cog_disabled_in_guild(self, message.guild):
            return
        if not (self.should_log(message.channel) or self.should_log(message.guild)):
            return

        if type(message.channel) in [discord.abc.PrivateChannel, discord.channel.DMChannel] or message.guild is None:
            await self.log("global", global_table="message", update=True, message=message, deleted_by=message.author)
            return

        entry = await self.get_audit_entry(
            message.guild,
            lambda e: e.action is discord.AuditLogAction.message_delete,
            lambda e: e.target.id == message.author.id,
            lambda e: e.extra.channel.id == message.channel.id if e.extra else False,
            lambda e: e.created_at >= discord.utils.utcnow() - timedelta(seconds=500),
            lambda e: e.extra.count >= 1 if e.extra else False,
        )
        deleted_by = entry.user if entry is not None else message.author

        await self.log("message", guild=message.guild, update=True, message=message, deleted_by=deleted_by)

    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild):
        if await self.bot.cog_disabled_in_guild(self, guild):
            return
        if guild.id in self.database_handlers:
            return

        # setup guild database
        database_conf = await self.config.database_config()

        # key ids for these should be ints
        if database_conf["backend"] == "sqlite":
            handler = DatabaseHandler(str(guild.id), data_path=str(self.data_path))
        elif database_conf["backend"] == "mysql":
            handler = DatabaseHandler(str(guild.id), **database_conf)
        else:  # shouldn't happen
            handler = None
        self.database_handlers[guild.id] = handler

    @commands.Cog.listener()
    async def on_guild_update(self, before: discord.Guild, after: discord.Guild):
        if await self.bot.cog_disabled_in_guild(self, after):
            return
        if not self.should_log(before):
            return

        action = "guild_update"
        category = "update"
        audit_entry = None
        attribute = []
        old_value = []
        new_value = []
        audit_entry = await self.get_audit_entry(
            after,
            lambda e: e.action is discord.AuditLogAction.guild_update,
        )

        author: User | Member | None = audit_entry.user if audit_entry else before.me
        if before.owner != after.owner:
            attribute.append("owner")
            old_value.append(before.owner.id if before.owner else None)
            new_value.append(after.owner.id if after.owner else None)

        if before.name != after.name:
            attribute.append("name")
            old_value.append(before.name)
            new_value.append(after.name)

        if before.icon != after.icon:
            attribute.append("guild_icon")
            old_value.append(before.icon.url if before.icon else None)
            new_value.append(after.icon.url if after.icon else None)

        if before.splash != after.splash:
            attribute.append("splash")
            old_value.append(before.splash.url if before.splash else None)
            new_value.append(after.splash.url if after.splash else None)

        for attr, old, new in zip(attribute, old_value, new_value):
            await self.log(
                "audit",
                guild=after,
                update=False,
                audit=audit_entry,
                action=action,
                category=category,
                author=author,
                attribute=attr,
                before=old,
                after=new,
            )

    @commands.Cog.listener()
    async def on_guild_emojis_update(
        self,
        guild: discord.Guild,
        before: Sequence[discord.Emoji],
        after: Sequence[discord.Emoji],
    ):
        if await self.bot.cog_disabled_in_guild(self, guild):
            return
        if not self.should_log(guild):
            return

        # Determine added and removed emojis
        before_ids = {e.id for e in before}
        after_ids = {e.id for e in after}

        added = [emoji for emoji in after if emoji.id not in before_ids]
        removed = [emoji for emoji in before if emoji.id not in after_ids]

        for emoji in added:
            audit_entry = await self.get_audit_entry(
                guild,
                lambda e: e.action == discord.AuditLogAction.emoji_create,
                lambda e: e.target.id == emoji.id,
            )
            author: User | Member | None = audit_entry.user if audit_entry else guild.me
            await self.log(
                "audit",
                guild=guild,
                update=False,
                audit=audit_entry,
                action="emoji_create",
                category="create",
                author=author,
                attribute="emoji",
                before=None,
                after=emoji.id,
            )
        for emoji in removed:
            audit_entry = await self.get_audit_entry(
                guild,
                lambda e: e.action == discord.AuditLogAction.emoji_delete,
                lambda e: e.target.id == emoji.id,
            )
            author: User | Member | None = audit_entry.user if audit_entry else guild.me
            await self.log(
                "audit",
                guild=guild,
                update=False,
                audit=audit_entry,
                action="emoji_delete",
                category="delete",
                author=author,
                attribute="emoji",
                before=emoji.id,
                after=emoji.name,
            )

    @commands.Cog.listener()
    async def on_guild_stickers_update(
        self, guild: discord.Guild, before: Sequence[discord.GuildSticker], after: Sequence[discord.GuildSticker]
    ):
        if await self.bot.cog_disabled_in_guild(self, guild):
            return
        if not self.should_log(guild):
            return

        # Determine added and removed stickers
        before_ids = {s.id for s in before}
        after_ids = {s.id for s in after}

        added = [sticker for sticker in after if sticker.id not in before_ids]
        removed = [sticker for sticker in before if sticker.id not in after_ids]

        for sticker in added:
            audit_entry = await self.get_audit_entry(
                guild,
                lambda e: e.action == discord.AuditLogAction.sticker_create,
                lambda e: e.target.id == sticker.id,
            )
            author: User | Member | None = audit_entry.user if audit_entry else guild.me
            await self.log(
                "audit",
                guild=guild,
                update=False,
                audit=audit_entry,
                action="sticker_create",
                category="create",
                author=author,
                attribute="sticker",
                before=None,
                after=sticker.id,
            )
        for sticker in removed:
            audit_entry = await self.get_audit_entry(
                guild,
                lambda e: e.action == discord.AuditLogAction.sticker_delete,
                lambda e: e.target.id == sticker.id,
            )
            author: User | Member | None = audit_entry.user if audit_entry else guild.me
            await self.log(
                "audit",
                guild=guild,
                update=False,
                audit=audit_entry,
                action="sticker_delete",
                category="delete",
                author=author,
                attribute="sticker",
                before=sticker.id,
                after=sticker.name,
            )

    @commands.Cog.listener()
    async def on_audit_log_entry_create(self, entry: discord.AuditLogEntry):
        # not logged directly, but used for checking other logging events
        if entry.guild.id not in self.audit_logs:
            self.audit_logs[entry.guild.id] = deque([entry], maxlen=AUDIT_QUEUE_LEN)
        else:
            self.audit_logs[entry.guild.id].appendleft(entry)

    @commands.Cog.listener()
    async def on_invite_create(self, invite: discord.Invite):
        if await self.bot.cog_disabled_in_guild(self, invite.guild):
            return
        if not self.should_log(invite.guild):
            return

        audit_entry = await self.get_audit_entry(
            invite.guild,
            lambda e: e.action == discord.AuditLogAction.invite_create,
            lambda e: e.target.id == invite.id,
        )

        await self.log(
            "audit",
            guild=invite.guild,
            update=False,
            audit=audit_entry,
            action="invite_create",
            category="create",
            author=invite.inviter if invite.inviter else invite.guild.me,
            attribute="invite",
            before=None,
            after=invite.code,
        )

    @commands.Cog.listener()
    async def on_invite_delete(self, invite: discord.Invite):
        if invite.guild is not None and await self.bot.cog_disabled_in_guild(self, invite.guild):
            return
        if not self.should_log(invite.guild):
            return

        audit_entry = await self.get_audit_entry(
            invite.guild,
            lambda e: e.action == discord.AuditLogAction.invite_delete,
            lambda e: e.target.id == invite.id,
        )
        author: User | Member | None = audit_entry.user if audit_entry else invite.guild.me

        await self.log(
            "audit",
            guild=invite.guild,
            update=False,
            audit=audit_entry,
            action="invite_delete",
            category="delete",
            author=author,
            attribute="invite",
            before=invite.code,
            after=None,
        )

    @commands.Cog.listener()
    async def on_bulk_message_delete(self, messages: List[discord.Message]):
        if not messages:
            return
        guild = messages[0].guild
        if guild is None:
            return
        if await self.bot.cog_disabled_in_guild(self, guild):
            return
        if not self.should_log(guild):
            return

        channel = messages[0].channel
        audit_entry = await self.get_audit_entry(
            guild,
            lambda e: e.action == discord.AuditLogAction.message_bulk_delete,
            lambda e: e.target.id == channel.id,
        )
        deleted_by: User | Member | None = audit_entry.user if audit_entry else guild.me

        for msg in messages:
            await self.log("message", guild=guild, update=True, message=msg, deleted_by=deleted_by)

    @commands.Cog.listener()
    async def on_scheduled_event_create(self, event: discord.ScheduledEvent):
        if event.guild is None or await self.bot.cog_disabled_in_guild(self, event.guild):
            return
        if not self.should_log(event.guild):
            return

        audit_entry = await self.get_audit_entry(
            event.guild,
            lambda e: e.action == discord.AuditLogAction.scheduled_event_create,
            lambda e: e.target.id == event.id,
        )
        author: User | Member | None = audit_entry.user if audit_entry else event.guild.me

        await self.log(
            "audit",
            guild=event.guild,
            update=False,
            audit=None,
            action="scheduled_event_create",
            category="create",
            author=author,
            attribute="event",
            before=None,
            after=event.id,
        )

    @commands.Cog.listener()
    async def on_scheduled_event_delete(self, event: discord.ScheduledEvent):
        if event.guild is None or await self.bot.cog_disabled_in_guild(self, event.guild):
            return
        if not self.should_log(event.guild):
            return

        audit_entry = await self.get_audit_entry(
            event.guild,
            lambda e: e.action == discord.AuditLogAction.scheduled_event_delete,
            lambda e: e.target.id == event.id,
        )
        author: User | Member | None = audit_entry.user if audit_entry else event.guild.me

        await self.log(
            "audit",
            guild=event.guild,
            update=False,
            audit=None,
            action="scheduled_event_delete",
            category="delete",
            author=author,
            attribute="event",
            before=event.id,
            after=event.name,
        )

    @commands.Cog.listener()
    async def on_scheduled_event_update(self, before: discord.ScheduledEvent, after: discord.ScheduledEvent):
        guild = after.guild
        if guild is None or await self.bot.cog_disabled_in_guild(self, guild):
            return
        if not self.should_log(guild):
            return

        attribute = []
        old_value = []
        new_value = []

        if before.name != after.name:
            attribute.append("name")
            old_value.append(before.name)
            new_value.append(after.name)
        if before.description != after.description:
            attribute.append("description")
            old_value.append(before.description)
            new_value.append(after.description)
        if before.start_time != after.start_time:
            attribute.append("start_time")
            old_value.append(str(before.start_time))
            new_value.append(str(after.start_time))
        if before.end_time != after.end_time:
            attribute.append("end_time")
            old_value.append(str(before.end_time) if before.end_time is not None else None)
            new_value.append(str(after.end_time) if after.end_time is not None else None)
        if before.channel != after.channel:
            attribute.append("channel")
            old_value.append(str(before.channel.id) if before.channel else None)
            new_value.append(str(after.channel.id) if after.channel else None)
        if before.status != after.status:
            attribute.append("status")
            old_value.append(str(before.status))
            new_value.append(str(after.status))
        if before.cover_image != after.cover_image:
            attribute.append("cover_image")
            old_value.append(before.cover_image.url if before.cover_image else None)
            new_value.append(after.cover_image.url if after.cover_image else None)

        audit_entry = await self.get_audit_entry(
            before.guild,
            lambda e: e.action == discord.AuditLogAction.scheduled_event_update,
            lambda e: e.target.id == before.id,
        )
        author: User | Member | None = audit_entry.user if audit_entry else guild.me

        for attr, old, new in zip(attribute, old_value, new_value):
            await self.log(
                "audit",
                guild=guild,
                update=False,
                audit=audit_entry,
                action="scheduled_event_update",
                category="update",
                author=author,
                attribute=attr,
                before=old,
                after=new,
                force_new_id=True,
            )

    @commands.Cog.listener()
    async def on_soundboard_sound_create(self, sound: discord.SoundboardSound):
        if await self.bot.cog_disabled_in_guild(self, sound.guild):
            return
        if not self.should_log(sound.guild):
            return

        audit_entry = await self.get_audit_entry(
            sound.guild,
            lambda e: e.action == discord.AuditLogAction.soundboard_sound_create,
            lambda e: e.after.id == sound.id,
        )
        author: User | Member | None = audit_entry.user if audit_entry else sound.guild.me

        await self.log(
            "audit",
            guild=sound.guild,
            update=False,
            audit=audit_entry,
            action="soundboard_sound_create",
            category="create",
            author=author,
            attribute="sound",
            before=None,
            after=sound.id,
        )

    @commands.Cog.listener()
    async def on_soundboard_sound_delete(self, sound: discord.SoundboardSound):
        if await self.bot.cog_disabled_in_guild(self, sound.guild):
            return
        if not self.should_log(sound.guild):
            return

        audit_entry = await self.get_audit_entry(
            sound.guild,
            lambda e: e.action == discord.AuditLogAction.soundboard_sound_delete,
            lambda e: e.before.id == sound.id,
        )
        author: User | Member | None = audit_entry.user if audit_entry else sound.guild.me

        await self.log(
            "audit",
            guild=sound.guild,
            update=False,
            audit=audit_entry,
            action="soundboard_sound_delete",
            category="delete",
            author=author,
            attribute="sound",
            before=sound.id,
            after=sound.name,
        )

    @commands.Cog.listener()
    async def on_soundboard_sound_update(self, before: discord.SoundboardSound, after: discord.SoundboardSound):
        guild = after.guild
        if await self.bot.cog_disabled_in_guild(self, guild):
            return
        if not self.should_log(guild):
            return

        attribute = []
        old_value = []
        new_value = []

        if before.name != after.name:
            attribute.append("name")
            old_value.append(before.name)
            new_value.append(after.name)
        if before.emoji != after.emoji:
            attribute.append("emoji")
            old_value.append(before.emoji.id if before.emoji else None)
            new_value.append(after.emoji.id if after.emoji else None)
        if before.volume != after.volume:
            attribute.append("volume")
            old_value.append(before.volume)
            new_value.append(after.volume)

        # for some reason this auditlog entry type has no id on before, after, or target
        # so hopefully this returns the right sound, as long as multiple edits arent happening at once
        audit_entry = await self.get_audit_entry(
            guild,
            lambda e: e.action == discord.AuditLogAction.soundboard_sound_update,
            # lambda e: e.target.id == after.id,
        )
        author: User | Member | None = audit_entry.user if audit_entry else guild.me

        for attr, old, new in zip(attribute, old_value, new_value):
            await self.log(
                "audit",
                guild=guild,
                update=False,
                audit=audit_entry,
                action="soundboard_sound_update",
                category="update",
                author=author,
                attribute=attr,
                before=old,
                after=new,
                force_new_id=True,
            )

    @commands.Cog.listener()
    async def on_guild_role_create(self, role: discord.Role):
        if await self.bot.cog_disabled_in_guild(self, role.guild):
            return
        if not self.should_log(role.guild):
            return

        action = "role_create"
        category = "create"
        audit_entry = None
        attribute = "role"
        old_value = None
        new_value = role.id
        audit_entry = await self.get_audit_entry(
            role.guild,
            lambda e: e.action == discord.AuditLogAction.role_create,
            lambda e: e.target.id == role.id,
        )

        author: User | Member | None = audit_entry.user if audit_entry else role.guild.me
        await self.log(
            "audit",
            guild=role.guild,
            update=False,
            audit=audit_entry,
            action=action,
            category=category,
            author=author,
            attribute=attribute,
            before=old_value,
            after=new_value,
        )

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role):
        if await self.bot.cog_disabled_in_guild(self, role.guild):
            return
        if not self.should_log(role.guild):
            return

        action = "role_delete"
        category = "delete"
        audit_entry = None
        attribute = "role"
        old_value = role.id
        new_value = None
        audit_entry = await self.get_audit_entry(
            role.guild,
            lambda e: e.action == discord.AuditLogAction.role_delete,
            lambda e: e.target.id == role.id,
        )

        author: User | Member | None = audit_entry.user if audit_entry else role.guild.me
        await self.log(
            "audit",
            guild=role.guild,
            update=False,
            audit=audit_entry,
            action=action,
            category=category,
            author=author,
            attribute=attribute,
            before=old_value,
            after=new_value,
        )

    @commands.Cog.listener()
    async def on_guild_role_update(self, before: discord.Role, after: discord.Role):
        if await self.bot.cog_disabled_in_guild(self, after.guild):
            return
        if not self.should_log(before.guild):
            return

        action = "role_update"
        category = "update"
        audit_entry = None
        attribute = []
        old_value = []
        new_value = []

        audit_entry = await self.get_audit_entry(
            after.guild,
            lambda e: e.action == discord.AuditLogAction.role_update,
            lambda e: e.target.id == after.id,
        )

        if before.name != after.name:
            attribute.append("name")
            old_value.append(before.name)
            new_value.append(after.name)

        if before.color != after.color:
            attribute.append("color")
            old_value.append(str(before.color))
            new_value.append(str(after.color))

        if before.mentionable != after.mentionable:
            attribute.append("mentionable")
            old_value.append(str(before.mentionable))
            new_value.append(str(after.mentionable))

        if before.hoist != after.hoist:
            attribute.append("hoist")
            old_value.append(str(before.hoist))
            new_value.append(str(after.hoist))

        if before.permissions != after.permissions:
            attribute.append("permissions")
            old_value.append(str(before.permissions.value))
            new_value.append(str(after.permissions.value))

        if before.position != after.position:
            attribute.append("position")
            old_value.append(str(before.position))
            new_value.append(str(after.position))

        author: User | Member | None = audit_entry.user if audit_entry else before.guild.me
        for attr, old, new in zip(attribute, old_value, new_value):
            await self.log(
                "audit",
                guild=before.guild,
                update=False,
                audit=audit_entry,
                action=action,
                category=category,
                author=author,
                attribute=attr,
                before=old,
                after=new,
                force_new_id=True,
            )

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if await self.bot.cog_disabled_in_guild(self, member.guild):
            return

        async with self.config.user(member).past_names() as past_names:
            if str(member) not in past_names:
                past_names.append(str(member))

        if not self.should_log(member.guild):
            return

        await self.log(
            "audit",
            guild=member.guild,
            update=False,
            audit=None,
            action="member_join",
            category="create",
            author=member,
            attribute="join",
            before=None,
            after=member.id,
        )

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        if await self.bot.cog_disabled_in_guild(self, member.guild):
            return
        if not self.should_log(member.guild):
            return

        audit_entry = await self.get_audit_entry(
            member.guild,
            lambda e: e.action == discord.AuditLogAction.kick,
            lambda e: e.target.id == member.id,
        )

        if audit_entry is not None:
            await self.log(
                "audit",
                guild=member.guild,
                update=False,
                audit=audit_entry,
                action="kick",
                category="create",
                author=audit_entry.user,
                attribute="kick",
                before=member.id,
                after=None,
            )
        else:
            # leave
            await self.log(
                "audit",
                guild=member.guild,
                update=False,
                audit=audit_entry,
                action="member_leave",
                category="create",
                author=member,
                attribute="leave",
                before=member.id,
                after=None,
            )

    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, member: discord.Member):
        if await self.bot.cog_disabled_in_guild(self, guild):
            return
        if not self.should_log(guild):
            return

        audit_entry = await self.get_audit_entry(
            guild,
            lambda e: e.action == discord.AuditLogAction.ban,
            lambda e: e.target.id == member.id,
        )

        author: User | Member | None = audit_entry.user if audit_entry else guild.me
        await self.log(
            "audit",
            guild=guild,
            update=False,
            audit=audit_entry,
            action="ban",
            category="create",
            author=author,
            attribute="ban",
            before=member.id,
            after=None,
        )

    @commands.Cog.listener()
    async def on_member_unban(self, guild: discord.Guild, member: discord.User):
        if await self.bot.cog_disabled_in_guild(self, guild):
            return
        if not self.should_log(guild):
            return

        audit_entry = await self.get_audit_entry(
            guild,
            lambda e: e.action == discord.AuditLogAction.unban,
            lambda e: e.target.id == member.id,
        )

        author: User | Member | None = audit_entry.user if audit_entry else guild.me
        await self.log(
            "audit",
            guild=guild,
            update=False,
            audit=audit_entry,
            action="unban",
            category="create",
            author=author,
            attribute="unban",
            before=member.id,
            after=None,
        )

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        if await self.bot.cog_disabled_in_guild(self, after.guild):
            return
        if not self.should_log(before.guild):
            return

        action = "member_update"
        category = "update"
        attribute = []
        old_value = []
        new_value = []

        audit_entry = await self.get_audit_entry(
            after.guild,
            lambda e: e.action == discord.AuditLogAction.member_update or discord.AuditLogAction.member_role_update,
            lambda e: e.target.id == after.id,
        )

        if before.nick != after.nick:
            attribute.append("nick")
            old_value.append(before.nick)
            new_value.append(after.nick)

        if before.roles != after.roles:
            broles = set(before.roles)
            aroles = set(after.roles)
            added = aroles - broles
            removed = broles - aroles

            for r in added:
                attribute.append("role")
                old_value.append(None)
                new_value.append(str(r.id))

            for r in removed:
                attribute.append("role")
                old_value.append(str(r.id))
                new_value.append(None)

        author: User | Member | None = audit_entry.user if audit_entry else before.guild.me
        for attr, old, new in zip(attribute, old_value, new_value):
            await self.log(
                "audit",
                guild=before.guild,
                update=False,
                audit=audit_entry,
                action=action,
                category=category,
                author=author,
                attribute=attr,
                before=old,
                after=new,
                force_new_id=True,
            )

    @commands.Cog.listener()
    async def on_user_update(self, before: discord.User, after: discord.User):
        if not self.should_log(before):
            return
        action = "user_update"
        category = "update"
        attribute = []
        old_value = []
        new_value = []

        if before.name != after.name:
            attribute.append("username")
            old_value.append(before.name)
            new_value.append(after.name)
            # update past usernames
            async with self.config.user(after).past_names() as past_names:
                if after.name not in past_names:
                    past_names.append(after.name)

        if before.avatar != after.avatar:
            attribute.append("avatar")
            old_value.append(str(before.avatar) if before.avatar else None)
            new_value.append(str(after.avatar) if after.avatar else None)

        for attr, old, new in zip(attribute, old_value, new_value):
            await self.log(
                "global",
                global_table="audit",
                guild=None,
                update=False,
                audit=None,
                action=action,
                category=category,
                author=after,
                attribute=attr,
                before=old,
                after=new,
            )

    @commands.Cog.listener()
    async def on_thread_create(self, thread: discord.Thread):
        if await self.bot.cog_disabled_in_guild(self, thread.guild):
            return
        if not self.should_log(thread.guild):
            return

        # try to join the thread so we can log
        try:
            await thread.join()
        except:
            pass

        audit_entry = await self.get_audit_entry(
            thread.guild,
            lambda e: e.action == discord.AuditLogAction.thread_create,
            lambda e: e.target.id == thread.id,
        )
        author: User | Member | None = audit_entry.user if audit_entry else thread.guild.me

        await self.log(
            "audit",
            guild=thread.guild,
            update=False,
            audit=audit_entry,
            action="thread_create",
            category="create",
            author=author,
            attribute="thread",
            before=None,
            after=thread.id,
        )

    @commands.Cog.listener()
    async def on_thread_join(self, thread: discord.Thread):
        pass

    @commands.Cog.listener()
    async def on_thread_update(self, before: discord.Thread, after: discord.Thread):
        guild = after.guild
        if await self.bot.cog_disabled_in_guild(self, guild):
            return
        if not self.should_log(guild):
            return

        attribute = []
        old_value = []
        new_value = []

        if before.name != after.name:
            attribute.append("name")
            old_value.append(before.name)
            new_value.append(after.name)
        if before.archived != after.archived:
            attribute.append("archived")
            old_value.append(str(before.archived))
            new_value.append(str(after.archived))
        if before.locked != after.locked:
            attribute.append("locked")
            old_value.append(str(before.locked))
            new_value.append(str(after.locked))

        audit_entry = await self.get_audit_entry(
            before.guild,
            lambda e: e.action == discord.AuditLogAction.thread_update,
            lambda e: e.target.id == before.id,
        )
        author: User | Member | None = audit_entry.user if audit_entry else before.guild.me

        for attr, old, new in zip(attribute, old_value, new_value):
            await self.log(
                "audit",
                guild=guild,
                update=False,
                audit=audit_entry,
                action="thread_update",
                category="update",
                author=author,
                attribute=attr,
                before=old,
                after=new,
                force_new_id=True,
            )

    @commands.Cog.listener()
    async def on_raw_thread_delete(self, payload: discord.RawThreadDeleteEvent):
        guild = self.bot.get_guild(payload.guild_id)
        if guild is None:
            return
        if await self.bot.cog_disabled_in_guild(self, guild):
            return
        if not self.should_log(guild):
            return

        audit_entry = await self.get_audit_entry(
            guild,
            lambda e: e.action == discord.AuditLogAction.thread_delete,
            lambda e: e.target.id == payload.thread_id,
        )
        author: User | Member | None = audit_entry.user if audit_entry else guild.me

        await self.log(
            "audit",
            guild=guild,
            update=False,
            audit=audit_entry,
            action="thread_delete",
            category="delete",
            author=author,
            attribute="thread",
            before=payload.thread_id,
            after=payload.parent_id,
        )

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel: discord.abc.GuildChannel):
        if await self.bot.cog_disabled_in_guild(self, channel.guild):
            return
        if not self.should_log(channel.guild):
            return

        action = "channel_create"
        category = "create"

        audit_entry = await self.get_audit_entry(
            channel.guild,
            lambda e: e.action == discord.AuditLogAction.channel_create,
            lambda e: e.target.id == channel.id,
        )

        author: User | Member | None = audit_entry.user if audit_entry else channel.guild.me
        await self.log(
            "audit",
            guild=channel.guild,
            update=False,
            audit=audit_entry,
            action=action,
            category=category,
            author=author,
            attribute="channel",
            before=None,
            after=channel.id,
        )

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel):
        if await self.bot.cog_disabled_in_guild(self, channel.guild):
            return
        if not self.should_log(channel.guild):
            return

        action = "channel_delete"
        category = "delete"

        audit_entry = await self.get_audit_entry(
            channel.guild,
            lambda e: e.action == discord.AuditLogAction.channel_delete,
            lambda e: e.target.id == channel.id,
        )

        author: User | Member | None = audit_entry.user if audit_entry else channel.guild.me
        await self.log(
            "audit",
            guild=channel.guild,
            update=False,
            audit=audit_entry,
            action=action,
            category=category,
            author=author,
            attribute="channel",
            before=channel.id,
            after=None,
        )

    @commands.Cog.listener()
    async def on_guild_channel_update(self, before: discord.abc.GuildChannel, after: discord.abc.GuildChannel):
        if await self.bot.cog_disabled_in_guild(self, after.guild):
            return
        if not self.should_log(before.guild):
            return

        action = "channel_update"
        category = "update"
        attribute = []
        old_value = []
        new_value = []

        audit_entry = await self.get_audit_entry(
            after.guild,
            lambda e: e.action
            in [
                discord.AuditLogAction.channel_update,
                discord.AuditLogAction.overwrite_create,
                discord.AuditLogAction.overwrite_delete,
                discord.AuditLogAction.overwrite_update,
            ],
            lambda e: e.target.id == after.id,
        )

        # common attributes
        if before.name != after.name:
            attribute.append("name")
            old_value.append(before.name)
            new_value.append(after.name)
        if before.position != after.position:
            attribute.append("position")
            old_value.append(str(before.position))
            new_value.append(str(after.position))
        if before.nsfw != after.nsfw:
            attribute.append("nsfw")
            old_value.append(str(before.nsfw))
            new_value.append(str(after.nsfw))

        if isinstance(before, discord.TextChannel) and isinstance(after, discord.TextChannel):
            if before.topic != after.topic:
                attribute.append("topic")
                old_value.append(before.topic)
                new_value.append(after.topic)
            if before.slowmode_delay != after.slowmode_delay:
                attribute.append("slowmode_delay")
                old_value.append(before.slowmode_delay)
                new_value.append(after.slowmode_delay)
            if before.category_id != after.category_id:
                attribute.append("category_id")
                old_value.append(before.category_id)
                new_value.append(after.category_id)

        if (isinstance(before, discord.VoiceChannel) and isinstance(after, discord.VoiceChannel)) or (
            isinstance(before, discord.StageChannel) and isinstance(after, discord.StageChannel)
        ):
            if before.slowmode_delay != after.slowmode_delay:
                attribute.append("slowmode_delay")
                old_value.append(before.slowmode_delay)
                new_value.append(after.slowmode_delay)
            if before.bitrate != after.bitrate:
                attribute.append("bitrate")
                old_value.append(before.bitrate)
                new_value.append(after.bitrate)
            if before.category_id != after.category_id:
                attribute.append("category_id")
                old_value.append(before.category_id)
                new_value.append(after.category_id)
            if before.rtc_region != after.rtc_region:
                attribute.append("rtc_region")
                old_value.append(before.rtc_region)
                new_value.append(after.rtc_region)
            if before.user_limit != after.user_limit:
                attribute.append("user_limit")
                old_value.append(before.user_limit)
                new_value.append(after.user_limit)
            if before.video_quality_mode != after.video_quality_mode:
                attribute.append("video_quality_mode")
                old_value.append(before.video_quality_mode)
                new_value.append(after.video_quality_mode)

        if isinstance(before, discord.CategoryChannel) and isinstance(after, discord.CategoryChannel):
            pass

        if isinstance(before, discord.StageChannel) and isinstance(after, discord.StageChannel):
            if before.topic != after.topic:
                attribute.append("topic")
                old_value.append(before.topic)
                new_value.append(after.topic)

        if isinstance(before, discord.ForumChannel) and isinstance(after, discord.ForumChannel):
            if before.topic != after.topic:
                attribute.append("topic")
                old_value.append(before.topic)
                new_value.append(after.topic)
            if before.slowmode_delay != after.slowmode_delay:
                attribute.append("slowmode_delay")
                old_value.append(before.slowmode_delay)
                new_value.append(after.slowmode_delay)
            if before.category_id != after.category_id:
                attribute.append("category_id")
                old_value.append(before.category_id)
                new_value.append(after.category_id)
            if before.available_tags != after.available_tags:
                btags = set(before.available_tags)
                atags = set(after.available_tags)
                added = atags - btags
                removed = btags - atags

                for r in added:
                    attribute.append("available_tags")
                    old_value.append(None)
                    new_value.append(str(r.name))

                for r in removed:
                    attribute.append("available_tags")
                    old_value.append(str(r.name))
                    new_value.append(None)

        before_ow = before.overwrites
        after_ow = after.overwrites

        before_keys = set(before_ow.keys())
        after_keys = set(after_ow.keys())

        added_keys = after_keys - before_keys
        removed_keys = before_keys - after_keys
        common_keys = before_keys & after_keys

        added_perms = {}
        for entity in added_keys:
            po = after_ow[entity]
            allow, deny = po.pair()
            perms = [perm for perm in discord.Permissions.VALID_FLAGS if getattr(allow, perm) or getattr(deny, perm)]
            added_perms[entity] = perms

        removed_perms = {}
        for entity in removed_keys:
            po = before_ow[entity]
            allow, deny = po.pair()
            perms = [perm for perm in discord.Permissions.VALID_FLAGS if getattr(allow, perm) or getattr(deny, perm)]
            removed_perms[entity] = perms

        changed_perms = {}
        for entity in common_keys:
            before_po = before_ow[entity]
            after_po = after_ow[entity]

            changes = compare_permissions(before_po, after_po)
            if changes:
                changed_perms[entity] = changes

        overwrite_change_data = build_overwrite_change_log(added_perms, removed_perms, changed_perms)

        if overwrite_change_data:
            attribute.append("overwrites")
            old_value.append(json.dumps(serialize_overwrites(before_ow)))
            new_value.append(json.dumps(overwrite_change_data))  # LONGTEXT-safe

        author: User | Member | None = audit_entry.user if audit_entry else after.guild.me
        for attr, old, new in zip(attribute, old_value, new_value):
            await self.log(
                "audit",
                guild=after.guild,
                update=False,
                audit=audit_entry,
                action=action,
                category=category,
                author=author,
                attribute=attr,
                before=old,
                after=new,
                force_new_id=True,
            )

    @commands.Cog.listener()
    async def on_voice_state_update(
        self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState
    ):
        if await self.bot.cog_disabled_in_guild(self, member.guild):
            return
        if not self.should_log(before.channel):
            return

        await self.log("voice", guild=member.guild, member=member, before=before, after=after)

    @commands.Cog.listener()
    async def on_automod_rule_create(self, rule: discord.AutoModRule):
        if await self.bot.cog_disabled_in_guild(self, rule.guild):
            return
        if not self.should_log(rule.guild):
            return

        action = "automod_rule_create"
        category = "create"
        await self.log(
            "audit",
            guild=rule.guild,
            update=False,
            audit=None,
            action=action,
            category=category,
            author=rule.creator,
            attribute="",
            before=None,
            after=rule.id,
        )

    @commands.Cog.listener()
    async def on_automod_rule_delete(self, rule: discord.AutoModRule):
        if await self.bot.cog_disabled_in_guild(self, rule.guild):
            return
        if not self.should_log(rule.guild):
            return

        action = "automod_rule_create"
        category = "create"
        await self.log(
            "audit",
            guild=rule.guild,
            update=False,
            audit=None,
            action=action,
            category=category,
            author=rule.creator,
            attribute="",
            before=None,
            after=rule.id,
        )

    @commands.Cog.listener()
    async def on_automod_rule_action(self, action: discord.AutoModAction):
        if await self.bot.cog_disabled_in_guild(self, action.guild):
            return
        if not self.should_log(action.guild):
            return

        # Log that an automod action was performed; details about the action can be expanded as needed.
        await self.log(
            "audit",
            guild=action.guild,
            update=False,
            audit=None,
            action="automod_rule_action",
            category="create",
            author=action.user_id,
            attribute="automod_action",
            before=None,
            after=action.rule_id,
        )
