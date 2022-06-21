import asyncio
import discord
import datetime
from tabulate import tabulate

from typing import Optional, Literal, Union
from redbot.core import Config, checks, commands
from redbot.core.utils.chat_formatting import *
from redbot.core.utils.menus import menu, DEFAULT_CONTROLS


class WatchlistUser:
    """
    Maintains watchlist user data and provides functions for modification
    """

    def __init__(
        self,
        bot,
        user_id: int,
        watchlist_number: int,
        reason: str,
        added_by: int,
        message: discord.Message = None,
        amended_by: int = None,
        amended_time: int = None,
    ):
        """
        Create a new user on a watchlist

        Args:
            bot (Red): Bot instance
            user_id (int): ID of the user on the watchlist
            watchlist_number (int): The watchlist number this user represents
            reason (str): Reason for being on the watchlist
            added_by (int): Moderator/Administrator that added this user to the watchlist
            message (discord.Message, optional): Message object on the watchlist. Defaults to None.
            amended_by (int, optional): User ID of user who edited this watchlist user. Defaults to None.
            amended_time (int, optional): When changes were last made to this watchlist user. Defaults to None.
        """
        self.user_id = user_id
        self.message = message
        self.watchlist_number = watchlist_number
        self.reason = reason
        self.added_by = added_by
        self.amended_by = amended_by
        self.amended_time = amended_time

        self.bot = bot

    async def create_embed(self, amended_by: discord.Member = None):
        """
        Create a discord Embed that represents this user on the watchlist

        Args:
            amended_by (discord.Member, optional): User who amended this watchlist user. Defaults to None.

        Returns:
            discord.Embed: The embed representing this user
        """
        user = self.bot.get_user(self.user_id)
        if not user:
            user = await self.bot.fetch_user(self.user_id)

        added_by = self.bot.get_user(self.added_by)
        if not added_by:
            added_by = await self.bot.fetch_user(self.added_by)

        if not user:
            title = f"#{self.watchlist_number} Unknown / not found user ({self.user_id})"
            avatar = None
        else:
            title = f"#{self.watchlist_number} {user} ({user.id})"
            avatar = user.avatar_url_as(static_format="png")

        embed = discord.Embed(color=discord.Color.blue(), title=title, description=self.reason)

        if avatar:
            embed.set_thumbnail(url=avatar)

        embed.add_field(
            name="Added by",
            value=f"{added_by if added_by is not None else 'Unknown / not found user ({self.added_by})'}",
        )

        if amended_by is not None:
            self.amended_by = amended_by.id
            self.amended_time = int(datetime.datetime.now().timestamp())
            embed.add_field(name="Amended by", value=f"{amended_by} at <t:{self.amended_time}:f>")
        else:
            amended_by = self.bot.get_user(self.amended_by)
            if not amended_by and self.amended_by is not None:
                amended_by = await self.bot.fetch_user(self.amended_by)

            if amended_by is not None:
                embed.add_field(name="Amended by", value=f"{amended_by} at <t:{self.amended_time}:f>")

        return embed

    async def send_watchlist_message(self, channel: discord.TextChannel = None):
        """
        Send (or resend) watchlist message

        Args:
            channel (discord.TextChannel, optional): The channel to send the message to

        Raises:
            AttributeError: If there is no channel provided and internal message is not set
        """
        if channel:
            message = await channel.send(embed=(await self.create_embed()))
            self.message = message
        elif self.message is not None:
            channel = self.message.channel
            try:
                await self.message.delete()
            except:
                pass

            message = await channel.send(embed=(await self.create_embed()))
            self.message = message
        else:
            raise AttributeError("Must provide a channel if there is no message for this user on watchlist.")

    async def delete_watchlist_message(self):
        """
        Deletes message on the watchlist

        Returns:
            bool: True if successful, False otherwise
        """
        if self.message is None:
            return False

        try:
            await self.message.delete()
            return True
        except:
            return False

    async def update_reason(self, member: discord.Member, reason: str):
        """
        Update the reason for this user

        Args:
            member (discord.Member): The user that requested this update.
            reason (str): The new reason

        Returns:
            bool: True if successful, False otherwise
        """
        self.reason = reason
        new_embed = await self.create_embed(member)

        try:
            await self.message.edit(embed=new_embed)
            return True
        except:
            return False

    async def update_embed(self):
        """
        Update embeds with new user information

        Returns:
            bool: True if successful, False otherwise
        """
        new_embed = await self.create_embed()

        try:
            await self.message.edit(embed=new_embed)
            return True
        except:
            return False

    def to_dict(self):
        """
        Converts data for this object into dictionary

        Returns:
            dict: The object data as a dictionary
        """
        data = {
            "user_id": self.user_id,
            "added_by": self.added_by,
            "channel_id": self.message.channel.id if self.message else None,
            "message_id": self.message.id if self.message else None,
            "watchlist_number": self.watchlist_number,
            "reason": self.reason,
            "amended_by": self.amended_by,
            "amended_time": self.amended_time,
        }

        return data

    @staticmethod
    async def from_dict(bot, data: dict):
        """
        Create a new WatchlistUser object from data dictionary

        Args:
            bot (Red): Bot instance
            data (dict): Data for watchlist user

        Raises:
            AttributeError: If there is a missing key in the data dictionary

        Returns:
            WatchlistUser: The watchlist user object
        """
        needed_keys = [
            "user_id",
            "added_by",
            "channel_id",
            "message_id",
            "watchlist_number",
            "reason",
            "amended_by",
            "amended_time",
        ]

        for k in needed_keys:
            if k not in data:
                raise AttributeError(f"{k} missing from dictionary!")

        channel = bot.get_channel(data["channel_id"])
        if not channel:
            message = None
        else:
            message = await channel.fetch_message(data["message_id"])

        return WatchlistUser(
            bot,
            data["user_id"],
            data["watchlist_number"],
            data["reason"],
            data["added_by"],
            message=message,
            amended_by=data["amended_by"],
            amended_time=data["amended_time"],
        )


