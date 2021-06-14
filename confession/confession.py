from redbot.core import commands, checks, Config
from redbot.core.utils.predicates import MessagePredicate
from redbot.core.utils.menus import DEFAULT_CONTROLS, menu
from typing import Literal
import contextlib
import discord
import asyncio


class Confession(commands.Cog):
    def __init__(self):
        self.config = Config.get_conf(self, identifier=665235, force_registration=True)
        default_guild = {"confession_room": None, "tracker_room": None}
        self.config.register_guild(**default_guild)

    @commands.group()
    @checks.admin_or_permissions(manage_guild=True)
    @commands.guild_only()
    async def confessionset(self, ctx):
        """Manage confession rooms"""
        pass

    @confessionset.command(name="confess")
    async def confessionset_confess(self, ctx, *, channel: discord.TextChannel = None):
        """Set a confession room
        Leave empty to unset the room.

        **Make sure bot is able to embed messages in confession room.**
        """

        room = await self.config.guild(ctx.guild).confession_room()
        room = ctx.guild.get_channel(room)

        if not channel:
            if room:
                await ctx.send(f"Unset confession channel {room.mention} ?")
                pred = MessagePredicate.yes_or_no(ctx)
                await ctx.bot.wait_for("message", check=pred)
                if pred.result:
                    await self.config.guild(ctx.guild).confession_room.clear()
                    await ctx.tick()
                else:
                    await ctx.send("Cancelled.")
                return
            else:
                await ctx.send("No confession room defined.")
                return

        await self.config.guild(ctx.guild).confession_room.set(channel.id)
        await ctx.tick()

    @confessionset.command(name="track")
    async def confessionset_track(self, ctx, *, channel: discord.TextChannel = None):
        """Set a tracker room
        Leave empty to unset the room.

        Tracker room has confessions sent along with who sent them,
        for easy moderation purposes. This is optional to set.

        **Make sure bot is able to embed messages in tracker room.**
        """

        room = await self.config.guild(ctx.guild).tracker_room()
        room = ctx.guild.get_channel(room)

        if not channel:
            if room:
                await ctx.send(f"Unset tracker channel {room.mention} ?")
                pred = MessagePredicate.yes_or_no(ctx)
                await ctx.bot.wait_for("message", check=pred)
                if pred.result:
                    await self.config.guild(ctx.guild).tracker_room.clear()
                    await ctx.tick()
                else:
                    await ctx.send("Cancelled.")
                return
            else:
                await ctx.send("No tracker room defined.")
                return

        await self.config.guild(ctx.guild).tracker_room.set(channel.id)
        await ctx.tick()

    @commands.command()
    @commands.cooldown(rate=1, per=180, type=commands.BucketType.user)
    async def confess(self, ctx, *, confession: str):
        """Confess your dirty sins
        Make sure to use in DMs
        It'll ask you which guild to confess in if you have more than one with a confession
        """

        async def select_guild(
            ctx: commands.Context,
            pages: list,
            controls: dict,
            message: discord.Message,
            page: int,
            timeout: float,
            emoji: str,
        ):
            # Clean up
            with contextlib.suppress(discord.NotFound):
                await message.delete()
            # Send it off to this function so it sends to initiate search after selecting subdomain
            await self.selected_guild(ctx, user_guilds, confession, page)
            return None

        if bool(ctx.guild):
            msg = await ctx.send("You should do this in DMs!")
            try:
                await ctx.message.delete()
                await asyncio.sleep(10)
                await msg.delete()
            except:
                pass
            return

        all_guilds = ctx.bot.guilds
        user_guilds = []
        for guild in all_guilds:
            if guild.get_member(ctx.message.author.id):
                room = await self.config.guild(guild).confession_room()
                if room is not None:
                    user_guilds.append(guild)

        if len(user_guilds) == 0:
            await ctx.author.send("No server with a confession room, ask your server owners to set it up!")
        if len(user_guilds) == 1:
            await self.send_confession(ctx, user_guilds[0], confession)
        else:
            SELECT_DOMAIN = {"\N{WHITE HEAVY CHECK MARK}": select_guild}

            # Create dict for controls used by menu
            SELECT_CONTROLS = {}
            SELECT_CONTROLS.update(DEFAULT_CONTROLS)
            SELECT_CONTROLS.update(SELECT_DOMAIN)

            embeds = []
            for guild in user_guilds:
                embed = discord.Embed()
                embed.title = "Where do you want to confess?"
                embed.description = guild.name
                embeds.append(embed)

            await menu(ctx, pages=embeds, controls=SELECT_CONTROLS, message=None, page=0, timeout=20)

    async def selected_guild(self, ctx, user_guilds, confession, page):

        confession_guild = user_guilds[page]
        await self.send_confession(ctx, confession_guild, confession)

    async def send_confession(self, ctx, confession_guild: discord.Guild, confession: str):

        confession_room = await self.config.guild(confession_guild).confession_room()
        confession_room = confession_guild.get_channel(confession_room)

        if not confession_room:
            await ctx.author.send("The confession room does not appear to exist.")
            return

        try:
            embed = discord.Embed(title="I have forgiven another sin", colour=ctx.author.colour)
            embed.set_footer(text="You can always confess to me.")
            embed.add_field(name="Confession", value=confession)

            await ctx.bot.send_filtered(destination=confession_room, embed=embed)
        except discord.errors.Forbidden:
            await ctx.author.send(
                "I don't have permission to send messages to this room, embed messages or something went wrong."
            )
            return

        tracker_room = await self.config.guild(confession_guild).tracker_room()
        tracker_room = confession_guild.get_channel(tracker_room)
        if tracker_room:
            embed = discord.Embed(title="New Confession", colour=ctx.author.colour)
            embed.add_field(name="Confession", value=confession)
            avatar = ctx.author.avatar_url_as(static_format="png")
            embed.set_author(name=ctx.author, url=avatar)
            embed.set_thumbnail(url=avatar)
            embed.set_footer(text=f"User ID: {ctx.author.id}")
            try:
                await ctx.bot.send_filtered(destination=tracker_room, embed=embed)
            except:
                pass

        await ctx.author.send("Your confession has been sent, you are forgiven now.")

    async def red_delete_data_for_user(
        self,
        *,
        requester: Literal["discord_deleted_user", "owner", "user", "user_strict"],
        user_id: int,
    ):
        pass
