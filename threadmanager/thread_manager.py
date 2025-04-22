import discord

from typing import Literal
from redbot.core import Config, checks, commands
from redbot.core.utils.chat_formatting import *
from redbot.core.utils.menus import menu, DEFAULT_CONTROLS


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

    @threadset.command(name="list")
    async def threadset_list(self, ctx):
        """
        List all channels and their thread roles
        """
        channel_data = await self.config.all_channels()

        msg = ""
        for id, data in channel_data.items():
            channel = ctx.guild.get_channel(id)
            if not channel:
                continue

            msg += f"#{channel.name}\n"
            for role_id, num_threads in data["allowed_roles"].items():
                role = ctx.guild.get_role(int(role_id))
                if not role:
                    continue
                msg += f"\t- @{role.name}: {num_threads}\n"
            msg += "\n"

        pages = list(pagify(msg, page_length=1700, delims=["\n"], priority=True))
        pages = [box(f"{page}\n\n-----------------\nPage {i+1} of {len(pages)}") for i, page in enumerate(pages)]

        if not pages:
            await ctx.send("No channels setup to use thread manager.", delete_after=30)
        else:
            await menu(ctx, pages, DEFAULT_CONTROLS)

    @threadset.command(name="archive")
    async def threadset_archive(self, ctx, archive: Literal[60, 1440, 4320, 10080]):
        """
        Set the archive duration of user created threads

        Must be one of: 60, 1440, 4320, and 10080
        If your guild doesn't have longer thread archival features, the archive value is clipped to the highest value available.
        """
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

    @commands.hybrid_command()
    @commands.guild_only()
    async def thread(self, ctx: commands.Context, *, name: str):
        """
        Create a new thread from this channel

        You must have proper permissions set
        """
        channel = ctx.channel
        guild = ctx.guild
        user = ctx.author

        if not isinstance(channel, discord.TextChannel):
            await ctx.reply(info("Sorry, this command only works in regular text channels."))
            return

        allowed_roles = await self.config.channel(channel).allowed_roles()
        roles = {int(r) for r in allowed_roles.keys()}
        u_roles = {r.id for r in user.roles}

        if not (roles & u_roles):
            return await ctx.send(
                "Sorry, you do not have a role that allows you to create threads here.", delete_after=15
            )

        possible_roles = roles & u_roles
        num_threads = sorted([allowed_roles[str(r)] for r in possible_roles])[-1]

        async with self.config.channel(channel).threads() as channel_threads:
            if str(user.id) not in channel_threads:
                channel_threads[str(user.id)] = []

            user_threads = set(
                [
                    channel.get_thread(tid)
                    for tid in channel_threads[str(user.id)]
                    if channel.get_thread(tid) is not None
                ]
            )

            user_threads = [t for t in user_threads if not t.archived or t.locked]

            if len(user_threads) >= num_threads:
                return await ctx.send(
                    f"You have reached the maximum number ({num_threads}) of threads you can create for this channel. Please have a staff member archive one of your threads.",
                    delete_after=15,
                )

            # now we can create a thread
            archive = await self.config.guild(guild).archive()
            try:
                thread = await channel.create_thread(
                    name=name, message=ctx.message, auto_archive_duration=archive, reason="Thread cog"
                )
                await thread.add_user(ctx.guild.me)
                channel_threads[str(user.id)].append(thread.id)
            except:
                return await ctx.send(
                    "Something went wrong, most likely a permissions issue. Please contact a staff member.",
                    delete_after=30,
                )
