import discord
from redbot.core.utils.chat_formatting import italics, pagify, box
from redbot.core import Config, checks, commands
import random
from random import choice
from typing import Literal

import asyncio
import os
import json
import re

mention = re.compile("<@(\d{18})>")
mention_bang = re.compile("<@!(\d{18})>")


class RolePlay(commands.Cog):
    def __init__(self, bot):
        super().__init__()

        mass_mentions = True
        self.config = Config.get_conf(self, identifier=3674895735)
        self.bot = bot
        self.default_guild = {
            "slap_items": [
                "a floppy disk",
                "a book",
                "a nuke",
                "a loaf of bread",
                "my hand",
                "a pack of ramen",
                "lotsa spaghetti",
                "a brick",
                "a slice of cheese",
                "my foot",
            ],
            "high_iq_msgs": [
                "wow!",
                "that's pretty big.",
                ":wink:",
                "niiicceee.",
                "someone here is actually smart.",
                "thats a dab.",
                "<:aureliawink:549481308519399425>",
                "you must of watched Rick and Morty.",
            ],
            "low_iq_msgs": [
                ":rofl:",
                "oof.",
                "you must have a lot of trouble in life.",
                "damn.",
                "awww you're special aren't you.",
                ":crying_cat_face:",
                "god I'm sorry (not).",
                "I didn't know people could have IQ that low.",
            ],
        }

        self.config.register_guild(**self.default_guild)
        # remove commands we are replacing
        bot.remove_command("hug")
        bot.remove_command("flip")

    def get_user_and_intensity(self, guild: discord.Guild, target: str):
        target = target.strip()
        user = None
        intensity = 1
        # mentions can be <@! or <@
        user_ment = mention.match(target)
        user_ment_b = mention_bang.match(target)

        # try with no intensity specified and not a mention
        if not user_ment or not user_ment_b:
            user = guild.get_member_named(target)

        # has intensity, could be a mention/text
        if not user:
            try:
                args = target.split()
                intensity = int(args[-1])
                name = " ".join(args[:-1])
                # not a mention
                user = guild.get_member_named(name)
                # parse mention
                if not user:
                    user_ment = mention.match(name)
                    user_ment_b = mention_bang.match(name)
            except:
                pass

        if not user:
            if user_ment:
                user = guild.get_member(int(user_ment.group(1)))
            elif user_ment_b:
                user = guild.get_member(int(user_ment_b.group(1)))
            else:
                user = None

        return user, intensity

    @commands.command(usage="<hug_target> <intensity>")
    @commands.guild_only()
    async def hug(self, ctx, *, hug_target: str):
        """Hugs a user with optional intensity!
        Example: .hug *username* 4

        Up to 10 intensity levels."""
        user, intensity = self.get_user_and_intensity(ctx.guild, hug_target)

        if user is not None:
            name = italics(user.display_name)
            if intensity <= 0:
                msg = "(っ˘̩╭╮˘̩)っ" + name
            elif intensity <= 3:
                msg = "(っ´▽｀)っ" + name
            elif intensity <= 6:
                msg = "╰(*´︶`*)╯" + name
            elif intensity <= 9:
                msg = "(つ≧▽≦)つ" + name
            elif intensity >= 10:
                msg = "(づ￣ ³￣)づ {} ⊂(´・ω・｀⊂)".format(name)
            await ctx.send(msg)
        else:
            await ctx.send("Member not found.")

    @commands.command()
    async def grouphug(self, ctx, intensity: int, *users: discord.Member):
        """
        Give a group hug to multiple users!

        If not pinging, you must put quotes around names with spaces
        Can also use user ids
        """
        if not users:
            await self.bot.send_help_for(ctx, "grouphug")
            return

        names = [italics(user.display_name) for user in users]
        names = ", ".join(names)

        if intensity <= 0:
            msg = "(っ˘̩╭╮˘̩)っ {} ⊂(˘̩╭╮˘̩⊂)".format(names)
        elif intensity <= 3:
            msg = "(っ´▽｀)っ {} ⊂(￣▽￣⊂)".format(names)
        elif intensity <= 6:
            msg = "╰(*´︶`*)╯ {} ╰(*´︶`*)╯".format(names)
        elif intensity <= 9:
            msg = "(つ≧▽≦)つ {} ⊂(・▽・⊂)".format(names)
        elif intensity >= 10:
            msg = "(づ￣ ³￣)づ {} ⊂(´・ω・｀⊂)".format(names)

        await ctx.send(msg)

    @commands.group(invoke_without_command=True)
    async def slap(self, ctx, *, user: discord.Member = None):
        """Slap a user"""
        guild = ctx.guild
        slap_items = await self.config.guild(guild).slap_items()
        botid = ctx.bot.user.id
        if user is None:
            user = ctx.message.author
            await ctx.send("Don't make me slap you instead " + user.display_name)
            return
        elif user.id == botid:
            user = ctx.message.author
            botname = ctx.bot.user.name
            await ctx.send(
                "`-" + botname + " slaps " + user.display_name + " multiple times with " + (choice(slap_items) + "-`")
            )
        else:
            await ctx.send("`-slaps " + user.display_name + " with " + (choice(slap_items) + "-`"))

    @slap.command(name="add")
    @checks.admin()
    async def _add_slap(self, ctx, *, slap_item):
        """Adds an item to use for slaps!"""
        guild = ctx.guild
        slap_items = await self.config.guild(guild).slap_items()
        if slap_item not in slap_items:
            async with self.config.guild(guild).slap_items() as current_slaps:
                current_slaps.append(slap_item)
            await ctx.send("Item '{}' added to the server's slap items list.".format(slap_item))
        else:
            await ctx.send("Item '{}' is already in the server's slap item list.".format(slap_item))

    @slap.command(name="remove")
    @checks.admin()
    async def _remove_slap(self, ctx, slap_item: str = ""):
        """Removes item to use for slaps!"""
        guild = ctx.guild
        slap_items = await self.config.guild(guild).slap_items()
        if slap_item in slap_items:
            async with self.config.guild(guild).slap_items() as current_slaps:
                current_slaps.remove(slap_item)
            await ctx.send("Item '{}' deleted from the server's slap items list.".format(slap_item))
        else:
            await ctx.send("Item '{}' does not exist in the server's slap items list.".format(slap_item))

    @slap.command(name="list")
    @checks.admin()
    async def _list_slap(self, ctx):
        """Prints list of slaps"""
        guild = ctx.guild
        slap_items = await self.config.guild(guild).slap_items()
        msg = ""
        for item in slap_items:
            msg += "+ {}\n".format(item)
        pages = pagify(msg)  # pages is an iterator of pages

        for page in pages:
            await ctx.send(box(page, lang="diff"))

    @slap.command(name="import")
    @checks.is_owner()
    async def _import_slap(self, ctx, path_to_import):
        """Imports slaps from jsons.

        Specifiy the **path** to the json to import slaps from.

        *i.e.: /path/containing/json/*"""
        bot = ctx.bot
        guild = ctx.guild
        path_to_slaps = os.path.join(path_to_import, "items.json")

        try:
            with open(path_to_slaps) as raw_slaps:
                import_slaps = json.load(raw_slaps)
                await self.config.guild(guild).slap_items.set(import_slaps)
                await ctx.send("Slaps imported.")
        except FileNotFoundError:
            await ctx.send("Invalid path to json file.")
        except json.decoder.JSONDecodeError:
            await ctx.send("Invalid or malformed json file.")

    @commands.group(invoke_without_command=True)
    async def iq(self, ctx, *users: discord.Member):
        """
        Gets IQ of a user. Use multiple users to compare IQs
        """
        if not users:
            await ctx.bot.send_help_for(ctx, self.iq)
            return
        guild = ctx.guild
        high_iq_msgs = await self.config.guild(guild).high_iq_msgs()
        low_iq_msgs = await self.config.guild(guild).low_iq_msgs()
        state = random.getstate()
        iqs = {}
        msg = ""
        for user in users:
            if user.id == 216319397944492033 or user.id == 213027180865781761 or user.id == 559915721627402241:
                iqs[user] = "0"
            else:
                random.seed(user.id)
                iqs[user] = "{}".format(random.randint(0, 250))

        random.setstate(state)
        iqs = sorted(iqs.items(), key=lambda x: x[1])

        for user, iq in iqs:
            msg += "{}'s iq is {}, {}\n".format(
                user.display_name, iq, choice(high_iq_msgs) if int(iq) > 130 else choice(low_iq_msgs)
            )

        await ctx.send(msg)

    @iq.command(name="list")
    @checks.admin()
    async def _list_iq(self, ctx):
        """Prints a list of all IQ phrases."""
        guild = ctx.guild
        high_iq_msgs = await self.config.guild(guild).high_iq_msgs()
        low_iq_msgs = await self.config.guild(guild).low_iq_msgs()
        msg1 = "HIGH IQ PHRASES:\n"
        msg2 = "LOW IQ PHRASES:\n"

        for high_phrase in high_iq_msgs:
            msg1 += "+ {}\n".format(high_phrase)
        high_pages = pagify(msg1)  # pages is an iterator of pages

        for low_phrase in low_iq_msgs:
            msg2 += "+ {}\n".format(low_phrase)
        low_pages = pagify(msg2)  # pages is an iterator of pages

        for high_page in high_pages:
            await ctx.send(box(high_page, lang="diff"))

        for low_page in low_pages:
            await ctx.send(box(low_page, lang="diff"))

    @iq.command(name="addhigh")
    @checks.admin()
    async def _addhigh_iq(self, ctx, *, new_high_iq_msg: str):
        """Adds a postive phrase for high IQ results!"""
        guild = ctx.guild
        high_iq_msgs = await self.config.guild(guild).high_iq_msgs()
        if new_high_iq_msg not in high_iq_msgs:
            async with self.config.guild(guild).high_iq_msgs() as current_hi_iq_msgs:
                current_hi_iq_msgs.append(new_high_iq_msg)
            await ctx.send("Phrase '{}' added to the server's High IQ list.".format(new_high_iq_msg))
        else:
            await ctx.send("Phrase '{}' is already in the server's High IQ list.".format(new_high_iq_msg))

    @iq.command(name="addlow")
    @checks.admin()
    async def _addlow_iq(self, ctx, *, new_low_iq_msg: str):
        """Adds a derogatory phrase for low IQ results!"""
        guild = ctx.guild
        low_iq_msgs = await self.config.guild(guild).low_iq_msgs()
        if new_low_iq_msg not in low_iq_msgs:
            async with self.config.guild(guild).low_iq_msgs() as current_low_iq_msgs:
                current_low_iq_msgs.append(new_low_iq_msg)
            await ctx.send("Phrase '{}' added to the server's Low IQ list. Heh, nice one.".format(new_low_iq_msg))
        else:
            await ctx.send("Phrase '{}' is already in the server's Low IQ list.".format(new_low_iq_msg))

    @iq.command(name="removehigh")
    @checks.admin()
    async def _removehigh_iq(self, ctx, high_phrase: str = ""):
        """Removes phrases for high IQ's!"""
        guild = ctx.guild
        high_iq_msgs = await self.config.guild(guild).high_iq_msgs()
        if high_phrase in high_iq_msgs:
            async with self.config.guild(guild).high_iq_msgs() as current_phrases:
                current_phrases.remove(high_phrase)
            await ctx.send("Phrase '{}' deleted from the server's high IQ messages.".format(high_phrase))
        elif high_phrase == "":
            if self.default_guild["high_iq_msgs"] != high_iq_msgs:
                await self.config.guild(guild).high_iq_msgs.set(self.default_guild["high_iq_msgs"])
                await ctx.send("Reverted the server to the default high IQ messages.")
            else:
                await ctx.send("Server is already using the default high IQ messages.")
        else:
            await ctx.send("Phrase '{}' does not exist in the server's high IQ messages.".format(high_phrase))

    @iq.command(name="removelow")
    @checks.admin()
    async def _removelow_iq(self, ctx, low_phrase: str = ""):
        """Removes phrases for low IQ's!"""
        guild = ctx.guild
        low_iq_msgs = await self.config.guild(guild).low_iq_msgs()
        if low_phrase in low_iq_msgs:
            async with self.config.guild(guild).low_iq_msgs() as current_phrases:
                current_phrases.remove(low_phrase)
            await ctx.send("Phrase '{}' deleted from the server's low IQ messages.".format(low_phrase))
        elif low_phrase == "":
            if self.default_guild["low_iq_msgs"] != low_iq_msgs:
                await self.config.guild(guild).low_iq_msgs.set(self.default_guild["low_iq_msgs"])
                await ctx.send("Reverted the server to the default low IQ messages.")
            else:
                await ctx.send("Server is already using the default low IQ messages.")
        else:
            await ctx.send("Phrase '{}' does not exist in the server's low IQ messages.".format(low_phrase))

    @commands.command()
    @commands.cooldown(1, 6, commands.BucketType.guild)
    async def army(self, ctx, horses: int):
        """
        Summon an army of Aurelias. Max 20
        """
        army_emoji = "<a:trottingaurelia:568577886164877312>"
        if horses > 20:
            await ctx.send("Too many Aurelias!")
            return
        msg = ""
        if horses == 1:
            largest_factor = 1
        else:
            largest_factor = [x for x in range(1, horses) if horses % x == 0][-1]
        # largest_factor = [x for x in largest_factor if x <= 15][-1]
        if largest_factor == 1:
            largest_factor = horses
            rows = 1
        else:
            rows = horses // largest_factor
        rows = rows if rows > 0 else 1
        for _ in range(rows):
            for _ in range(largest_factor):
                msg += "{} ".format(army_emoji)
            msg += "\n"
            if len(msg) + len(army_emoji) + 20 > 2000:
                await ctx.send(msg)
                msg = ""

        if msg != "":
            await ctx.send(msg)

    @commands.command(usage="<boop_target> <intensity>")
    @commands.guild_only()
    async def boop(self, ctx, *, boop_target: str):
        """
        Boops a user. 10 intensity levels.
        """
        user, intensity = self.get_user_and_intensity(ctx.guild, boop_target)
        if user is not None:
            name = italics(user.display_name)
            if intensity <= 3:
                msg = "/) {}".format(name)
            elif intensity <= 6:
                msg = "**/)** {}".format(name)
            elif intensity <= 9:
                msg = "**__/)__** {}".format(name)
            elif intensity >= 10:
                msg = "**__/)__** {} **__(\\\__**".format(name)
            await ctx.send(msg)
        else:
            await ctx.send("Can't boop what I can't see!")

    @commands.command()
    @commands.guild_only()
    async def bap(self, ctx, *, user: discord.Member):
        """
        Baps a user
        """
        if user.id == ctx.bot.user.id:
            await ctx.send(":newspaper2: :newspaper2: :newspaper2: " + italics(ctx.message.author.display_name))
        else:
            if ctx.guild.id == 508496957350608906:
                await ctx.send(italics(user.display_name) + " <:aureliabagu:678829441178271770>")
            else:
                await ctx.send(":newspaper2: " + italics(user.display_name))

    @commands.command()
    async def flip(self, ctx, *, user: discord.Member = None):
        """Flip a coin... or a user.
        Defaults to a coin.
        """
        if user is not None:
            msg = ""
            if user.id == ctx.bot.user.id:
                user = ctx.author
                msg = "Nice try. You think this is funny?\n How about *this* instead:\n\n"
            char = "abcdefghijklmnopqrstuvwxyz"
            tran = "ɐqɔpǝɟƃɥᴉɾʞlɯuodbɹsʇnʌʍxʎz"
            table = str.maketrans(char, tran)
            name = user.display_name.translate(table)
            char = char.upper()
            tran = "∀qƆpƎℲפHIſʞ˥WNOԀQᴚS┴∩ΛMX⅄Z"
            table = str.maketrans(char, tran)
            name = name.translate(table)
            await ctx.send(msg + "(╯°□°）╯︵ " + name[::-1])
        else:
            await ctx.send("*flips a coin and... " + choice(["HEADS!*", "TAILS!*"]))

    async def red_delete_data_for_user(
        self,
        *,
        requester: Literal["discord_deleted_user", "owner", "user", "user_strict"],
        user_id: int,
    ):
        pass
