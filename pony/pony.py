import discord
from redbot.core.utils.chat_formatting import *
from redbot.core import Config, checks, commands
from urllib import parse
from typing import Literal
import aiohttp
import os
import traceback
import json
import asyncio
import time


class Pony(commands.Cog):
    def __init__(self, bot):
        super().__init__()
        self.bot = bot
        self.config = Config.get_conf(self, identifier=7384662719)
        default_global = {"maxfilters": 50}
        self.default_guild = {
            "filters": ["-meme", "safe", "-spoiler:*", "-vulgar"],
            "verbose": False,
            "display_artist": False,
            "cooldown": 10,
        }
        self.cooldowns = {}
        self.config.register_guild(**self.default_guild)
        self.config.register_global(**default_global)

        self.task = asyncio.create_task(self.init())

    def cog_unload(self):
        if self.task:
            self.task.cancel()

    async def init(self):
        """
        Setup cooldown cache
        """
        await self.bot.wait_until_ready()
        for guild in self.bot.guilds:
            self.cooldowns[guild.id] = {}

    @commands.command()
    @commands.guild_only()
    async def pony(self, ctx, *text):
        """Retrieves the latest result from Derpibooru"""
        await self.fetch_image(ctx, randomize=False, tags=text)

    @commands.command()
    @commands.guild_only()
    async def ponyr(self, ctx, *text):
        """Retrieves a random result from Derpibooru"""
        await self.fetch_image(ctx, randomize=True, tags=text)

    # needed because derpi was having trouble getting a random image from our derpi page with the filters we have
    @commands.command()
    @commands.guild_only()
    async def mascot(self, ctx):
        """
        Gives a random picture of our mascot!
        """
        await self.fetch_image(ctx, randomize=True, mascot=True, tags=["safe,", "coe"])

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
    async def _maxfilters_ponyset(self, ctx, new_max_filters: int):
        """Sets the global tag limit for the filter list.

        Leave blank to get current max filters.

        Gives an error when a user tries to add a filter while the server's filter list contains a certain amount of tags"""
        if new_max_filters is None:
            max_filters = self.config.maxfilters()
            await ctx.send("Current filter limit: {} filters.".format(max_filters))
            return

        guild = ctx.guild
        await self.config.maxfilters.set(new_max_filters)
        await ctx.send("Maximum filters allowed per server for pony set to '{}'.".format(new_max_filters))

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

    async def fetch_image(self, ctx, randomize: bool = False, tags: list = [], mascot=False):
        guild = ctx.guild

        # check cooldown
        if self.cooldowns[guild.id].get(ctx.author.id, 0) > time.time():
            left = self.cooldowns[guild.id].get(ctx.author.id, 0) - time.time()
            return await ctx.send(
                "Sorry, that command is on cooldown for {:.0f} seconds.".format(left), delete_after=left
            )
        else:
            cooldown = await self.config.guild(guild).cooldown()
            self.cooldowns[guild.id][ctx.author.id] = time.time() + cooldown

        filters = await self.config.guild(guild).filters()
        verbose = await self.config.guild(guild).verbose()
        display_artist = await self.config.guild(guild).display_artist()

        # Initialize variables
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

        # Assign tags to URL
        if tags:
            tagSearch += "{} ".format(" ".join(tags)).strip().strip(",")
        if filters and not mascot:
            if filters != [] and tags:
                tagSearch += ", "
            tagSearch += ", ".join(filters)
        elif not mascot:
            if tags:
                tagSearch += ", "
            tagSearch += ", ".join(filters)

        search += parse.quote_plus(tagSearch)
        if search[-1] == "=":
            search += "safe"

        # Randomize results and apply Derpibooru's "Everything" filter
        if randomize:
            if not tags and not filters:
                search = "https://derpibooru.org/api/v1/json/search/images?q=safe&sf=random&filter_id=56027&per_page=1"
            else:
                search += "&sf=random&filter_id=56027&per_page=1"
        else:
            search += "&filter_id=56027&per_page=1"

        # Inform users about image retrieving
        message = await ctx.send("Fetching pony image...")

        # Fetch the image or display an error
        try:
            async with aiohttp.ClientSession(loop=ctx.bot.loop) as session:
                async with session.get(search, headers={"User-Agent": "Booru-Bot"}) as r:
                    website = await r.json()
            if website["total"] > 0:
                website = website["images"][0]
                imageId = website["id"]
                imageURL = website["representations"]["full"]
            else:
                return await message.edit(content="Your search terms gave no results.")
        except Exception as e:
            traceback.print_exc()
            return await message.edit(content="Error! Contact bot owner.")

        # If verbose mode is enabled, create an embed and fill it with information
        if verbose:
            # Sets the embed title
            embedTitle = "Derpibooru Image #{}".format(imageId)

            # Sets the URL to be linked
            embedLink = "https://derpibooru.org/{}".format(imageId)

            # Populates the tag list
            tagList = website["tags"]

            # Checks for the rating and sets an appropriate color
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

            # Grabs the artist(s)
            toRemove = []
            for tag in tagList:
                if "artist:" in tag:
                    artistList.append(tag[7:])
                    toRemove.append(tag)

            tagList = list(set(tagList) - set(toRemove))

            # Determine if there are multiple artists
            if len(artistList) == 1:
                artist = artistList[0]
            elif len(artistList) > 1:
                artists = ", ".join(artistList)
                artist = ""

            # Initialize verbose embed
            output = discord.Embed(title=embedTitle, url=embedLink, colour=discord.Colour(value=int(ratingColor, 16)))

            # Sets the thumbnail and adds the rating and tag fields to the embed
            output.add_field(name="Rating", value=ratingWord)
            if artist:
                output.add_field(name="Artist", value=artist)
            elif artists:
                output.add_field(name="Artists", value=artists)
            output.add_field(name="Tags", value=", ".join(tagList), inline=False)
            output.add_field(name="Search url", value=search)
            output.set_thumbnail(url=imageURL)
        else:
            # Sets the link to the image URL if verbose mode is not enabled
            output = imageURL

        # Edits the pending message with the results
        if verbose:
            return await message.edit(content="Image found.", embed=output)
        elif display_artist:
            for tag in website["tags"]:
                if "artist:" in tag:
                    artistList.append(tag[7:])

            # Determine if there are multiple artists
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
