from redbot.core.utils.chat_formatting import *
from redbot.core import Config, checks, commands, bank
from redbot.core.data_manager import cog_data_path
import discord

import os
import glob
import asyncio
from difflib import get_close_matches
import tabulate

from .utils import saysound, code_path

EXT = ("mp3", "flac", "ogg", "wav")


class SFX(commands.Cog):
    """Play saysounds in VC's in your guild
    Supports costs, files, and links.
    """

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=8495126065166516132, force_registration=True)

        # saysounds maps saysound name (str) -> saysound data (dict)
        default_guild = {"saysounds": {}, "FREE_ROLES": []}
        default_global = {"attachments": True}

        self.config.register_guild(**default_guild)
        self.config.register_global(**default_global)

        global PATH
        global AUDIO_CODE_PATH
        PATH = str(cog_data_path(cog_instance=self))
        audio_cog = bot.get_cog("Audio")
        if audio_cog:
            AUDIO_CODE_PATH = str(code_path(cog_instance=audio_cog))
        else:
            AUDIO_CODE_PATH = None

    # integrates cost manager free roles!
    # if cost_manager isn't loaded, use this cog's free roles
    async def get_cost(self, member: discord.Member, sound: dict):
        cost = sound["cost"]
        cost_manager = self.bot.get_cog("CostManager")

        if cost_manager:
            free_roles = await cost_manager.config.guild(member.guild).FREE_ROLES()
        else:
            free_roles = await self.config.guild(member.guild).FREE_ROLES()

        member_roles = {r.id for r in member.roles if r.name != "@everyone"}
        found_roles = set(free_roles) & member_roles
        if found_roles:
            cost = 0

        return cost

    # plays sound in vc of author
    async def play(self, ctx, sound: dict):
        audio_cog = self.bot.get_cog("Audio")
        if not audio_cog:
            await ctx.send(error("Unable to load audio cog, please contact bot owner!"))
            return

        try:
            query = sound["url"] if sound["url"] else sound["filepath"]
            await audio_cog.sfx_play(ctx, query, volume=sound["volume"])
        except Exception as e:
            await ctx.send(error("Unable to play sound, please contact bot owner!"))
            print(e)  # TODO add logging properly

    @commands.group()
    @checks.admin_or_permissions(administrator=True)
    async def sfxset(self, ctx):
        """
        Manage settings for saysounds
        """
        pass

    @sfxset.command(name="vol")
    @commands.guild_only()
    async def sfxset_vol(self, ctx, vol: int, *, name: str):
        """
        Change volume of sfx sound
        """
        async with self.config.guild(ctx.guild).saysounds() as saysounds:
            try:
                saysounds[name]["volume"] = vol
            except:
                await ctx.send(error("Sound not found, try again!"))
                return

        await ctx.tick()

    @sfxset.command(name="cost")
    @commands.guild_only()
    async def sfxset_cost(self, ctx, cost: int, *, name: str):
        """
        Change cost of sfx sound
        """
        async with self.config.guild(ctx.guild).saysounds() as saysounds:
            try:
                saysounds[name]["cost"] = cost
            except:
                await ctx.send(error("Sound not found, try again!"))
                return

        await ctx.tick()

    @sfxset.command(name="name")
    @commands.guild_only()
    async def sfxset_name(self, ctx, old_name: str, *, new_name: str):
        """
        Change name of sfx sound

        **OLD_NAME MUST be in quotes if it has spaces!**
        """
        async with self.config.guild(ctx.guild).saysounds() as saysounds:
            try:
                temp = saysounds[old_name]
                saysounds[new_name] = temp
                saysounds[new_name]["name"] = new_name
                del saysounds[old_name]
            except:
                await ctx.send(error("Sound not found, try again!"))
                return

        await ctx.tick()

    @sfxset.command(name="add")
    @commands.guild_only()
    async def sfxset_add(self, ctx, cost: int, vol: int, *, name: str):
        """
        Add an sfx sound for the guild.

        Attach the audio file to the message.
        """
        can_use = await self.config.attachments()
        name = name.lower()

        if not can_use:
            await ctx.send(error("Sorry, I only allow adding say sounds using URLs."))
            return

        if len(ctx.message.attachments) < 1:
            await ctx.send(error("Please provide an attachment."))
            return

        sounds = await self.config.guild(ctx.guild).saysounds()
        try:
            x = sounds[name]
            await ctx.send(error("Sound already exists by that name, please delete it first!"))
            return
        except:
            pass

        file = ctx.message.attachments[0]
        ext = file.filename.split(".")[-1]

        if ext not in EXT:
            await ctx.send(error("Audio file must one of `mp3, wav, flac, or ogg` formats."))
            return

        save_path = os.path.join(PATH, str(ctx.guild.id))
        if not os.path.exists(save_path):
            os.makedirs(save_path)

        save_path = os.path.join(save_path, file.filename)

        try:
            await file.save(save_path)
        except:
            await ctx.send(error("Error saving file, please try again."))
            return

        author = f"{ctx.author} id: {ctx.author.id}"
        new_sound = saysound(name, author, cost=cost, volume=vol, filepath=save_path)
        sounds[name] = new_sound

        await self.config.guild(ctx.guild).saysounds.set(sounds)

        await ctx.tick()

    @sfxset.command(name="addurl")
    @commands.guild_only()
    async def sfxset_addurl(self, ctx, cost: int, vol: int, url: str, *, name: str):
        """
        Add an sfx sound for the guild.

        URL must be a direct link to the audio file, a youtube link, spotify link,
        soundcloud link etc.
        You can test if it will work using the `play` command on the bot.
        """
        name = name.lower()
        async with self.config.guild(ctx.guild).saysounds() as saysounds:
            try:
                x = saysounds[name]
                await ctx.send(error("Sound already exists by that name, please delete it first!"))
                return
            except:
                pass
            author = f"{ctx.author} id: {ctx.author.id}"
            new_sound = saysound(name, author, cost=cost, volume=vol, url=url)
            saysounds[name] = new_sound

        await ctx.tick()

    @sfxset.command(name="del")
    @commands.guild_only()
    async def sfxset_del(self, ctx, *, name: str):
        """
        Delete an sfx sound for the guild.
        """
        name = name.lower()
        async with self.config.guild(ctx.guild).saysounds() as saysounds:
            try:
                del saysounds[name]
                await ctx.tick()
            except KeyError:
                await ctx.send(error("That say sound does not exist!"))

    @sfxset.command(name="file")
    @checks.is_owner()
    async def sfxset_file(self, ctx, *, on_off: bool = None):
        """
        Enable or disable allowing to save audio files directly for playback
        """
        curr = await self.config.attachments()
        if on_off is None:
            msg = "on" if curr else "off"
            await ctx.send(f"Allowing saving of audio files is currently {msg}.")
            return

        await self.config.attachments.set(on_off)
        await ctx.tick()

    @sfxset.command(name="setup")
    @checks.is_owner()
    async def sfxset_setup(self, ctx):
        """
        Run this first to inject code into audio cog for proper sfx usage.

        After injection, reload audio cog and run this again to confirm injection
        was successful.
        """
        audio_cog = self.bot.get_cog("Audio")

        if not audio_cog:
            await ctx.send(error("Audio cog not loaded, load it first before running this."))
            return

        try:
            if callable(audio_cog.sfx_play):
                await ctx.send("Injection successful, SFX is ready to use!")
            else:
                await ctx.send("Function found but not callable, unknown error.")
            return
        except:
            pass

        if not AUDIO_CODE_PATH:
            await ctx.send(error("Please reload the cog after the Audio cog has been loaded!"))
            return

        inject_path = str(code_path(cog_instance=self) / "injection.txt")
        with open(inject_path, "r") as f:
            injection = f.read()

        inject_path = os.path.join(AUDIO_CODE_PATH, "utilities", "player.py")
        with open(inject_path, "a") as f:
            f.write(injection)

        await ctx.send("Injection complete, reload audio cog then run this command again to make sure it worked.")

    @commands.command(name="sfx")
    @commands.guild_only()
    @commands.cooldown(rate=1, per=10, type=commands.BucketType.user)
    async def sfx(self, ctx, *, name: str):
        """
        Play a say sound!
        """
        # TODO: cost manager receipt integration
        if not ctx.author.voice or ctx.author.voice.channel is None:
            await ctx.send(error("Connect to a voice channel to use this command."))
            return

        # TODO: create my own queue to fix this issue
        if ctx.guild.me.voice and ctx.guild.me.voice.channel != ctx.author.voice.channel:
            await ctx.send(error("Please wait for the bot to disconnect from it's VC before using the command."))
            return

        name = name.lower()
        saysounds = await self.config.guild(ctx.guild).saysounds()
        audio_cog = self.bot.get_cog("Audio")
        play = self.bot.get_command("play")
        volume = self.bot.get_command("volume")
        if not play:
            await ctx.send(error("Audio cog not loaded! Please contact bot owner."))
            return

        try:
            sound = saysounds[name]
        except KeyError:
            # name doesn't have to be full name, will find closest match
            matches = get_close_matches(name, list(saysounds.keys()), n=1, cutoff=0.7)
            if matches:
                sound = saysounds[matches[0]]
            else:
                await ctx.send(error("Say sound could not be found!"))
                return

        # found saysound

        # charge user
        cost = await self.get_cost(ctx.author, sound)
        msg = None
        if cost > 0:
            currency_name = await bank.get_currency_name(ctx.guild)
            try:
                await bank.withdraw_credits(ctx.author, cost)
                balance = await bank.get_balance(ctx.author)
                msg = await ctx.send(f"Charged: {cost}, Balance: {balance}")
            except ValueError:
                balance = await bank.get_balance(ctx.author)
                msg = await ctx.send(
                    error(
                        f"Sorry {ctx.author.name}, you do not have enough {currency_name} to use that say sound. (Cost: {cost}, Balance: {balance})"
                    )
                )
                await asyncio.sleep(10)
                await msg.delete()
                return

        await self.play(ctx, sound)

        if msg:
            await asyncio.sleep(5)
            await msg.delete()

    @commands.command(name="sfxlist")
    async def sfx_list(self, ctx):
        """
        List all say sounds for guild.
        """

        saysounds = await self.config.guild(ctx.guild).saysounds()
        msg = []

        keys = sorted(list(saysounds.keys()))

        for sound_name in keys:
            msg.append((sound_name, saysounds[sound_name]["cost"]))

        msg = tabulate.tabulate(msg, ["Sound", "Cost"], tablefmt="github")

        pages = pagify(msg)

        for page in pages:
            try:
                await ctx.author.send(box(page))
            except:
                await ctx.send("Please allow DMs from server members so I can DM you the list!")
                return
