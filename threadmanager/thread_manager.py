import asyncio
import discord

from typing import Optional, Literal
from redbot.core import Config, checks, commands

from .discord_thread_feature import create_thread, add_user_thread, get_active_threads


class ThreadManager(commands.Cog):
    """
    Better Thread Manager
    """

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=165164165133023130, force_registration=True)

        # allowed roles maps role id (str) -> number of threads each user can create with this role (int)
        # threads maps member id str -> list of active thread ids (int) that the user created in the channel
        default_channel = {"allowed_roles": {}, "threads": {}}
        default_guild = {"archive": 60}
        self.config.register_channel(**default_channel)
        self.config.register_guild(**default_guild)

    @commands.group()
    @commands.guild_only()
    @checks.admin_or_permissions(administrator=True)
    async def threadset(self, ctx):
        """
        Manage threads
        """
        pass

    @threadset.command(name="archive")
    async def threadset_archive(self, ctx, archive: int):
        """
        Set the archive duration of user created threads

        Must be one of: 60, 1440, 4320, and 10080
        If your guild doesn't have longer thread archival features, the archive value is clipped to the highest value available.
        """
        if archive not in [60, 1440, 4320, 10080]:
            return await ctx.send("Invalid archive time, try again.", delete_after=30)

        await self.config.guild(ctx.guild).archive.set(archive)
        await ctx.tick()

    @threadset.command(name="add")
    async def threadset_add(self, ctx, channel: discord.TextChannel, num_threads: int, *, role: discord.Role):
        """
        Set the number for threads anyone with role can create for channel

        If a user has multiple roles, whatever role has the highest value is used
        """
        async with self.config.channel(channel).allowed_roles() as allowed_roles:
            allowed_roles[str(role.id)] = num_threads
        await ctx.tick()

    @threadset.command(name="del")
    async def threadset_del(self, ctx, channel: discord.TextChannel, *, role: discord.Role):
        """
        Delete a role from a channel

        Does not cleanup threads currently active
        """
        async with self.config.channel(channel).allowed_roles() as allowed_roles:
            if str(role.id) in allowed_roles:
                del allowed_roles[str(role.id)]

        await ctx.tick()

    @commands.command()
    @commands.guild_only()
    async def thread(self, ctx, *, name: str):
        """
        Create a new thread from this channel

        You must have proper permissions set
        """
        channel = ctx.channel
        guild = ctx.guild
        user = ctx.author

        allowed_roles = await self.config.channel(channel).allowed_roles()
        roles = {int(r) for r in allowed_roles.keys()}
        u_roles = {r.id for r in user.roles}

        if not (roles & u_roles):
            return await ctx.send(
                "Sorry, you do not have a role that allows you to create threads here.", delete_after=15
            )

        possible_roles = roles & u_roles
        num_threads = sorted([allowed_roles[str(r)] for r in possible_roles])[-1]

        threads = await self.config.channel(channel).threads()
        if str(user.id) not in threads:
            threads[str(user.id)] = []

        user_threads = threads[str(user.id)]
        if len(user_threads) >= num_threads:
            # first, need to update active threads for this channel
            activate_threads = set(await get_active_threads(self.bot, guild))
            still_active = set(user_threads) & activate_threads

            # remove not active threads
            user_threads = [t for t in user_threads if t in still_active]
            # update config
            threads[str(user.id)] = user_threads
            await self.config.channel(channel).threads.set(threads)

        if len(user_threads) >= num_threads:
            return await ctx.send(
                f"You have reached the maximum number ({num_threads}) of threads you can create for this channel. Please have a staff member archive one of your threads.",
                delete_after=15,
            )

        # now we can create a thread
        archive = await self.config.guild(guild).archive()
        try:
            thread = await create_thread(self.bot, channel, ctx.message, name=name, archive=archive)
            await add_user_thread(self.bot, thread, user)
        except:
            return await ctx.send(
                "Something went wrong, most likely a permissions issue. Please contact a staff member.", delete_after=30
            )

        threads[str(user.id)].append(thread)
        await self.config.channel(channel).threads.set(threads)
