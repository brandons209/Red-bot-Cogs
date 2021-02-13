from redbot.core import commands, checks, Config
from redbot.core.utils.chat_formatting import *
from redbot.core.utils.predicates import MessagePredicate
from typing import Literal
import asyncio, discord, random


class Valentine_Cards(commands.Cog):
    """
    Distribute valentine (or any messages / pictures) to all members in a server.
    Cards and messages are randomly selected for each person
    """

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=8465846534353571, force_registration=True)
        default_guild = {"cards": [], "dm_msgs": [], "fallback_channel": None}

        self.config.register_guild(**default_guild)

    @staticmethod
    def format_list(items: list) -> list:
        """
        Format a list into a numbered list for printing

        Returns pages of text
        """
        if not items:
            return []

        msg = "\n".join(f"{i+1}. {item}" for i, item in enumerate(items))
        return pagify(msg)

    @commands.group(name="vset")
    @checks.admin_or_permissions(administrator=True)
    @commands.guild_only()
    async def vset(self, ctx):
        """
        Manage cards and DM messages
        """
        pass

    @vset.command(name="fallback")
    async def vset_fallback_channel(self, ctx, *, channel: discord.TextChannel = None):
        """
        Set a channel as fallback when DM fails

        Run command with no channel to reset channel
        """
        if not channel:
            current_channel = await self.config.guild(ctx.guild).fallback_channel()
            if not current_channel:
                await ctx.send(warning("No fallback channel set."))
            elif not ctx.guild.get_channel(current_channel):
                await ctx.send(
                    warning("Channel set but I cannot see the channel, so I will reset the fallback channel saved.")
                )
                await self.config.guild(ctx.guild).fallback_channel.clear()
            else:
                await ctx.send(f"Current fallback channel: {ctx.guild.get_channel(current_channel).mention}")
            return

        await self.config.guild(ctx.guild).fallback_channel.set(channel.id)
        await ctx.tick()

    @vset.group(name="cards")
    async def vset_cards(self, ctx):
        """
        Manage cards
        """
        pass

    @vset_cards.command(name="add")
    async def vset_cards_add(self, ctx, *, url: str):
        """
        Add a possible card to be sent to a user

        Card should be a URL to the image
        """
        async with self.config.guild(ctx.guild).cards() as cards:
            cards.append(url)

        await ctx.tick()

    @vset_cards.command(name="list")
    async def vset_cards_list(self, ctx):
        """
        List the current cards
        """
        cards = await self.config.guild(ctx.guild).cards()
        if not cards:
            await ctx.send(warning("No cards defined."))
            return

        pages = self.format_list(cards)
        for page in pages:
            await ctx.send(page)

    @vset_cards.command(name="del")
    async def vset_cards_del(self, ctx):
        """
        Delete a card
        """
        async with self.config.guild(ctx.guild).cards() as cards:
            if not cards:
                await ctx.send(warning("No cards defined."))
                return
            pages = self.format_list(cards)
            for page in pages:
                await ctx.send(box(page))

            await ctx.send("Please choose the number of the message to delete.")
            pred = MessagePredicate.contained_in([str(i + 1) for i in range(len(cards))], ctx=ctx)
            try:
                await self.bot.wait_for("message", check=pred, timeout=60)
            except asyncio.TimeoutError:
                await ctx.send("Took too long, cancelled.")
                return

            del cards[pred.result]

        await ctx.tick()

    @vset.group(name="dms")
    async def vset_dms(self, ctx):
        """
        Manage DM messages
        """
        pass

    @vset_dms.command(name="add")
    async def vset_dms_add(self, ctx, *, msg: str):
        """
        Add a possible DM message to be sent to a user
        """
        async with self.config.guild(ctx.guild).dm_msgs() as dm_msgs:
            dm_msgs.append(msg)

        await ctx.tick()

    @vset_dms.command(name="list")
    async def vset_dms_list(self, ctx):
        """
        List the current DM messages
        """
        dm_msgs = await self.config.guild(ctx.guild).dm_msgs()
        if not dm_msgs:
            await ctx.send(warning("No DM messages defined."))
            return
        pages = self.format_list(dm_msgs)
        for page in pages:
            await ctx.send(box(page))

    @vset_dms.command(name="del")
    async def vset_dms_del(self, ctx):
        """
        Delete a DM message
        """
        async with self.config.guild(ctx.guild).dm_msgs() as dm_msgs:
            if not dm_msgs:
                await ctx.send(warning("No DM messages defined."))
                return
            pages = self.format_list(dm_msgs)
            for page in pages:
                await ctx.send(box(page))

            await ctx.send("Please choose the number of the message to delete.")
            pred = MessagePredicate.contained_in([str(i + 1) for i in range(len(dm_msgs))], ctx=ctx)
            try:
                await self.bot.wait_for("message", check=pred, timeout=60)
            except asyncio.TimeoutError:
                await ctx.send("Took too long, cancelled.")
                return

            del dm_msgs[pred.result]

        await ctx.tick()

    @commands.command(name="sendcards")
    @checks.admin_or_permissions(administrator=True)
    @commands.guild_only()
    async def valentine_cards(self, ctx):
        """
        Send out valentine cards!

        Everyone in the server with DMs enabled will receive a custom message and card!
        Failed DMs will be sent in the fallback channel, if available.
        """
        # update members
        _guilds = [g for g in self.bot.guilds if g.large and not (g.chunked or g.unavailable)]
        await self.bot.request_offline_members(*_guilds)

        members = [m for m in ctx.guild.members if m != ctx.guild.me]

        fallback = ctx.guild.get_channel(await self.config.guild(ctx.guild).fallback_channel())

        pred = MessagePredicate.yes_or_no(ctx)
        if not fallback:
            extra = warning("\n\nThere is no fallback channel set, you should set it before running this command.")
        else:
            extra = ""

        await ctx.send(f"Are you sure you want to send cards to {len(members)} members?{extra}")
        try:
            await self.bot.wait_for("message", check=pred, timeout=60)
        except asyncio.TimeoutError:
            await ctx.send("Took too long, cancelled.")
            return

        if not pred.result:
            await ctx.send("Cancelled.")
            return

        # lets gooooo
        dm_msgs = await self.config.guild(ctx.guild).dm_msgs()
        cards = await self.config.guild(ctx.guild).cards()
        update_msg = await ctx.send(f"Processed `1` out of `{len(members)}` members.")
        failed = 0
        for i, member in enumerate(members):
            msg = random.choice(dm_msgs)
            card = random.choice(cards)

            try:
                await member.send(msg)
                await asyncio.sleep(0.01)
                await member.send(card)
            except discord.HTTPException:
                if fallback:
                    await fallback.send(msg)
                    await asyncio.sleep(0.01)
                    await fallback.send(f"{member.mention}\n{card}")
                failed += 1

            if i % 10 == 0:
                await update_msg.edit(content=f"Processed `{i+1}` out of `{len(members)}` members.")

        if failed:
            await update_msg.edit(
                content=f"DMed `{len(members) - failed}` members successfully and failed to send a DM to `{failed}` members, they were sent in the fallback channel if set."
            )
        else:
            await update_msg.edit(content=f"DMed `{len(members)}` members successfully.")

    async def red_delete_data_for_user(
        self,
        *,
        requester: Literal["discord_deleted_user", "owner", "user", "user_strict"],
        user_id: int,
    ):
        pass
