import discord
from redbot.core.utils.chat_formatting import italics, pagify, box, warning
from redbot.core import Config, checks, commands
import random
from random import choice
from typing import Literal, Optional

import re

mention = re.compile(r"<@!?(\d{18})>")  # This will handle both <@user_id> and <@!user_id>


class RolePlay(commands.Cog):
    def __init__(self, bot):
        super().__init__()

        self.mass_mentions = True
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
        intensity = 1  # Default intensity

        # Check if the target contains intensity and mention or just the name with intensity
        args = target.split()

        # If the last part of the target is a digit, treat it as intensity
        if args[-1].isdigit():
            intensity = int(args[-1])
            target = " ".join(args[:-1])  # Everything before the last part is the user name

        # Try matching the mention format first
        user_ment = mention.match(target)

        if user_ment:
            # If it's a mention, extract the user by ID
            user = guild.get_member(int(user_ment.group(1)))
        else:
            # If not a mention, try to get the member by name
            user = guild.get_member_named(target)

        # If the user wasn't found by name, try again by matching the mention format
        if not user:
            user_ment = mention.match(target)
            if user_ment:
                user = guild.get_member(int(user_ment.group(1)))

        return user, intensity

    @commands.hybrid_command(usage="<hug_target> <intensity>")
    @commands.guild_only()
    async def hug(self, ctx, *, input: str):
        """Hugs a user with optional intensity!
        Example: .hug *username* 4

        Up to 10 intensity levels."""
        user, intensity = self.get_user_and_intensity(ctx.guild, input)
        if user is None:
            await ctx.send(warning(f"I can't see {input}!"))
            return

        name = italics(user.display_name)
        msg = ""
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

    @commands.hybrid_command(usage="<snug_target> <intensity>")
    async def snug(self, ctx, *, input: str):
        """Snugs a user with optional intensity!
        Example: .snug *username* 4

        Up to 10 intensity levels."""
        user, intensity = self.get_user_and_intensity(ctx.guild, input)
        if user is None:
            await ctx.send(warning(f"I can't see {input}!"))
            return

        name = italics(user.display_name)
        msg = ""
        if intensity <= 0:
            msg = "(>^w^)> {} <('w'<)".format(name)
        elif intensity <= 3:
            msg = "(づ｡◕‿‿◕｡)づ {} <( ‘ w ‘ )>".format(name)
        elif intensity <= 6:
            msg = "(∩˃̣̣̣̣̣̣̣̣̣̣̣̣̣̣̣̣̣̣̣̣̣̣̣̣̣̣̣̣̣̣˃̣̣̣̣̣̣̣̣̣̣̣̣̣̣̣̣̣˂){} <( ‘ w ‘ )>".format(name)
        elif intensity <= 9:
            msg = "(っ´∀｀)っ {} (´∇｀*)".format(name)
        elif intensity >= 10:
            msg = "(づ｡◕‿‿◕｡)づ {} ٩(◕‿◕｡)۶".format(name)

        await ctx.send(msg)

    @commands.hybrid_command(usage="<snuzz_target> <intensity>")
    async def snuzz(self, ctx, *, input: str):
        """Snuzzles a user with optional intensity!
        Example: .snuzz username 4

        Up to 10 intensity levels."""
        user, intensity = self.get_user_and_intensity(ctx.guild, input)
        if user is None:
            await ctx.send(warning(f"I can't see {input}!"))
            return

        name = italics(user.display_name)
        msg = ""
        if intensity <= 0:
            # Almost no snuzz
            msg = f"{name} gently snuzzles the air... (˘ω˘ )"
        elif intensity <= 3:
            # Light snuzz
            msg = f"{name} gets their fluff nuzzled lovingly~ >w<"
        elif intensity <= 6:
            # Medium snuzz
            msg = f"{name} receives a cozy nuzzle! (๑˘︶˘๑)¨*"
        elif intensity <= 9:
            # Big snuzz
            msg = f"{name} is enveloped in snuggly snuzzles! (づ｡◕‿‿◕｡)づ"
        else:
            # Maximum snuzz
            msg = f"{name} is overwhelmed by non-stop snuzzling!!! (≧◡≦) ♡"

        await ctx.send(msg)

    @commands.hybrid_command(usage="<pat_target> <intensity>")
    async def pat(self, ctx, *, input: str):
        """Pats a user with optional intensity!
        Example: .pat username 4

        Up to 10 intensity levels."""
        user, intensity = self.get_user_and_intensity(ctx.guild, input)
        if user is None:
            await ctx.send(warning(f"I can't see {input}!"))
            return

        name = italics(user.display_name)

        if intensity <= 0:
            # Almost no pat
            msg = f"(・_・)つ {name}"
        elif intensity <= 3:
            # Gentle pat
            msg = f"(；^＿^)/)☆(　゜o゜) **pats {name}**"
        elif intensity <= 6:
            # Medium pat
            msg = f"(＾・ω・＾)つ**pats {name}**"
        elif intensity <= 9:
            # Big pat
            msg = f"ヽ(≧∀≦)ﾉ **big pats for  {name}!**"
        else:
            # Maximum pat attack
            msg = f"(((o(*ﾟ▽ﾟ*)o))) **pat attack on   {name}!**"

        await ctx.send(msg)

    @commands.hybrid_command(usage="<glomp_target> <intensity>")
    async def glomp(self, ctx, *, input: str):
        """Glomps a user with optional intensity!
        Example: .glomp username 4

        Up to 10 intensity levels."""
        user, intensity = self.get_user_and_intensity(ctx.guild, input)
        if user is None:
            await ctx.send(warning(f"I can't see {input}!"))
            return

        author = italics(ctx.author.display_name)
        name = italics(user.display_name)
        msg = ""

        if intensity <= 0:
            # Barely a glomp
            msg = f"{author} tiptoes up to {name} and gives a little nudgy glomp. (*´ω｀*)"
        elif intensity <= 3:
            # Gentle glomp
            msg = f"{author} glomps {name} gently! (っ´▽｀)っ"
        elif intensity <= 6:
            # Big old glomp
            msg = f"{author} charges at {name} and gives a big old glomp! ╰(*´︶`*)╯"
        elif intensity <= 9:
            # Enthusiastic tackle-glomp
            msg = f"{author} tackles {name} in a super enthusiastic glomp! (つ≧▽≦)つ"
        else:
            # Maximum, full-power glomp
            msg = f"{author} FULL-POWER GLOMP GLOMP glomps {name} with all their might!!! (^з^)-☆"

        await ctx.send(msg)

    @commands.hybrid_command(usage="<wuv_target> <intensity>")
    async def wuv(self, ctx, *, input: str):
        """Sends cutesy wuv to a user with optional intensity!
        Example: .wuv username 4

        Up to 10 intensity levels."""
        user, intensity = self.get_user_and_intensity(ctx.guild, input)
        if user is None:
            await ctx.send(warning(f"I can't see {input}!"))
            return

        name = italics(user.display_name)
        msg = ""

        if intensity <= 0:
            # A tiny bit of wuv
            msg = f"❤️ {name} ❤️"
        elif intensity <= 3:
            # Light wuv
            msg = f"💖 Sending soft wuv to {name} 💖"
        elif intensity <= 6:
            # Medium wuv
            msg = f"💘 {name}, you are so loved! 💘"
        elif intensity <= 9:
            # Big wuv
            msg = f"💝 Overflowing wuv for {name}! 💝"
        else:
            # Maximum, heart‑explosion wuv
            msg = f"💓💓💓 {name} is absolutely showered in wuv!!! 💓💓💓"

        await ctx.send(msg)

    @commands.hybrid_command(usage="<smooch_target> <intensity>")
    async def smooch(self, ctx, *, input: str):
        """Smooches a user with optional intensity!
        Example: .smooch username 4

        Up to 10 intensity levels."""
        user, intensity = self.get_user_and_intensity(ctx.guild, input)
        if user is None:
            await ctx.send(warning(f"I can't see {input}!"))
            return

        author = italics(ctx.author.display_name)
        name = italics(user.display_name)
        msg = ""

        if intensity <= 0:
            # Almost no smooch
            msg = f"{author} air-kisses {name}... *teehee*"
        elif intensity <= 3:
            # Light peck
            msg = f"{author} gives {name} a sweet little smooch on the cheek! 😘"
        elif intensity <= 6:
            # Classic kiss
            msg = f"{author} plants a soft kiss on {name}’s cheek! 😚"
        elif intensity <= 9:
            # Passionate smooch
            msg = f"{author} showers {name} with kisses! 😙💋"
        else:
            # Full smoochfest
            msg = f"{author} launches into a full-on smoochfest with {name}!!! 💋💋💋"

        await ctx.send(msg)

    @commands.hybrid_command(usage="<lick_target> <intensity>")
    async def lick(self, ctx, *, input: str):
        """Licks a user with optional intensity!
        Example: .lick username 4

        Up to 10 intensity levels. Pony‑themed!"""
        user, intensity = self.get_user_and_intensity(ctx.guild, input)
        if user is None:
            await ctx.send(warning(f"I can't see {input}!"))
            return

        name = italics(user.display_name)
        msg = ""

        if intensity <= 0:
            # Tiny, tentative pony poke
            msg = f"OwO What's this? **pretends to lick {name}**"
        elif intensity <= 3:
            # Light lick
            msg = f"UwU licks    {name} softly! :3"
        elif intensity <= 6:
            # Cozy pony nuzzle‐lick
            msg = f"(◕‿◕✿) Lick for {name}! *nom nom*"
        elif intensity <= 9:
            # Rainbow dash lick
            msg = f"(*￣3￣)ちゅっ licks {name}!"
        else:
            # Full‑on pony lick attack!
            msg = f"(✧ω✧) LICK ATTACK on {name}!!! /ᐠ｡‸｡ᐟ\\"

        await ctx.send(msg)

    @commands.hybrid_command(usage="<mlem_target> <intensity>")
    async def mlem(self, ctx, *, input: str):
        """Mlems a user with optional intensity!
        Example: .mlem username 4

        Up to 10 intensity levels."""
        user, intensity = self.get_user_and_intensity(ctx.guild, input)
        if user is None:
            await ctx.send(warning(f"I can't see {input}!"))
            return

        author = italics(ctx.author.display_name)
        name = italics(user.display_name)
        emoji = "<a:aureliamlem:662860677769330688>"
        msg = ""

        if intensity <= 0:
            # Barely a mlem
            msg = f"{author} barely mlems at {name}... {emoji}"
        elif intensity <= 3:
            # Gentle mlem
            msg = f"{author} gives {name} a soft little mlem! {emoji}"
        elif intensity <= 6:
            # Proper mlem
            msg = f"{author} leans in and mlems {name} lovingly! {emoji}"
        elif intensity <= 9:
            # Big mlem
            msg = f"{author} goes for a big, enthusiastic mlem on {name}! {emoji}"
        else:
            # Maximum mlem assault
            msg = f"{author} unleashes a MLEM OVERDRIVE on {name}!!! {emoji}{emoji}{emoji}"

        await ctx.send(msg)

    @commands.hybrid_command(usage="<scritch_target> <intensity>")
    async def scritch(self, ctx, *, input: str):
        """Scritches a user with optional intensity!
        Example: .scritch username 4

        Up to 10 intensity levels."""
        user, intensity = self.get_user_and_intensity(ctx.guild, input)
        if user is None:
            await ctx.send(warning(f"I can't see {input}!"))
            return

        author = italics(ctx.author.display_name)
        name = italics(user.display_name)
        msg = ""

        if intensity <= 0:
            # Barely a scritch
            msg = f"{author} scritches the air near {name}... (^.^)"
        elif intensity <= 3:
            # Light scritch
            msg = f"{author} scritch-scratches along the back of {name} comfortingly~"
        elif intensity <= 6:
            # Medium scritch
            msg = f"{author} gives {name} a soothing scritch down their spine! (⌒‿⌒)"
        elif intensity <= 9:
            # Big scritch
            msg = f"{author} practically rakes scritches across {name}! (≧◡≦)"
        else:
            # Maximum scritch storm
            msg = f"{author} unleashes a full scritch-storm on {name}!!! (*ﾉ>ω<)"

        await ctx.send(msg)

    @commands.hybrid_command(usage="<nibble_target> <intensity>")
    async def nibble(self, ctx, *, input: str):
        """Nibbles a user with optional intensity!
        Example: .nibble username 4

        Up to 10 intensity levels."""
        user, intensity = self.get_user_and_intensity(ctx.guild, input)
        if user is None:
            await ctx.send(warning(f"I can't see {input}!"))
            return

        author = italics(ctx.author.display_name)
        name = italics(user.display_name)
        msg = ""

        if intensity <= 0:
            # Just a gentle nuzzle
            msg = f"{author} softly nuzzles {name}'s neck... (~˘▾˘)~"
        elif intensity <= 3:
            # Light nibble
            msg = f"{author} grabs and nibbles the neck of {name} softly~ (｡>ω<｡)"
        elif intensity <= 6:
            # Playful nibble
            msg = f"{author} playfully nibbles at {name}'s ear and neck! (๑>ᴗ<๑)"
        elif intensity <= 9:
            # Enthusiastic nibble
            msg = f"{author} chomps on {name} with plenty of adorable nibbles! (≧ω≦)"
        else:
            # Full nibble blitz
            msg = f"{author} goes full nibble blitz on {name}! nom nom nom!!! (≧ڡ≦)"

        await ctx.send(msg)

    @commands.hybrid_command(usage="<bite_target> <intensity>")
    async def bite(self, ctx, *, input: str):
        """Bites a user with optional intensity!
        Example: .bite username 4

        Up to 10 intensity levels."""
        user, intensity = self.get_user_and_intensity(ctx.guild, input)
        if user is None:
            await ctx.send(warning(f"I can't see {input}!"))
            return

        author = italics(ctx.author.display_name)
        name = italics(user.display_name)
        msg = ""

        if intensity <= 0:
            # Sniff but no bite
            msg = f"*sniffs* {name} but decides not to bite... 🐾"
        elif intensity <= 3:
            # Gentle nom
            msg = f"{author} ***noms*** {name} gently! (＾• ω •＾)"
        elif intensity <= 6:
            # Playful chomp
            msg = f"{author} ***chomps*** {name} playfully! (๑•̀ㅁ•́๑)"
        elif intensity <= 9:
            # Gusto bite
            msg = f"{author} bites {name} with gusto! (ง˃̵ᴗ˂̵)ง"
        else:
            # Full bite attack
            msg = f"{author} unleashes a full bite attack on {name}! ***NOM NOM NOM*** (≧ω≦)⊃━☆"

        await ctx.send(msg)

    @commands.hybrid_command(usage="<kiss_target> <intensity>")
    async def kiss(self, ctx, *, input: str):
        """Kisses a user with optional intensity!
        Example: .kiss username 4

        Up to 10 intensity levels."""
        user, intensity = self.get_user_and_intensity(ctx.guild, input)
        if user is None:
            await ctx.send(warning(f"I can't see {input}!"))
            return

        author = italics(ctx.author.display_name)
        name = italics(user.display_name)
        msg = ""

        if intensity <= 0:
            # Just a token kiss
            msg = f"💋 {name}"
        elif intensity <= 3:
            # Gentle peck
            msg = f"{author} gives {name} a gentle peck! 😘"
        elif intensity <= 6:
            # Sweet kiss
            msg = f"{author} blows a sweet kiss to {name}! 😚"
        elif intensity <= 9:
            # Kiss fest
            msg = f"{author} peppers {name} with kisses! 😙💋"
        else:
            # All-out kiss barrage
            msg = f"{author} unleashes a full-on kiss barrage at {name}!!! 💋💋💋"

        await ctx.send(msg)

    @commands.hybrid_command(usage="<winghug_target> <intensity>")
    async def winghug(self, ctx, *, input: str):
        """Gives a winghug with optional intensity!
        Example: .winghug username 4

        Up to 10 intensity levels."""
        user, intensity = self.get_user_and_intensity(ctx.guild, input)
        if user is None:
            await ctx.send(warning(f"I can't see {input}!"))
            return

        author = italics(ctx.author.display_name)
        name = italics(user.display_name)
        msg = ""

        if intensity <= 0:
            # A light wing gesture
            msg = f"{author} flutters their wings near {name}... 🪽"
        elif intensity <= 3:
            # Gentle winghug
            msg = f"{name} is gently dragged and wrapped in {author}'s wings. 🪽🤍"
        elif intensity <= 6:
            # Cozy winghug
            msg = f"{author} wraps {name} in a warm, cozy winghug! 🪽✨"
        elif intensity <= 9:
            # Embracing winghug
            msg = f"{author} envelops {name} completely in a protective winghug! 🪽🛡️"
        else:
            # Majestic full‑power winghug
            msg = (
                f"{author} unfurls their majestic wings and sweeps {name} into a glorious, "
                "all-encompassing winghug!!! 🪽🌟"
            )

        await ctx.send(msg)

    @commands.hybrid_command(usage="<steal_target> <intensity>")
    async def steal(self, ctx, *, input: str):
        """“Steals” a user with optional intensity!
        Example: .steal username 4

        Up to 10 intensity levels."""
        user, intensity = self.get_user_and_intensity(ctx.guild, input)
        if user is None:
            await ctx.send(warning(f"I can't find {input}!"))
            return

        name = italics(user.display_name)
        author = italics(ctx.author.display_name)

        # Base ASCII art template with placeholder for the target’s name in the brackets
        base = [
            "wot",
            f"[ {name} ]",
            "                /\\   /\\",
            "               (' w ')",
        ]

        # Suffix line depends on intensity
        if intensity <= 0:
            # Just a curious glance
            suffix = "    Huh? What’s this…?"
        elif intensity <= 3:
            # Light steal
            suffix = "    Dis is mine now~"
        elif intensity <= 6:
            # More possessive
            suffix = "    Hands off—moi treasure!"
        elif intensity <= 9:
            # Aggressive snatch
            suffix = "    ALL MINE!!! Muahaha!"
        else:
            # Full-on raid
            suffix = "    BOW DOWN! EVERYTHING IS MINE!!!"

        # Combine and send
        art = "\n".join(base + [suffix])
        await ctx.send(art)

    @commands.hybrid_command(usage="<drag_target> <intensity>")
    async def drag(self, ctx, *, input: str):
        """Drags a user with optional intensity!
        Example: .drag username 4

        Up to 10 intensity levels."""
        user, intensity = self.get_user_and_intensity(ctx.guild, input)
        if user is None:
            await ctx.send(warning(f"I can't see {input}!"))
            return

        name = italics(user.display_name)
        msg = ""

        if intensity <= 0:
            # Almost no drag
            msg = f"*barely nudges {name} over...*"
        elif intensity <= 3:
            # Gentle drag
            msg = f"**Drags** {name} **over here**"
        elif intensity <= 6:
            # Medium drag
            msg = f"**Yanks** {name} **closer**"
        elif intensity <= 9:
            # Strong drag
            msg = f"**Hauls** {name} **towards me**"
        else:
            # Maximum drag
            msg = f"**PILES** {name} **into place with unstoppable force!**"

        await ctx.send(msg)

    @commands.command()
    @commands.guild_only()
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

    @commands.hybrid_command()
    async def slap(self, ctx, *, user: Optional[discord.Member] = None):
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

    @commands.group(name="slapset")
    @checks.admin()
    async def slapset(self, ctx):
        """
        Manage slaps
        """
        pass

    @slapset.command(name="add")
    async def slapset_add(self, ctx, *, slap_item):
        """Adds an item to use for slaps!"""
        guild = ctx.guild
        slap_items = await self.config.guild(guild).slap_items()
        if slap_item not in slap_items:
            async with self.config.guild(guild).slap_items() as current_slaps:
                current_slaps.append(slap_item)
            await ctx.send("Item '{}' added to the server's slap items list.".format(slap_item))
        else:
            await ctx.send("Item '{}' is already in the server's slap item list.".format(slap_item))

    @slapset.command(name="remove")
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

    @slapset.command(name="list")
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

    @commands.command()
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

    @commands.group(name="iqset")
    @checks.admin()
    async def iqset(self, ctx):
        """
        Manage iq messages
        """
        pass

    @iqset.command(name="list")
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

    @iqset.command(name="addhigh")
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

    @iqset.command(name="addlow")
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

    @iqset.command(name="removehigh")
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

    @iqset.command(name="removelow")
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

    @commands.hybrid_command()
    @commands.cooldown(1, 6, commands.BucketType.guild)
    async def army(self, ctx, horses: int):
        """
        Summon an army of Aurelias. Max 50
        """
        army_emoji = "<a:trottingaurelia:568577886164877312>"
        if horses > 50:
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
            if len(msg) + len(army_emoji) + 50 > 2000:
                await ctx.send(msg)
                msg = ""

        if msg != "":
            await ctx.send(msg)

    @commands.hybrid_command(usage="<boop_target> <intensity>")
    @commands.guild_only()
    async def boop(self, ctx, *, input: str):
        """
        Boops a user. 10 intensity levels.
        """
        user, intensity = self.get_user_and_intensity(ctx.guild, input)
        if user is None:
            await ctx.send(warning(f"I can't see {input}!"))
            return

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

    @commands.hybrid_command()
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

    @commands.hybrid_command()
    async def flip(self, ctx, *, user: Optional[discord.Member] = None):
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
