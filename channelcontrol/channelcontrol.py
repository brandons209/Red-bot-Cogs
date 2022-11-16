import asyncio
import discord

from redbot.core import Config, checks, commands, modlog
from redbot.core.utils.chat_formatting import *

from typing import Union
from datetime import datetime


class ChannelControl(commands.Cog):
    """
    Functions for managing channels in a guild
    """

    def __init__(self, bot):
        self.bot = bot

        self.config = Config.get_conf(self, identifier=4896413516576857, force_registration=True)

        default_guild = {"locked": False, "text_channels": {}, "voice_channels": {}}
        self.config.register_guild(**default_guild)

        self.task = asyncio.create_task(self.init())

    def cog_unload(self):
        if self.task is not None:
            self.task.cancel()
        return super().cog_unload()

    async def init(self):
        await self.bot.wait_until_ready()
        # register mod case
        lock_case = {
            "name": "Channel Position Locked",
            "default_setting": True,
            "image": "↕",
            "case_str": "Channel Position Locked",
        }
        unlock_case = {
            "name": "Channel Position Unlocked",
            "default_setting": True,
            "image": "↕",
            "case_str": "Channel Position Unlocked",
        }

        try:
            await modlog.register_casetypes([lock_case, unlock_case])
        except RuntimeError:
            pass

        # update channel positions if channels are locked:
        while True:
            for guild in self.bot.guilds:
                locked = await self.config.guild(guild).locked()
                if not locked:
                    continue
                await self.set_channel_positions(guild)

                await asyncio.sleep(1)

            await asyncio.sleep(120)

    def get_channel_positions(self, guild: discord.Guild):
        text_channels = {}
        voice_channels = {}

        for cat in guild.categories:
            text_channels[str(cat.id)] = {}
            voice_channels[str(cat.id)] = {}
            for channel in cat.text_channels:
                text_channels[str(cat.id)][str(channel.id)] = channel.position
            for channel in cat.voice_channels:
                voice_channels[str(cat.id)][str(channel.id)] = channel.position

        # make sure they are sorted
        for cat in guild.categories:
            text_channels[str(cat.id)] = {
                k: v for k, v in sorted(text_channels[str(cat.id)].items(), key=lambda i: i[1])
            }
            voice_channels[str(cat.id)] = {
                k: v for k, v in sorted(voice_channels[str(cat.id)].items(), key=lambda i: i[1])
            }

        return text_channels, voice_channels

    async def set_channel_positions(self, guild: discord.Guild):
        # these are in sorted order
        text_channels = await self.config.guild(guild).text_channels()
        voice_channels = await self.config.guild(guild).voice_channels()

        for cat_id in text_channels.keys():
            cat = guild.get_channel(int(cat_id))
            if not cat:
                continue
            for ch_id, pos in text_channels[cat_id].items():
                channel = guild.get_channel(int(ch_id))
                if not channel:
                    continue

                # first check if channel is in right category
                if channel.category_id != int(cat_id):
                    try:
                        await channel.edit(category=cat, position=pos)
                    except:
                        pass
                elif channel.position != pos:
                    try:
                        await channel.edit(position=pos)
                    except:
                        pass

            for ch_id, pos in voice_channels[cat_id].items():
                channel = guild.get_channel(int(ch_id))
                if not channel:
                    continue

                # first check if channel is in right category
                if channel.category_id != int(cat_id):
                    try:
                        await channel.edit(category=cat, position=pos)
                    except:
                        pass
                elif channel.position != pos:
                    try:
                        await channel.edit(position=pos)
                    except:
                        pass

    async def create_case(
        self,
        channel: Union[discord.TextChannel, discord.VoiceChannel],
        type: str,
        reason: str,
        user: discord.Member,
        moderator: discord.Member = None,
    ):
        try:
            case = await modlog.create_case(
                self.bot,
                channel.guild,
                datetime.now(),
                type,
                user,
                moderator=moderator if moderator is not None else user,
                reason=reason,
            )
        except:
            case = None

        return case

    @commands.group(name="chpos")
    @commands.guild_only()
    @checks.admin()
    @checks.bot_has_permissions(manage_channels=True)
    async def channel_control(self, ctx):
        """
        Manage channel control settings
        """
        pass

    @channel_control.command(name="lock")
    async def channel_control_lock(self, ctx, toggle: bool):
        """
        Lock or unlock channel positions to their current positions
        """
        locked = await self.config.guild(ctx.guild).locked()
        if toggle and not locked:
            await ctx.send(info("Channels are now locked to their current positions."), delete_after=30)
            await self.create_case(
                ctx.channel,
                type="Channel Position Locked",
                reason=f"Channel positions locked.",
                user=ctx.author,
                moderator=ctx.author,
            )
            await self.config.guild(ctx.guild).locked.set(toggle)
            text_channels, voice_channels = self.get_channel_positions(ctx.guild)

            await self.config.guild(ctx.guild).text_channels.set(text_channels)
            await self.config.guild(ctx.guild).voice_channels.set(voice_channels)
        elif not toggle and locked:
            await ctx.send(info("Channels are unlocked and can be moved."), delete_after=30)
            await self.create_case(
                ctx.channel,
                type="Channel Position Unlocked",
                reason=f"Channel positions unlocked.",
                user=ctx.author,
                moderator=ctx.author,
            )
            await self.config.guild(ctx.guild).locked.set(toggle)
        elif toggle and locked:
            await ctx.send(info("Channel positions are already locked!"), delete_after=30)
        else:
            await ctx.send(info("Channel positions are already unlocked!"), delete_after=30)
