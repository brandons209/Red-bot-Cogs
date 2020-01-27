import discord
from redbot.core.utils.chat_formatting import *
from redbot.core import Config, checks, commands
from urllib import parse
import aiohttp
import os
import traceback
import json


class Pony(commands.Cog):
    def __init__(self):
        super().__init__()

        self.config = Config.get_conf(self, identifier=7384662719)
        default_global = {"maxfilters": 50}
        self.default_guild = {"filters": ["-meme", "safe", "-spoiler:*", "-vulgar"], "verbose": False}
        self.config.register_guild(**self.default_guild)
        self.config.register_global(**default_global)

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
    @commands.command(pass_context=True)
    async def mascot(self, ctx):
        """
        Gives a random picture of our mascot!
        """
        await fetch_image(self, ctx, randomize=True, mascot=True, tags=["safe,", "coe"])

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
            filter_list = "\n".join(sorted(filters["default"]))
            target_guild = "Default"
        await ctx.send("{} pony filter list contains:```\n{}```".format(target_guild, filter_list))

    @commands.group()
    @checks.admin()
    async def ponyset(self, ctx):
        """Manages pony options"""
        pass

    @ponyset.command(name="verbose")
    async def _verbose_ponyset(self, ctx, toggle: str = "toggle"):
        """Toggles verbose mode"""
        guild = ctx.guild
        verbose = await self.config.guild(guild).verbose()
        if toggle.lower() == "on" or toggle.lower() == "true" or toggle.lower() == "enable":
            if not verbose:
                await self.config.guild(guild).verbose.set(True)
                await ctx.send("Verbose mode is now enabled.")
            else:
                await ctx.send("Verbose mode is already enabled.")
        elif toggle.lower() == "off" or toggle.lower() == "false" or toggle.lower() == "disable":
            if verbose:
                await self.config.guild(guild).verbose.set(False)
                await ctx.send("Verbose mode is now disabled.")
            else:
                await ctx.send("Verbose mode is already disabled.")
        else:
            if verbose:
                await self.config.guild(guild).verbose.set(False)
                await ctx.send("Verbose mode is now disabled.")
            else:
                await self.config.guild(guild).verbose.set(True)
                await ctx.send("Verbose mode is now enabled.")

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
        filters = await self.config.guild(guild).filters()
        verbose = await self.config.guild(guild).verbose()

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
        search = "https://derpibooru.org/search.json?q="
        tagSearch = ""

        # Assign tags to URL
        if tags:
            tagSearch += "{} ".format(" ".join(tags)).strip()
        if filters and not mascot:
            if filters != [] and tags:
                tagSearch += ", "
            tagSearch += ", ".join(filters)
        elif not mascot:
            if tags:
                tagSearch += ", "
            tagSearch += ", ".join(filters)

        search += parse.quote_plus(tagSearch)

        # Randomize results and apply Derpibooru's "Everything" filter
        if randomize:
            if not tags and filters:
                if filters == []:
                    search = "https://derpibooru.org/images/random.json?filter_id=56027"
                else:
                    search += "&random_image=y&filter_id=56027"
            else:
                search += "&random_image=y&filter_id=56027"

        # Inform users about image retrieving
        message = await ctx.send("Fetching pony image...")

        # Fetch the image or display an error
        try:
            async with aiohttp.ClientSession(loop=ctx.bot.loop) as session:
                async with session.get(search, headers={"User-Agent": "Booru-Cogs (https://git.io/booru)"}) as r:
                    website = await r.json()
            if randomize:
                if "id" in website:
                    imageId = str(website["id"])
                    async with aiohttp.ClientSession(loop=ctx.bot.loop) as session:
                        async with session.get("https://derpibooru.org/images/" + imageId + ".json") as r:
                            website = await r.json()
                    imageURL = "https:{}".format(website["image"])
                else:
                    return await message.edit(content="Your search terms gave no results.")
            else:
                if website["search"] != []:
                    website = website["search"][0]
                    imageURL = "https:{}".format(website["image"])
                else:
                    return await message.edit(content="Your search terms gave no results.")
        except:
            return await message.edit(content="Error. {}".format(traceback.format_exc()))

        # If verbose mode is enabled, create an embed and fill it with information
        if verbose:
            # Sets the embed title
            embedTitle = "Derpibooru Image #{}".format(imageId)

            # Sets the URL to be linked
            embedLink = "https://derpibooru.org/{}".format(imageId)

            # Populates the tag list
            tagList = website["tags"].split(", ")

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
            for i in range(0, len(tagList)):
                if "artist:" in tagList[i]:
                    while "artist:" in tagList[i]:
                        artistList.append(tagList.pop(i)[7:])
                    break

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
        else:
            return await message.edit(content=output)