class Watchlist(commands.Cog):
    """
    Watchlist of persons of interest
    """

    def __init__(self, bot):
        self.bot = bot

        self.config = Config.get_conf(self, identifier=8946115618891655613, force_registration=True)

        # watchlist user data will contain list of dictionaries that cna be converted to a watchlistuser class object
        default_guild = {
            "watchlist_users": [],
            "removed_users": [],
            "channel": None,
            "alert_channel": None,
            "watchlist_num": 0,
        }

        self.config.register_guild(**default_guild)

        # store cached watchlist for each guild
        self.watchlist = {}

        self.task = asyncio.create_task(self.init())

    def cog_unload(self):
        if self.task:
            self.task.cancel()

    async def init(self):
        await self.bot.wait_until_ready()

        for guild in self.bot.guilds:
            watch_list = await self.config.guild(guild).watchlist_users()
            self.watchlist[guild.id] = []
            for w in watch_list:
                try:
                    self.watchlist[guild.id].append(await WatchlistUser.from_dict(self.bot, w))
                except AttributeError as e:
                    print(e)

        while True:
            for guild in self.bot.guilds:
                if guild.id not in self.watchlist:
                    self.watchlist[guild.id] = []

                for watchlist_user in self.watchlist[guild.id]:
                    await watchlist_user.update_embed()

            await asyncio.sleep(28800)  # update every 8 hours

    @commands.group(name="watchlist")
    @commands.guild_only()
    @checks.admin_or_permissions(administrator=True)
    async def watchlist(self, ctx):
        """
        Manage guild watchlist
        """
        pass

    @watchlist.command(name="channel")
    async def watchlist_channel(self, ctx, *, channel: discord.TextChannel = None):
        """
        Change the watchlist channel
        """
        if not channel:
            await self.config.guild(ctx.guild).channel.clear()
            await ctx.send(info("Watchlist channel cleared."))
        else:
            await self.config.guild(ctx.guild).channel.set(channel.id)

        await ctx.tick()

    @watchlist.command(name="alert")
    async def watchlist_alert(self, ctx, *, channel: discord.TextChannel = None):
        """
        Change the watchlist alert channel
        """
        if not channel:
            await self.config.guild(ctx.guild).alert_channel.clear()
            await ctx.send(info("Watchlist channel cleared."))
        else:
            await self.config.guild(ctx.guild).alert_channel.set(channel.id)

        await ctx.tick()

    @watchlist.command(name="add")
    async def watchlist_add(self, ctx, user_id: int, *, reason: str = None):
        """
        Add a user to the watchlist, Reason is optional

        Must use their user id!
        """
        if ctx.guild.id not in self.watchlist:
            self.watchlist[ctx.guild.id] = []

        user = self.bot.get_user(user_id)
        if not user:
            user = await self.bot.fetch_user(user_id)

        watch_list_ids = [w.user_id for w in self.watchlist[ctx.guild.id]]

        if not user:
            await ctx.send(error(f"Could not find user with id `{user_id}`!"))
            return
        elif user_id in watch_list_ids:
            await ctx.send(error(f"User {user} already in the watchlist!"))
            return

        if reason is None:
            reason = "Use `[p]watchlist reason <watchlist number>` to add a reason."

        watchlist_num = await self.config.guild(ctx.guild).watchlist_num()
        channel_id = await self.config.guild(ctx.guild).channel()
        channel = ctx.guild.get_channel(channel_id)
        alert_channel = await self.config.guild(ctx.guild).alert_channel()
        alert_channel = ctx.guild.get_channel(alert_channel)

        if not channel:
            await ctx.send(error(f"Could not find watchlist channel, please set it using `[p]watchlist channel` !"))
            return

        if not alert_channel:
            await ctx.send(
                warning(
                    "No alert channel set, you will not get alerts if this user joins! Please set it using `[p]watchlist alert`"
                )
            )

        watchlist_user = WatchlistUser(self.bot, user.id, watchlist_num, reason, ctx.author.id)
        await watchlist_user.send_watchlist_message(channel)

        self.watchlist[ctx.guild.id].append(watchlist_user)

        async with self.config.guild(ctx.guild).watchlist_users() as watchlist_users:
            watchlist_users.append(watchlist_user.to_dict())

        await self.config.guild(ctx.guild).watchlist_num.set(watchlist_num + 1)

        await ctx.tick()

    @watchlist.command(name="remove")
    async def watchlist_remove(self, ctx, watchlist_num: int, *, reason: str = None):
        """
        Remove a user from the watchlist.

        Reason is optional
        """
        if ctx.guild.id not in self.watchlist:
            self.watchlist[ctx.guild.id] = []

        watch_list_ids = [w.watchlist_number for w in self.watchlist[ctx.guild.id]]

        if watchlist_num not in watch_list_ids:
            await ctx.send(error("Unknown watchlist number!"))
            return

        idx = watch_list_ids.index(watchlist_num)
        watchlist_user = self.watchlist[ctx.guild.id][idx]
        if reason:
            watchlist_user.reason = f"Removed from watchlist by {ctx.author.mention} (id: {ctx.author.id}) because: {reason}\nOriginal reason: {watchlist_user.reason}"
        else:
            watchlist_user.reason = f"Removed from watchlist by {ctx.author.mention} (id: {ctx.author.id})\nOriginal reason: {watchlist_user.reason}"

        async with self.config.guild(ctx.guild).removed_users() as removed_users:
            removed_users.append(watchlist_user.to_dict())

        # delete message from watchlist channel
        status = await watchlist_user.delete_watchlist_message()

        if not status:
            await ctx.send(warning("There was an issue removing the message from the watchlist channel for this user!"))

        del self.watchlist[ctx.guild.id][idx]

        async with self.config.guild(ctx.guild).watchlist_users() as watchlist_users:
            ids = [w["watchlist_number"] for w in watchlist_users]
            idx = ids.index(watchlist_num)
            del watchlist_users[idx]

        await ctx.tick()

    @watchlist.command(name="reason")
    async def watchlist_reason(self, ctx, watchlist_num: int, *, reason):
        """
        Change the reason for a watchlist user

        Use the watchlist number to specify the user to change the reason for
        """
        if ctx.guild.id not in self.watchlist:
            self.watchlist[ctx.guild.id] = []

        watchlist_numbers = [w.watchlist_number for w in self.watchlist[ctx.guild.id]]

        if watchlist_num not in watchlist_numbers:
            await ctx.send(error("Unknown watchlist number!"))
            return

        idx = watchlist_numbers.index(watchlist_num)
        watchlist_user = self.watchlist[ctx.guild.id][idx]

        status = await watchlist_user.update_reason(ctx.author, reason)

        if not status:
            await ctx.send(error("There was an issue updating the reason!"))
        else:
            await ctx.tick()

    @watchlist.command(name="list")
    async def watchlist_list(self, ctx):
        """
        List removed users
        """
        removed_users = await self.config.guild(ctx.guild).removed_users()

        if len(removed_users) < 1:
            await ctx.send(info("No one has been removed from the watchlist in your guild."))
            return

        msg = ""
        for data in removed_users:
            user = self.bot.get_user(data["user_id"])
            if not user:
                user = await self.bot.fetch_user(data["user_id"])

            if user is None:
                msg += f"Unknown user (id: {data['user_id']})\n"
            else:
                msg += f"{user.mention} (id: {user.id})\n"

            msg += f"{data['reason']}\n"
            msg += ("=" * 10) + "\n"

        raw = list(
            pagify(
                msg,
                page_length=1700,
                delims=["\n"],
                priority=True,
            )
        )

        pages = []
        for i, page in enumerate(raw):
            pages.append(f"{page}\n\n-----------------\nPage {i+1} of {len(raw)}")
        if not pages:
            await ctx.send("No one has their birthday set in your server!")
        else:
            await menu(ctx, pages, DEFAULT_CONTROLS)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        guild = member.guild
        if guild.id not in self.watchlist:
            self.watchlist[guild.id] = []

        watchlist_ids = [w.user_id for w in self.watchlist[guild.id]]

        if not member.id in watchlist_ids:
            return

        idx = watchlist_ids.index(member.id)
        watchlist_user = self.watchlist[guild.id][idx]
        alert_channel = await self.config.guild(guild).alert_channel()
        channel = guild.get_channel(alert_channel)

        if not channel:
            return

        admin_roles = " ".join([r.mention for r in (await self.bot.get_admin_roles(guild))])
        mod_roles = " ".join([r.mention for r in (await self.bot.get_mod_roles(guild))])

        if not admin_roles or not mod_roles:
            await channel.send(
                f"**__Watchlist Alert for #{watchlist_user.watchlist_number}__**\n@everyone\n\nUser {member.mention} has joined!\n\n**Watchlist reason:** `{watchlist_user.reason}`",
                allowed_mentions=discord.AllowedMentions(everyone=True),
            )
        else:
            await channel.send(
                f"**__Watchlist Alert for #{watchlist_user.watchlist_number}__**\n{admin_roles} {mod_roles}\n\nUser {member.mention} has joined!\n\n**Watchlist reason:** `{watchlist_user.reason}`",
                allowed_mentions=discord.AllowedMentions(roles=True),
            )

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        guild = member.guild
        if guild.id not in self.watchlist:
            self.watchlist[guild.id] = []

        watchlist_ids = [w.user_id for w in self.watchlist[guild.id]]

        if not member.id in watchlist_ids:
            return

        idx = watchlist_ids.index(member.id)
        watchlist_user = self.watchlist[guild.id][idx]
        alert_channel = await self.config.guild(guild).alert_channel()
        channel = guild.get_channel(alert_channel)

        if not channel:
            return

        admin_roles = " ".join([r.mention for r in (await self.bot.get_admin_roles(guild))])
        mod_roles = " ".join([r.mention for r in (await self.bot.get_mod_roles(guild))])

        if not admin_roles or not mod_roles:
            await channel.send(
                f"**__Watchlist Alert for #{watchlist_user.watchlist_number}__**\n@everyone\n\nUser {member.mention} has left!\n\n**Watchlist reason:** `{watchlist_user.reason}`",
                allowed_mentions=discord.AllowedMentions(everyone=True),
            )
        else:
            await channel.send(
                f"**__Watchlist Alert for #{watchlist_user.watchlist_number}__**\n{admin_roles} {mod_roles}\n\nUser {member.mention} has left!\n\n**Watchlist reason:** `{watchlist_user.reason}`",
                allowed_mentions=discord.AllowedMentions(roles=True),
            )
