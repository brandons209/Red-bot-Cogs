from redbot.core.utils.chat_formatting import *
from redbot.core import Config, checks, commands, bank
from redbot.core.data_manager import cog_data_path
import discord

import aiohttp
import PIL
import os


class NitroEmoji(commands.Cog):
    """
    Reward nitro boosters with a custom emoji.
    """

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=123859659843, force_registration=True)
        default_guild = {"channel": None, "disabled": False}
        default_member = {"emojis": []}
        self.config.register_guild(**default_guild)
        self.config.register_member(**default_member)

    async def initialize(self):
        for member in self.bot.get_all_members():
            async with self.config.member(member).emojis() as data:
                to_remove = []
                for e in data:
                    emoji = self.find_emoji(member.guild, e)
                    # clean removed emojis if bot is down
                    if not emoji:
                        to_remove.append(e)

                for r in to_remove:
                    data.remove(r)

    @staticmethod
    def get_boosts(member: discord.Member):
        # this will return number of boosts once api supports it
        return member.premium_since is not None

    def find_emoji(self, guild, name):
        emoji = self.bot.get_emoji(name)
        # find by name:
        if not emoji:
            emoji = discord.utils.get(guild.emojis, name=name)
        return emoji

    async def add_emoji(self, member, name, attachment_or_url, reason=None):
        path = str(cog_data_path(cog_instance=self))
        path = os.path.join(path, str(member.id) + name)
        if isinstance(attachment_or_url, discord.Attachment):
            await attachment_or_url.save(path)
        elif isinstance(attachment_or_url, str):
            async with aiohttp.ClientSession(loop=self.bot.loop) as session:
                async with session.get(attachment_or_url) as r:
                    if r.status == 200:
                        with open(path, "wb") as f:
                            f.write(await r.read())

        # verify image
        im = PIL.Image.open(path)
        im.verify()

        # upload emoji
        with open(path, "rb") as f:
            emoji = await member.guild.create_custom_emoji(name=name, image=f.read())

        os.remove(path)

        async with self.config.member(member).emojis() as e:
            e.append(emoji.id)

        channel = await self.config.guild(member.guild).channel()
        channel = member.guild.get_channel(channel)
        if not channel:
            return

        embed = discord.Embed(title="Custom Emoji Added", colour=member.colour)
        embed.set_footer(text="User ID:{}".format(member.id))

        embed.set_author(name=str(member), url=emoji.url)
        embed.set_thumbnail(url=emoji.url)
        embed.set_author(name=str(member))

        if reason:
            embed.add_field(name="Reason", value=reason)

        await channel.send(embed=embed)

    async def del_emoji(self, guild, member, emoji=None, reason=None):
        channel = await self.config.guild(member.guild).channel()
        channel = member.guild.get_channel(channel)
        if channel:
            embed = discord.Embed(title="Custom Emoji Removed", colour=member.colour)
            embed.set_footer(text="User ID:{}".format(member.id))

            embed.set_author(name=str(member), url=emoji.url)
            embed.set_thumbnail(url=emoji.url)
            embed.set_author(name=str(member))

            if reason:
                embed.add_field(name="Reason", value=reason)

            await channel.send(embed=embed)

        if emoji:
            await emoji.delete()
            async with self.config.member(member).emojis() as e:
                e.remove(emoji.id)

    @commands.group(name="nitroset")
    @commands.guild_only()
    @checks.admin()
    async def nitroset(self, ctx):
        """Manage nitro emoji settings."""
        pass

    @nitroset.command(name="channel")
    async def nitroset_channel(self, ctx, channel: discord.TextChannel):
        """
        Set the channel to log nitro events.

        Logs boosts, unboosts, and added emojis.
        """

        await self.config.guild(ctx.guild).channel.set(channel.id)
        await ctx.tick()

    @nitroset.command(name="disable")
    async def nitroset_disable(self, ctx, *, on_off: bool = None):
        """
        Disable users from adding more emojis.

        Users can still remove and list their own emojis.
        """
        if on_off is None:
            curr = await self.config.guild(ctx.guild).disabled()
            msg = "enabled" if not curr else "disabled"
            await ctx.send(f"Nitro emojis is {msg}.")
            return

        await self.config.guild(ctx.guild).disabled.set(on_off)
        await ctx.tick()

    @commands.group(name="nitroemoji")
    @checks.bot_has_permissions(manage_emojis=True)
    async def nitroemoji(self, ctx):
        """
        Manage your emojis if you boosted the server.
        """
        pass

    @nitroemoji.command(name="add")
    async def nitroemoji_add(self, ctx, name: str, *, url: str = None):
        """
        Add an emoji to the server, if you boosted.

        Can only add an emoji for every boost you have in the server.
        """
        disabled = await self.config.guild(ctx.guild).disabled()
        if disabled:
            await ctx.send("Sorry, adding emojis is currently disabled right now.")
            return

        curr = await self.config.member(ctx.author).emojis()
        boosts = self.get_boosts(ctx.author)
        # TODO: add in checking for multiple emojis once supported
        if boosts and not curr:
            try:
                if url:
                    emoji = await self.add_emoji(ctx.author, name, url)
                else:
                    emoji = await self.add_emoji(ctx.author, name, ctx.message.attachments[0])
                await ctx.tick()
            except discord.errors.HTTPException as e:
                await ctx.send(e.text)
            except PIL.UnidentifiedImageError:
                await ctx.send("That is not a valid picture! Pictures must be in PNG, JPEG, or GIF format.")
            except:
                await ctx.send(
                    "Something went wrong, make sure to add a valid picture (PNG, JPG, or GIF) of the right size (256KB) and a valid name."
                )
                return
        elif not boosts:
            await ctx.send("Sorry, you need to be a nitro booster to add an emoji!")
        elif curr:
            await ctx.send("You already have a custom emoji, please delete it first before adding another one.")

    @nitroemoji.command(name="rem")
    async def nitroemoji_rem(self, ctx, name: str):
        """
        Remove an emoji to the server, if you boosted.
        """
        curr = await self.config.member(ctx.author).emojis()
        emoji = self.find_emoji(ctx.guild, name)
        if emoji:
            if emoji.id in curr:
                await self.del_emoji(ctx.guild, ctx.author, emoji=emoji, reason="Removed by user.")
                await ctx.tick()
            else:
                await ctx.send("That isn't your custom emoji.")
        else:
            await ctx.send(warning("Emoji not found."))

    @nitroemoji.command(name="list")
    async def nitroemoji_list(self, ctx):
        """
        List your custom emojis in the server
        """
        curr = await self.config.member(ctx.author).emojis()
        msg = ""
        if curr:
            msg += "Current emojis:\n"
            for emoji in curr:
                emoji = self.find_emoji(ctx.guild, emoji)
                if not emoji:
                    continue
                msg += f"{emoji.url}\n"
        else:
            msg += "You have no custom emojis."

        for page in pagify(msg):
            await ctx.send(page)

    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        # check if they stopped boosting
        if before.premium_since != after.premium_since and after.premium_since is None:
            emojis = await self.config.member(after).emojis()
            for emoji in emojis:
                emoji = self.find_emoji(after.guild, emoji)
                if not emoji:
                    continue
                await self.del_emoji(after.guild, after, emoji=emoji, reason="Stopped boosting.")

    @commands.Cog.listener()
    async def on_guild_emojis_update(self, guild, before, after):
        b_e = set(before)
        a_e = set(after)
        diff = b_e - a_e
        if diff:
            for e in diff:
                for member in guild.premium_subscribers:
                    curr = await self.config.member(member).emojis()
                    if e.id in curr:
                        curr.remove(e.id)
                        await self.config.member(member).emojis.set(curr)
                        await self.del_emoji(guild, member, emoji=e, reason="Manually deleted by admin.")
                        break
