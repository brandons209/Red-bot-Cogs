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

    Can also set roles that give emojis as well that stacks with boosting
    """

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=123859659843, force_registration=True)
        # roles maps: role id (str) -> number of allowed emojis (int)
        default_guild = {"channel": None, "disabled": False, "roles": {}}
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

    async def get_boosts(self, member: discord.Member):
        # this will return number of boosts once api supports it
        # for now, set custom roles that give how ever emojis set
        # boosting stacks with custom roles and
        # custom roles stack with each other
        custom_roles = await self.config.guild(member.guild).roles()
        members_roles = [str(r.id) for r in member.roles]
        num_emojis = 0
        for c_role in custom_roles.keys():
            if c_role in members_roles:
                num_emojis += custom_roles[c_role]

        # TODO: add in checking for multiple emojis once supported
        if member.premium_since is not None:
            num_emojis += 1

        return num_emojis

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
            try:
                await emoji.delete()
            except:
                pass
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

    @nitroset.command(name="role")
    async def nitroset_roles(self, ctx, num_emojis: int, *, role: discord.Role):
        """
        Set the amount of emojis role is allowed to add.

        Set to 0 to remove role.
        """
        async with self.config.guild(ctx.guild).roles() as roles:
            if num_emojis == 0:
                try:
                    del roles[str(role.id)]
                except:
                    pass
            else:
                roles[str(role.id)] = num_emojis

        await ctx.tick()

    @nitroset.command(name="list")
    async def nitroset_list(self, ctx):
        """
        List roles and the number of emojis they give.
        """
        msg = ""

        async with self.config.guild(ctx.guild).roles() as roles:
            if roles:
                msg += "Current roles:\n"
                for role_id in list(roles.keys()):
                    role = ctx.guild.get_role(int(role_id))
                    if not role:  # remove deleted roles silently
                        del roles[role_id]
                        continue
                    msg += f"{role.name}: {roles[role_id]}\n"

                for page in pagify(msg):
                    await ctx.send(box(page))
            else:
                await ctx.send("No roles defined.")

    @commands.group(name="nitroemoji")
    @checks.bot_has_permissions(manage_emojis=True)
    async def nitroemoji(self, ctx):
        """
        Manage your emojis if you boosted the server, or have a special role
        """
        pass

    @nitroemoji.command(name="add")
    async def nitroemoji_add(self, ctx, name: str, *, url: str = None):
        """
        Add an emoji to the server, if you boosted or have a special role

        Can only add an emoji for every boost you have in the server.
        """
        disabled = await self.config.guild(ctx.guild).disabled()
        if disabled:
            await ctx.send("Sorry, adding emojis is currently disabled right now.")
            return

        curr = await self.config.member(ctx.author).emojis()
        boosts = await self.get_boosts(ctx.author)
        if boosts and len(curr) < boosts:
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
            await ctx.send("Sorry, you need to be a nitro booster or have a special role to add an emoji!")
        elif curr:
            await ctx.send(
                "You already have the maximum number of custom emojis, please delete one first before adding another one."
            )

    @nitroemoji.command(name="rem")
    async def nitroemoji_rem(self, ctx, name: str):
        """
        Remove an emoji to the server, if you boosted or have a special role
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
        boosts = await self.get_boosts(ctx.author)
        msg = f"Number of custom emojis used: {len(curr)}/{boosts}\n"
        if curr:
            msg += "Current emojis:\n"
            for emoji in curr:
                emoji = self.find_emoji(ctx.guild, emoji)
                if not emoji:
                    continue
                msg += f"{emoji.url}\n"
        else:
            msg += "`You have no custom emojis.`"

        for page in pagify(msg):
            await ctx.send(page)

    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        # check if they stopped boosting
        if (before.premium_since != after.premium_since and after.premium_since is None) or before.roles != after.roles:
            boosts = await self.get_boosts(after)
            emojis = await self.config.member(after).emojis()
            if len(emojis) > boosts:
                to_delete = []
                for i in range(len(emojis) - (len(emojis) - boosts), len(emojis)):
                    to_delete.append(emojis[i])

                for emoji in to_delete:
                    emoji = self.find_emoji(after.guild, emoji)
                    if not emoji:
                        continue

                    reason = ""
                    if before.premium_since != after.premium_since and after.premium_since is None:
                        reason += "Stopped boosting."
                    if before.roles != after.roles:
                        broles = set(before.roles)
                        aroles = set(after.roles)
                        removed = broles - aroles
                        reason += f"\nLost roles: {humanize_list(list(removed))}"

                    await self.del_emoji(after.guild, after, emoji=emoji, reason=reason)

    @commands.Cog.listener()
    async def on_guild_emojis_update(self, guild, before, after):
        b_e = set(before)
        a_e = set(after)
        diff = b_e - a_e
        if diff:
            for e in diff:
                user = None
                try:
                    async for entry in guild.audit_logs(limit=2):
                        if entry.action is discord.AuditLogAction.emoji_delete:
                            # if the bot didnt delete emoji
                            if entry.target.id != guild.me.id:
                                user = entry.user
                except:
                    continue
                # sanity check
                if not user or user.id == guild.me.id:
                    continue

                for member in guild.members:
                    curr = await self.config.member(member).emojis()
                    try:
                        async with self.config.member(member).emojis() as curr:
                            curr.remove(e.id)
                        await self.del_emoji(
                            guild, member, emoji=e, reason=f"Manually deleted by admin {user.name} (id: {user.id})"
                        )
                        break
                    except ValueError:
                        pass
