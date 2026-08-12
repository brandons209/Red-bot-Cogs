import discord
from redbot.core.utils.chat_formatting import *
from redbot.core import Config, checks, commands
from redbot.core.commands import BadArgument
from redbot.core.utils.chat_formatting import humanize_timedelta
from urllib import parse
from typing import Literal, Optional, Union
import aiohttp
import logging
import os
import json
import asyncio
import time

from .derpi import ChallengeGate, DerpiBusy, DerpiCold, DerpiError, fetch_json, make_ssl_context

log = logging.getLogger("red.brandons209.pony")

# Derpibooru's own block lasts 15 minutes, and requests during it restart the timer,
# so a shorter cold period only keeps us blocked longer.
MIN_BLOCK_COOLDOWN = 900


class Pony(commands.Cog):
    __version__ = "5.1.0"

    def __init__(self, bot):
        super().__init__()
        self.bot = bot
        self.config = Config.get_conf(self, identifier=7384662719)
        default_global = {
            "maxfilters": 50,
            "challenge_autosolve": True,
            "challenge_threshold": 3,
            "challenge_window": 900,
            "challenge_cooldown": 900,
            "challenge_block_cooldown": 960,
            "challenge_blocked_until": 0.0,
        }
        self.default_guild = {
            "filters": ["-meme", "safe", "-spoiler:*", "-vulgar"],
            "verbose": False,
            "display_artist": False,
            "cooldown": 10,
        }
        default_channel = {"filters": []}
        self.cooldowns = {}
        self.config.register_guild(**self.default_guild)
        self.config.register_global(**default_global)
        self.config.register_channel(**default_channel)

        # Clearance is keyed to our IP, so one gate and one lock cover every guild.
        # The lock is also what holds the three-request-per-fetch ceiling globally.
        self.gate = ChallengeGate()
        self.derpi_lock = asyncio.Lock()
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=15),
            headers={"User-Agent": "Booru-Bot"},
            connector=aiohttp.TCPConnector(ssl=make_ssl_context()),
        )

        self.task = asyncio.create_task(self.init())

    async def cog_unload(self):
        if self.task:
            self.task.cancel()
        await self.session.close()

    async def init(self):
        """
        Setup cooldown cache and restore any cold period we were in before a reload
        """
        await self.bot.wait_until_ready()
        for guild in self.bot.guilds:
            self.cooldowns[guild.id] = {}
        self.gate.restore(await self.config.challenge_blocked_until())

    @commands.hybrid_command()
    @commands.guild_only()
    async def pony(self, ctx, *, text: str = ""):
        """Retrieves the latest result from Derpibooru"""
        await self.fetch_image(ctx, randomize=False, tags=text)

    @commands.hybrid_command()
    @commands.guild_only()
    async def ponyr(self, ctx, *, text: str = ""):
        """Retrieves a random result from Derpibooru"""
        await self.fetch_image(ctx, randomize=True, tags=text)

    # needed because derpi was having trouble getting a random image from our derpi page with the filters we have
    @commands.hybrid_command()
    @commands.guild_only()
    async def mascot(self, ctx):
        """
        Gives a random picture of our mascot!
        """
        await self.fetch_image(ctx, randomize=True, mascot=True, tags="safe, coe OR oc:aurelia coe")

    @commands.group()
    @commands.guild_only()
    @checks.admin()
    async def ponyfilter(self, ctx: commands.Context):
        """Manages pony filters
        Warning: Can be used to allow NSFW images

        Filters automatically apply tags to each search"""
        pass

    @ponyfilter.command(name="add")
    async def _add_ponyfilter(self, ctx, filter_tag: str):
        """Adds a tag to the server's pony filter list

        Example: !ponyfilter add safe"""
        guild = ctx.guild
        filters = await self.config.guild(guild).filters()
        max_filters = await self.config.maxfilters()
        # if reached limit of max filters, don't add
        if len(filters) < max_filters:
            if filter_tag not in filters:
                async with self.config.guild(guild).filters() as old_filter:
                    old_filter.append(filter_tag)
                await ctx.send("Filter '{}' added to the server's pony filter list.".format(filter_tag))
            else:
                await ctx.send("Filter '{}' is already in the server's pony filter list.".format(filter_tag))
        else:
            await ctx.send("This server has exceeded the maximum filters ({}/{}).".format(len(filters), max_filters))

    @ponyfilter.command(name="del")
    async def _del_ponyfilter(self, ctx, filter_tag: str = ""):
        """Deletes a tag from the server's pony filter list

        Without arguments, reverts to the default pony filter list

        Example: !ponyfilter del safe"""
        guild = ctx.guild
        filters = await self.config.guild(guild).filters()
        if len(filter_tag) > 0:
            if filter_tag in filters:
                async with self.config.guild(guild).filters() as old_filter:
                    old_filter.remove(filter_tag)
                await ctx.send("Filter '{}' deleted from the server's pony filter list.".format(filter_tag))
            else:
                await ctx.send("Filter '{}' does not exist in the server's pony filter list.".format(filter_tag))
        else:
            if self.default_guild["filters"] != filters:
                await self.config.guild(guild).filters.set(self.default_guild["filters"])
                await ctx.send("Reverted the server to the default pony filter list.")
            else:
                await ctx.send("Server is already using the default pony filter list.")

    @ponyfilter.command(name="list")
    async def _list_ponyfilter(self, ctx):
        """Lists all of the filters currently applied to the current server"""
        guild = ctx.guild
        filters = await self.config.guild(guild).filters()
        if filters:
            filter_list = "\n".join(sorted(filters))
            target_guild = "{}'s".format(guild.name)
        else:
            filter_list = "***No Filters Set***"
            target_guild = "Default"
        await ctx.send("{} pony filter list contains:```\n{}```".format(target_guild, filter_list))

    @ponyfilter.group(name="channel")
    async def ponyfilter_channel(self, ctx: commands.Context):
        """
        Manage channel override filters

        If filters are a set for a channel they **completely** override server level filters.
        """
        pass

    @ponyfilter_channel.command(name="add")
    async def channel_add_ponyfilter(
        self,
        ctx: commands.Context,
        channel: Union[discord.TextChannel, discord.VoiceChannel, discord.Thread],
        filter_tag: str,
    ):
        """Adds a tag to the channel's pony filter list

        Example: [p]ponyfilter channel #channel add safe"""
        filters = await self.config.channel(channel).filters()
        max_filters = await self.config.maxfilters()
        # if reached limit of max filters, don't add
        if len(filters) < max_filters:
            if filter_tag not in filters:
                async with self.config.channel(channel).filters() as old_filter:
                    old_filter.append(filter_tag)
                await ctx.send("Filter '{}' added to the {}'s pony filter list.".format(filter_tag, channel.mention))
            else:
                await ctx.send(
                    "Filter '{}' is already in the {}'s pony filter list.".format(filter_tag, channel.mention)
                )
        else:
            await ctx.send("This channel has exceeded the maximum filters ({}/{}).".format(len(filters), max_filters))

    @ponyfilter_channel.command(name="del")
    async def channel_del_ponyfilter(
        self,
        ctx,
        channel: Union[discord.TextChannel, discord.VoiceChannel, discord.Thread],
        filter_tag: str = "",
    ):
        """Deletes a tag from the channel's pony filter list

        Without arguments, clears the channel's filters

        Example: [p]ponyfilter channel #channel del safe"""
        filters = await self.config.channel(channel).filters()
        if len(filter_tag) > 0:
            if filter_tag in filters:
                async with self.config.channel(channel).filters() as old_filter:
                    old_filter.remove(filter_tag)
                await ctx.send(
                    "Filter '{}' deleted from the {}'s pony filter list.".format(filter_tag, channel.mention)
                )
            else:
                await ctx.send(
                    "Filter '{}' does not exist in the {}'s pony filter list.".format(filter_tag, channel.mention)
                )
        else:
            await self.config.channel(channel).filters.clear()
            await ctx.send("Cleared {}'s filters.".format(channel.mention))

    @ponyfilter_channel.command(name="list")
    async def channel_list_ponyfilter(
        self,
        ctx: commands.Context,
        channel: Union[discord.TextChannel, discord.VoiceChannel, discord.Thread],
    ):
        """Lists all of the filters currently applied to the current server"""
        filters = await self.config.channel(channel).filters()
        target = "{}'s".format(channel.name)
        if filters:
            filter_list = "\n".join(sorted(filters))
        else:
            filter_list = "***No Filters Set***"
        await ctx.send("{} pony filter list contains:```\n{}```".format(target, filter_list))

    @commands.group()
    @checks.admin()
    async def ponyset(self, ctx):
        """Manages pony options"""
        pass

    @ponyset.command(name="cooldown")
    async def _cooldown_ponyset(self, ctx, cooldown: int):
        """
        Set the per user cooldown for all pony commands
        """
        await self.config.guild(ctx.guild).cooldown.set(cooldown)
        await ctx.tick()

    @ponyset.command(name="artist")
    async def _display_artist_ponyset(self, ctx, toggle: bool):
        """
        Turn on displaying artists on pony commands
        """
        guild = ctx.guild
        display = await self.config.guild(guild).display_artist()
        if toggle:
            if not display:
                await self.config.guild(guild).display_artist.set(True)
                await ctx.send("Display artist mode is now enabled.")
            else:
                await ctx.send("Display artist is already enabled.")
        else:
            if display:
                await self.config.guild(guild).display_artist.set(False)
                await ctx.send("Display artist is now disabled.")
            else:
                await ctx.send("Display artist is already disabled.")

    @ponyset.command(name="verbose")
    async def _verbose_ponyset(self, ctx, toggle: bool):
        """Toggles verbose mode"""
        guild = ctx.guild
        verbose = await self.config.guild(guild).verbose()
        if toggle:
            if not verbose:
                await self.config.guild(guild).verbose.set(True)
                await ctx.send("Verbose mode is now enabled.")
            else:
                await ctx.send("Verbose mode is already enabled.")
        else:
            if verbose:
                await self.config.guild(guild).verbose.set(False)
                await ctx.send("Verbose mode is now disabled.")
            else:
                await ctx.send("Verbose mode is already disabled.")

    @ponyset.command(name="maxfilters")
    @checks.is_owner()
    async def _maxfilters_ponyset(self, ctx, new_max_filters: Optional[int] = None):
        """Sets the global tag limit for the filter list.

        Leave blank to get current max filters.

        Gives an error when a user tries to add a filter while the server's filter list contains a certain amount of tags
        """
        if new_max_filters is None:
            max_filters = self.config.maxfilters()
            await ctx.send("Current filter limit: {} filters.".format(max_filters))
            return

        await self.config.maxfilters.set(new_max_filters)
        await ctx.send("Maximum filters allowed per server for pony set to '{}'.".format(new_max_filters))

    @ponyset.group(name="challenge")
    @checks.is_owner()
    async def ponyset_challenge(self, ctx):
        """Manage how the cog handles Derpibooru's anti-bot challenge

        Derpibooru serves a challenge page when the whole site is under load, not
        because of anything this bot did. The cog solves it automatically. These
        settings control when it stops solving and backs off instead.

        Settings are global: the clearance is tied to the bot's IP, not to a guild.
        """
        pass

    @ponyset_challenge.command(name="threshold")
    async def _challenge_threshold(self, ctx, count: int):
        """Challenged requests allowed in the window before the cog backs off"""
        if count < 1:
            return await ctx.send("Threshold must be at least 1.")
        await self.config.challenge_threshold.set(count)
        window = await self.config.challenge_window()
        await ctx.send(
            f"Backing off after more than **{count}** challenged requests in {humanize_timedelta(seconds=window)}."
        )

    @ponyset_challenge.command(name="window")
    async def _challenge_window(self, ctx, *, duration: str):
        """Rolling window the challenge threshold is counted over

        Example: [p]ponyset challenge window 15m"""
        seconds = self.parse_duration(duration, minimum=60, maximum=86400)
        await self.config.challenge_window.set(seconds)
        threshold = await self.config.challenge_threshold()
        await ctx.send(
            f"Counting challenged requests over **{humanize_timedelta(seconds=seconds)}** (threshold {threshold})."
        )

    @ponyset_challenge.command(name="cooldown")
    async def _challenge_cooldown(self, ctx, *, duration: str):
        """How long to stop talking to Derpibooru once the threshold is exceeded"""
        seconds = self.parse_duration(duration, minimum=60, maximum=86400)
        await self.config.challenge_cooldown.set(seconds)
        await ctx.send(f"Backoff after too many challenges set to **{humanize_timedelta(seconds=seconds)}**.")

    @ponyset_challenge.command(name="blockcooldown")
    async def _challenge_block_cooldown(self, ctx, *, duration: str):
        """How long to go silent after Derpibooru hard-blocks us (HTTP 500)

        Cannot be set below 15 minutes. That is how long Derpibooru's block lasts,
        and any request sent during it restarts the timer, so a shorter value would
        only keep the bot blocked for longer."""
        seconds = self.parse_duration(duration, minimum=60, maximum=86400)
        clamped = max(seconds, MIN_BLOCK_COOLDOWN)
        await self.config.challenge_block_cooldown.set(clamped)
        msg = f"Backoff after a hard block set to **{humanize_timedelta(seconds=clamped)}**."
        if clamped != seconds:
            msg += f"\nRaised from {humanize_timedelta(seconds=seconds)}: Derpibooru's own block lasts 15 minutes."
        await ctx.send(msg)

    @ponyset_challenge.command(name="autosolve")
    async def _challenge_autosolve(self, ctx, toggle: bool):
        """Toggle solving the challenge automatically

        With this off, a challenged request just tells the user the site is busy."""
        await self.config.challenge_autosolve.set(toggle)
        if toggle:
            await ctx.send("Auto-solving the Derpibooru challenge is now enabled.")
        else:
            await ctx.send("Auto-solving is now disabled. Challenged requests will report the site as busy.")

    @ponyset_challenge.command(name="status")
    async def _challenge_status(self, ctx):
        """Show the current challenge and backoff state"""
        settings = await self.challenge_settings()
        now = time.time()
        remaining = self.gate.cold_remaining(now)
        recent = self.gate.challenges_in_window(now, settings["window"])

        if remaining > 0:
            state = f"**Backing off**, {humanize_timedelta(seconds=max(1, int(remaining)))} remaining"
        else:
            state = "**Ready**"

        msg = (
            f"{state}\n"
            f"Challenged requests in the last {humanize_timedelta(seconds=settings['window'])}: "
            f"**{recent}** (threshold {settings['threshold']})\n"
            f"Auto-solve: **{'on' if settings['autosolve'] else 'off'}**\n"
            f"Backoff after too many challenges: **{humanize_timedelta(seconds=settings['cooldown'])}**\n"
            f"Backoff after a hard block: **{humanize_timedelta(seconds=settings['block_cooldown'])}**"
        )
        await ctx.send(msg)

    @ponyset_challenge.command(name="clear")
    async def _challenge_clear(self, ctx):
        """Clear the current backoff and the challenge history

        Only use this if you know the site has recovered. Requests sent while
        Derpibooru still has us blocked restart its 15 minute timer."""
        self.gate.clear()
        await self.config.challenge_blocked_until.set(0.0)
        await ctx.send("Backoff cleared.")

    @staticmethod
    def parse_duration(duration: str, *, minimum: int, maximum: int) -> int:
        delta = commands.parse_timedelta(duration)
        if delta is None:
            raise BadArgument(f"`{duration}` is not a valid duration. Try something like `15m` or `1h30m`.")
        seconds = int(delta.total_seconds())
        if seconds < minimum or seconds > maximum:
            raise BadArgument(
                f"Duration must be between {humanize_timedelta(seconds=minimum)} "
                f"and {humanize_timedelta(seconds=maximum)}."
            )
        return seconds

    @ponyset.command(name="import")
    @checks.is_owner()
    async def _import_ponyset(self, ctx, path_to_import):
        """Imports filters and settings from jsons.

        Specifiy the **path** to the jsons to import filters and settings from.

        *i.e.: /path/containing/jsons/*"""
        bot = ctx.bot
        path_to_settings = os.path.join(path_to_import, "settings.json")
        path_to_filters = os.path.join(path_to_import, "filters.json")

        try:
            with open(path_to_settings) as raw_settings:
                msg = "Settings import sucessful for these guilds:\n"
                import_settings = json.load(raw_settings)
                for json_guild_id, json_guild_verbose in import_settings.items():
                    if json_guild_id != "maxfilters":
                        guild = bot.get_guild(int(json_guild_id))
                        if guild is None:
                            continue

                        await self.config.guild(guild).verbose.set(json_guild_verbose["verbose"])
                        msg += "**{}**\n".format(guild)
                        if len(msg) + 100 > 2000:
                            await ctx.send(msg)
                            msg = ""

                await self.config.maxfilters.set(int(import_settings["maxfilters"]))
                if msg != "":
                    await ctx.send(msg)

            with open(path_to_filters) as raw_filters:
                import_filters = json.load(raw_filters)
                msg = "Filters import successful for these guilds:\n"
                for json_guild_id, json_guild_filters in import_filters.items():
                    if json_guild_id != "default":
                        guild = bot.get_guild(int(json_guild_id))  # returns None if guild is not found
                        if guild is None:
                            continue

                        await self.config.guild(guild).filters.set(json_guild_filters)
                        msg += "**{}**\n".format(guild)
                        if len(msg) + 100 > 2000:
                            await ctx.send(msg)
                            msg = ""
                    else:
                        continue
                if msg != "":
                    await ctx.send(msg)

        except FileNotFoundError:
            await ctx.send("Invalid path to json files.")
        except json.decoder.JSONDecodeError:
            await ctx.send("Invalid or malformed json files.")

    async def challenge_settings(self):
        conf = self.config
        return {
            "autosolve": await conf.challenge_autosolve(),
            "threshold": await conf.challenge_threshold(),
            "window": await conf.challenge_window(),
            "cooldown": await conf.challenge_cooldown(),
            "block_cooldown": await conf.challenge_block_cooldown(),
        }

    async def derpi_fetch(self, url):
        """Serialize every Derpibooru request and persist any cold period it earns."""
        settings = await self.challenge_settings()
        async with self.derpi_lock:
            before = self.gate.blocked_until
            try:
                return await fetch_json(self.session, url, self.gate, settings)
            finally:
                # Persisted so a reload mid-block doesn't resume hammering. Only on a
                # change, which keeps the write off the hot path.
                if self.gate.blocked_until != before:
                    await self.config.challenge_blocked_until.set(self.gate.blocked_until)
                    log.warning("derpibooru backoff engaged for %.0fs", self.gate.cold_remaining(time.time()))

    async def fetch_image(self, ctx, randomize: bool = False, tags: str = "", mascot=False):
        guild = ctx.guild
        channel = ctx.channel
        # setdefault, not [], because init() only seeds guilds present at startup
        cooldowns = self.cooldowns.setdefault(guild.id, {})
        if cooldowns.get(ctx.author.id, 0) > time.time():
            left = cooldowns.get(ctx.author.id, 0) - time.time()
            return await ctx.send(
                "Sorry, that command is on cooldown for {:.0f} seconds.".format(left), delete_after=left
            )
        else:
            cooldown = await self.config.guild(guild).cooldown()
            cooldowns[ctx.author.id] = time.time() + cooldown

        tags = [t for t in tags.split(",") if t != ""]
        filters = await self.config.guild(guild).filters()
        channel_filters = await self.config.channel(channel).filters()
        filters = filters if len(channel_filters) == 0 else channel_filters
        verbose = await self.config.guild(guild).verbose()
        display_artist = await self.config.guild(guild).display_artist()

        artist = "unknown artist"
        artists = ""
        artistList = []
        embedLink = ""
        embedTitle = ""
        imageId = ""
        message = ""
        output = None
        rating = ""
        ratingColor = "FFFFFF"
        ratingWord = "unknown"
        search = "https://derpibooru.org/api/v1/json/search/images?q="
        tagSearch = ""

        if tags:
            # Parenthesised so the user's search resolves before the filters, otherwise
            # an OR in their query swallows them.
            tagSearch += "({})".format(", ".join(tags)).strip().strip(",")
        if not mascot:
            if filters != [] and tags:
                tagSearch += ", "
            tagSearch += ", ".join(filters)

        search += parse.quote_plus(tagSearch)
        if search[-1] == "=":
            search += "safe"

        # filter_id=56027 is Derpibooru's "Everything" filter; our own tags do the
        # gating, so the site-side filter must not narrow the pool first.
        if randomize:
            if not tags and not filters:
                search = "https://derpibooru.org/api/v1/json/search/images?q=safe&sf=random&filter_id=56027&per_page=1"
            else:
                search += "&sf=random&filter_id=56027&per_page=1"
        else:
            search += "&filter_id=56027&per_page=1"

        # Also covers the 5s pause when a challenge has to be solved.
        message = await ctx.send("Fetching pony image...")

        try:
            website = await self.derpi_fetch(search)
        except DerpiCold as e:
            left = humanize_timedelta(seconds=max(1, int(e.remaining)))
            return await message.edit(content=f"Derpibooru is under heavy load. Try again in {left}.")
        except DerpiBusy as e:
            log.info("derpibooru busy: %s", e)
            return await message.edit(content="Derpibooru is under load right now. Try again in a moment.")
        except DerpiError as e:
            log.error("derpibooru request failed: %s", e)
            return await message.edit(content="Error! Contact bot owner.")

        try:
            if website["total"] > 0:
                website = website["images"][0]
                imageId = website["id"]
                imageURL = website["representations"]["full"]
            else:
                return await message.edit(content="Your search terms gave no results.")
        except (KeyError, IndexError, TypeError) as e:
            log.error("unexpected derpibooru response shape: %s", e)
            return await message.edit(content="Error! Contact bot owner.")

        if verbose:
            embedTitle = "Derpibooru Image #{}".format(imageId)
            embedLink = "https://derpibooru.org/{}".format(imageId)
            tagList = website["tags"]

            # Pops the rating out of tagList so it isn't repeated in the tag field.
            for i in range(0, len(tagList)):
                if tagList[i] == "safe":
                    ratingColor = "00FF00"
                    ratingWord = tagList.pop(i)
                    break
                elif tagList[i] == "suggestive":
                    ratingColor = "FFFF00"
                    ratingWord = tagList.pop(i)
                    break
                elif tagList[i] == "questionable":
                    ratingColor = "FF9900"
                    ratingWord = tagList.pop(i)
                    break
                elif tagList[i] == "explicit":
                    ratingColor = "FF0000"
                    ratingWord = tagList.pop(i)
                    break

            toRemove = []
            for tag in tagList:
                if "artist:" in tag:
                    artistList.append(tag[7:])
                    toRemove.append(tag)

            tagList = list(set(tagList) - set(toRemove))

            if len(artistList) == 1:
                artist = artistList[0]
            elif len(artistList) > 1:
                artists = ", ".join(artistList)
                artist = ""

            output = discord.Embed(title=embedTitle, url=embedLink, colour=discord.Colour(value=int(ratingColor, 16)))
            output.add_field(name="Rating", value=ratingWord)
            if artist:
                output.add_field(name="Artist", value=artist)
            elif artists:
                output.add_field(name="Artists", value=artists)
            output.add_field(name="Tags", value=", ".join(tagList), inline=False)
            output.add_field(name="Search url", value=search)
            output.set_thumbnail(url=imageURL)
        else:
            output = imageURL

        if verbose:
            return await message.edit(content="Image found.", embed=output)
        elif display_artist:
            for tag in website["tags"]:
                if "artist:" in tag:
                    artistList.append(tag[7:])

            if len(artistList) == 1:
                artist = artistList[0]
            elif len(artistList) > 1:
                artists = ", ".join(artistList)
                artist = ""

            if artist:
                return await message.edit(content=f"Artist: `{artist}`\n{output}")
            else:
                return await message.edit(content=f"Artists: `{artists}`\n{output}")
        else:
            return await message.edit(content=output)

    async def red_delete_data_for_user(
        self,
        *,
        requester: Literal["discord_deleted_user", "owner", "user", "user_strict"],
        user_id: int,
    ):
        pass
