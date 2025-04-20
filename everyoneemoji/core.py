import io

import aiohttp
import discord
import re
from redbot.core import commands
from redbot.core.utils.chat_formatting import error
from typing import Union

EMOJI_ID_RE = re.compile(r"<a?:(?:[A-Za-z0-9_]+):([0-9]+)>")


class EveryoneEmoji(commands.Cog):
    """Allows anyone to use all emojis the bot can see!"""

    def __init__(self, bot):
        self.bot = bot
        self.session = aiohttp.ClientSession()

    def cog_unload(self):
        self.bot.loop.create_task(self.session.close())

    @commands.hybrid_command(name="e")
    async def emoji_send(self, ctx, emoji_or_id: str):
        """Post emoji. Emoji can be animated or not.

        Even if you don't have nitro, you can send emojis!

        If you have nitro, you can send emojis from many server you are in!

        If you normally can't use the emoji (don't have nitro)
        then you can use any emoji in **this server** using :emoji_name:
        and it will send.
        To send emojis from other servers without nitro, you need the **emoji ID**.
        then use [p]e <emoji_id>

        Make sure the bot has manage message permissions for cleaner chat
        """
        # just pass if failing to delete message, it should still run even if don't have manage
        # message permissions.
        try:
            await ctx.message.delete()
        except:
            pass

        emoji_id = re.match(EMOJI_ID_RE, emoji_or_id)
        parsed_emoji = None
        if emoji_id:
            parsed_emoji = self.bot.get_emoji(int(emoji_id.group(1)))
        elif emoji_or_id[0] == ":" and emoji_or_id[-1] == ":":
            name = emoji_or_id.strip(":")
            parsed_emoji: Union[discord.Emoji, None] = discord.utils.get(ctx.guild.emojis, name=name)
        elif emoji_or_id.isnumeric():
            parsed_emoji = self.bot.get_emoji(int(emoji_or_id))

        if not parsed_emoji:
            await ctx.send(error("Can't find that emoji!"), delete_after=15)
            return

        url = parsed_emoji.url
        async with self.session.get(str(url)) as resp:
            if resp.status != 200:
                await ctx.send(error("Can't find that emoji!"), delete_after=15)
                return
            img = await resp.read()

        img = io.BytesIO(img)

        await ctx.send(
            f"{ctx.author.display_name} says:",
            file=discord.File(img, f"{parsed_emoji.name}.{'.gif' if parsed_emoji.animated else '.png'}"),
        )
