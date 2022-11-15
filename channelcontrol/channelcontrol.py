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

        default_guild = {"locked": False}
        default_channel = {"pos": -1}
        self.config.register_channel(**default_channel)
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

        # update channel positions for new channels
        for guild in self.bot.guilds:
            locked = await self.config.guild(guild).locked()
            all_channels = guild.text_channels + guild.voice_channels
            for channel in all_channels:
                curr = await self.config.channel(channel).pos()
                if curr == -1:
                    await self.config.channel(channel).pos.set(channel.position)
                elif curr != channel.position and locked:
                    # channel moved while bot was down, need to fix
                    try:
                        await channel.edit(position=curr)
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

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel: Union[discord.TextChannel, discord.VoiceChannel]):
        await self.config.channel(channel).pos.set(channel.position)

    @commands.Cog.listener()
    async def on_guild_channel_update(
        self,
        before: Union[discord.TextChannel, discord.VoiceChannel],
        after: Union[discord.TextChannel, discord.VoiceChannel],
    ):
        if before.position != after.position:
            locked = await self.config.guild(before.guild).locked()
            if locked:
                pos = await self.config.channel(after).pos()
                if pos != -1:  # this shouldnt happen, but its possible
                    try:
                        await after.edit(position=pos)
                    except:
                        pass
            else:
                await self.config.channel(after).pos.set(after.position)
