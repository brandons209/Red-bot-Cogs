import asyncio
import functools
import io
import unicodedata

import aiohttp
import discord
from redbot.core import commands, checks


class EveryoneEmoji(commands.Cog):

    """Allows anyone to use all emojis the bot can see!"""

    def __init__(self, bot):
        self.bot = bot
        self.session = aiohttp.ClientSession()

    def cog_unload(self):
        self.bot.loop.create_task(self.session.close())

    @commands.command(name="e")
    async def emoji_send(self, ctx, emoji: str):
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
        if emoji[0] == "<":
            # custom Emoji
            name = emoji.split(":")[1]
            emoji_name = emoji.split(":")[2][:-1]
            if emoji.split(":")[0] == "<a":
                # animated custom emoji
                url = "https://cdn.discordapp.com/emojis/" + emoji_name + ".gif"
                name += ".gif"
            else:
                url = "https://cdn.discordapp.com/emojis/" + emoji_name + ".png"
                name += ".png"
        elif emoji[0] == ":" and emoji[-1] == ":":
            name = emoji.strip(":")
            emoji = discord.utils.get(ctx.guild.emojis, name=name)
            if emoji:
                if emoji.animated:
                    url = "https://cdn.discordapp.com/emojis/" + str(emoji.id) + ".gif"
                    name += ".gif"
                else:
                    url = "https://cdn.discordapp.com/emojis/" + str(emoji.id) + ".png"
                    name += ".png"
            else:
                url = None
        elif emoji.isnumeric():
            name = ("none.gif", "none.png")
            # could be animated or regular, check both
            url = ["https://cdn.discordapp.com/emojis/" + emoji + ".gif"]
            url += ["https://cdn.discordapp.com/emojis/" + emoji + ".png"]
        else:
            chars = []
            name = []
            for char in emoji:
                chars.append(str(hex(ord(char)))[2:])
                try:
                    name.append(unicodedata.name(char))
                except ValueError:
                    # Sometimes occurs when the unicodedata library cannot
                    # resolve the name, however the image still exists
                    name.append("none")

            name = "_".join(name) + ".png"
            url = "https://twemoji.maxcdn.com/2/72x72/" + "-".join(chars) + ".png"

        if type(url) == list:
            async with self.session.get(url[0]) as resp:
                if not resp.status != 200:
                    name = name[0]
                    img = await resp.read()
                else:
                    async with self.session.get(url[1]) as resp_2:
                        if resp_2.status != 200:
                            await ctx.send("Emoji not found.")
                            return
                        name = name[1]
                        img = await resp_2.read()
        else:
            async with self.session.get(url) as resp:
                if resp.status != 200:
                    await ctx.send("Emoji not found.")
                    return
                img = await resp.read()

        img = io.BytesIO(img)

        await ctx.send(f"{ctx.author.display_name} says:", file=discord.File(img, name))
