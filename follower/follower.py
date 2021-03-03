from redbot.core import commands, checks, Config
from redbot.core.utils.menus import menu, DEFAULT_CONTROLS
from redbot.core.utils.predicates import MessagePredicate
from redbot.core.utils.chat_formatting import *

from typing import Union
import time

# user must be inactive for an hour in a channel before message is sent, in seconds
# TODO: maybe make this customizable?
INACTIVITY_DELAY = 3600


class Follower(commands.Cog):
    """
    Twitter style following system
    """

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=478564389756438, force_registration=True)

        # followers/following maps channel_ids -> users
        # last_active_time maps channel_ids -> last time talked (for user)
        default_user = {
            "followers": {},
            "following": {},
            "opt_out": False,
            "blocked": [],
            "last_active_time": {},
        }
        # TODO: this can be modified to track a user in all channels, but
        # i feel that can be abused too easily for someone to stalk another user

        # TODO: maybe add economy credits to follow users?
        # only for global or per guild basis?
        self.config.register_user(**default_user)

    async def get_user(self, id: int):
        """
        Trys to get a user from cache, if not found uses API call
        """
        user = self.bot.get_user(id)
        if not user:
            user = await self.bot.fetch_user(id)

        return user

    async def unfollow(
        self,
        author: int,
        user: int,
        channel: int = None,
    ):
        """
        Unfollows user, by author

        channel is optional, if not provided unfollows user from every channel
        """
        followers = await self.config.user_from_id(user).followers()
        following = await self.config.user_from_id(author).following()
        last_active_time = await self.config.user_from_id(user).last_active_time()

        if not channel:
            to_delete = []
            for channel_id in following.keys():
                try:
                    following[channel_id].remove(user)
                    # if no other users in channel, clear channel from config
                    if not following[channel_id]:
                        to_delete.append(channel_id)
                except ValueError:
                    pass
                except KeyError:
                    pass

            for channel_id in to_delete:
                del following[channel_id]

            to_delete = []
            for channel_id in followers.keys():
                try:
                    followers[channel_id].remove(author)
                    # if no other users in channel, clear channel from config
                    if not followers[channel_id]:
                        to_delete.append(channel_id)
                except ValueError:
                    pass
                except KeyError:
                    pass

            for channel_id in to_delete:
                del followers[channel_id]
                del last_active_time[channel_id]
        else:
            try:
                following[str(channel)].remove(user)
                if not following[str(channel)]:
                    del following[str(channel)]
            except ValueError:
                pass
            except KeyError:
                pass

            try:
                followers[str(channel)].remove(author)
                if not followers[str(channel)]:
                    del followers[str(channel)]
                    del last_active_time[str(channel)]
            except ValueError:
                pass
            except KeyError:
                pass

        await self.config.user_from_id(user).followers.set(followers)
        await self.config.user_from_id(user).last_active_time.set(last_active_time)
        await self.config.user_from_id(author).following.set(following)

    @commands.group(name="follower", aliases=["fol"])
    async def followers(self, ctx):
        """
        Manage your followers (from DMs)! Followers allows others to get notified when you talk in a specific channel or join a voice chat.

        Its easiest to use the IDs of users, channels, etc when running these commands
        Follow this link to learn how to get IDs:
        https://support.discord.com/hc/en-us/articles/206346498-Where-can-I-find-my-User-Server-Message-ID-
        """
        pass

    @followers.group(name="list")
    async def followers_list(self, ctx):
        """
        List followers or those you are following
        """
        pass

    @followers_list.command(name="followers")
    async def followers_list_followers(self, ctx):
        """
        List who is following you
        """
        followers = await self.config.user_from_id(ctx.author.id).followers()

        if not followers:
            await ctx.send("You have no followers!")
            return

        users_list = {}
        for channel_id, users in followers.items():
            channel = self.bot.get_channel(int(channel_id))
            if not channel:
                # clean out guilds no longer in
                for user_id in users:
                    await self.unfollow(user_id, ctx.author.id, channel=channel_id)
                continue
            else:
                guild = channel.guild.name
                channel = channel.name

            for user_id in users:
                user = await self.get_user(user_id)
                if not user:
                    # user is deleted or something, remove
                    await self.unfollow(user_id, ctx.author.id)
                    continue
                else:
                    user = str(user)

                if not users_list.get(user, None):
                    users_list[user] = {}
                if not users_list[user].get(guild):
                    users_list[user][guild] = []

                users_list[user][guild].append(channel)

        msg = ""
        for user, guild_data in users_list.items():
            msg += f"{user}:\n"
            for guild, channels in guild_data.items():
                msg += f"\t- {guild}: {humanize_list(channels)}\n"
            msg += "\n\n"

        pages = list(pagify(msg, priority=True, page_length=1970))
        for i in range(len(pages)):
            pages[i] += f"\nPage {i+1} out of {len(pages)}"
            pages[i] = box(pages[i])

        await menu(ctx, pages, DEFAULT_CONTROLS)

    @followers_list.command(name="following")
    async def followers_list_following(self, ctx):
        """
        List who you are following
        """
        following = await self.config.user_from_id(ctx.author.id).following()

        if not following:
            await ctx.send("You aren't following anyone!")
            return

        users_list = {}
        for channel_id, users in following.items():
            channel = self.bot.get_channel(int(channel_id))
            if not channel:
                # clean out guilds no longer in
                for user_id in users:
                    await self.unfollow(user_id, ctx.author.id, channel=channel_id)
                continue
            else:
                guild = channel.guild.name
                channel = channel.name

            for user_id in users:
                user = await self.get_user(user_id)
                if not user:
                    # user is deleted or something, remove
                    await self.unfollow(user_id, ctx.author.id)
                    continue
                else:
                    user = str(user)

                if not users_list.get(user, None):
                    users_list[user] = {}
                if not users_list[user].get(guild):
                    users_list[user][guild] = []

                users_list[user][guild].append(channel)

        msg = ""
        for user, guild_data in users_list.items():
            msg += f"{user}:\n"
            for guild, channels in guild_data.items():
                msg += f"\t- {guild}: {humanize_list(channels)}\n"
            msg += "\n\n"

        pages = list(pagify(msg, priority=True, page_length=1970))
        for i in range(len(pages)):
            pages[i] += f"\nPage {i+1} out of {len(pages)}"
            pages[i] = box(pages[i])

        await menu(ctx, pages, DEFAULT_CONTROLS)

    @followers_list.command(name="blocked")
    async def followers_list_blocked(self, ctx):
        """
        List who you have blocked
        """
        blocked = await self.config.user_from_id(ctx.author.id).blocked()

        if not blocked:
            await ctx.send("You haven't blocked anyone!")
            return

        for i in range(len(blocked)):
            b = await self.get_user(blocked[i])
            blocked[i] = str(b) if b else f"Unkown user (id: {blocked[i]})"

        msg = "\n".join(blocked)

        pages = list(pagify(msg, priority=True, page_length=1970))
        for i in range(len(pages)):
            pages[i] += f"\n\nPage {i+1} out of {len(pages)}"
            pages[i] = box(pages[i])

        await menu(ctx, pages, DEFAULT_CONTROLS)

    @followers.command(name="opt-out")
    async def followers_opt_out(self, ctx, on_off: bool):
        """
        Opt out of followers

        This will stop anyone from following you
        You can still follow others
        """
        current = await self.config.user_from_id(ctx.author.id).opt_out()

        if not current and on_off:
            await ctx.send(warning("**Are you sure? This will remove ALL of your followers!** (y/n)"))
            pred = MessagePredicate.yes_or_no(ctx)
            try:
                await self.bot.wait_for("message", check=pred, timeout=30)
            except asyncio.TimeoutError:
                await ctx.send(error("Took too long, cancelling!"))
                return

            if pred.result:
                await self.config.user_from_id(ctx.author.id).followers.clear()
                await self.config.user_from_id(ctx.author.id).last_active_time.clear()
                await self.config.user_from_id(ctx.author.id).opt_out.set(True)
                await ctx.send("All followers removed, and no one will be able to follow you until you turn this off!")
            else:
                await ctx.send(warning("Cancelled."))
        elif current and not on_off:
            await self.config.user_from_id(ctx.author.id).opt_out.set(False)
            await ctx.send(warning("You have opted back in, users will be able to follow you again!"))
        elif current and on_off:
            await ctx.send(warning("You already opted out!"))
        elif not current and not on_off:
            await ctx.send(warning("You already are opted in!"))

    @followers.command(name="block")
    async def followers_block(self, ctx, *, user: discord.User):
        """
        Block a user from following you

        If using the command in DMs, its easier to use the user's ID
        """
        if user.id == ctx.author.id:
            await ctx.send(error("Sorry, you can't block yourself!"))
            return

        async with self.config.user_from_id(ctx.author.id).blocked() as blocked:
            if user.id in blocked:
                await ctx.send(error(f"You already blocked {user.mention}!"))
                return
            blocked.append(user.id)

        await self.unfollow(user.id, ctx.author.id)
        # also unfollow yourself from them
        await self.unfollow(ctx.author.id, user.id)

        await ctx.tick()

    @followers.command(name="unblock")
    async def followers_unblock(self, ctx, *, user: discord.User):
        """
        Unblock a user from following you

        If using the command in DMs, its easier to use the user's ID
        """
        if user.id == ctx.author.id:
            await ctx.send(error("Sorry, you can't unblock yourself!"))
            return

        async with self.config.user_from_id(ctx.author.id).blocked() as blocked:
            try:
                blocked.remove(user.id)
                await ctx.tick()
            except ValueError:
                await ctx.send(error(f"You haven't blocked {user.mention}!"))

    @followers.command(name="unfollow")
    async def followers_unfollow(
        self,
        ctx,
        user: discord.User,
        *,
        channel: Union[discord.TextChannel, discord.VoiceChannel] = None,
    ):
        """
        Unfollow a user.

        Channel is optional, if no channel is provided this will unfollow the user from ALL channels
        """
        if not channel:
            await ctx.send(
                warning(f"**Are you sure? This will remove ALL channels you are following {user.mention} in!** (y/n)")
            )
            pred = MessagePredicate.yes_or_no(ctx)
            try:
                await self.bot.wait_for("message", check=pred, timeout=30)
            except asyncio.TimeoutError:
                await ctx.send(error("Took too long, cancelling!"))
                return

            if pred.result:
                await self.unfollow(ctx.author.id, user.id)
        else:
            await self.unfollow(ctx.author.id, user.id, channel=channel.id)

        await ctx.tick()

    @followers.command(name="follow")
    async def followers_follow(
        self,
        ctx,
        user: discord.User,
        *,
        channel: Union[discord.TextChannel, discord.VoiceChannel],
    ):
        """
        Follow a user in a text or voice channel

        For voice channels, its best to use the channel's ID

        If in DMs, it is easier to use the user's ID and the channel's ID
        **Make sure to turn on allow DMs from me so I can notify you!**
        """
        blocked = await self.config.user(user).blocked()
        opt_out = await self.config.user(user).opt_out()

        if opt_out or ctx.author.id in blocked:
            await ctx.send(
                error(
                    "Sorry, you cannot follow this user because they blocked you or have turn off follower (opted-out)."
                )
            )
            return

        if user.id == ctx.author.id:
            await ctx.send(error("Sorry, you can't follow yourself!"))
            return

        member = channel.guild.get_member(ctx.author.id)
        if not member:
            await ctx.send(
                error(
                    f"You don't appear to be in the server {guild.name}\n\nIf this is a mistake, contact the bot owner."
                )
            )
            return

        perms = channel.permissions_for(member)
        if not perms.read_messages:
            await ctx.send(error("You don't have access to that channel!"))
            return

        async with self.config.user_from_id(ctx.author.id).following() as following:
            if not following.get(str(channel.id), None):
                following[str(channel.id)] = []

            following[str(channel.id)].append(user.id)

        async with self.config.user(user).followers() as followers:
            if not followers.get(str(channel.id), None):
                followers[str(channel.id)] = []

            followers[str(channel.id)].append(ctx.author.id)

        try:
            await user.send(
                f"**__Follower:__**\n**{ctx.author.mention} has followed you in {channel.mention if isinstance(channel, discord.TextChannel) else inline(channel.name)} on the server `{channel.guild.name}`**!\n\nIf you want this user to stop following you, block them using `{ctx.clean_prefix}follower block {ctx.author.id}`\n\nYou can also opt-out to stop anyone from following you using `{ctx.clean_prefix}follower opt-out on`\nYou can view your followers using `{ctx.clean_prefix}follower list followers`"
            )
        except discord.HTTPException:
            # cant notify user, so pass
            pass

        await ctx.tick()

    @commands.Cog.listener()
    async def on_message(self, message):
        if await self.bot.cog_disabled_in_guild(self, message.guild):
            return

        guild = message.guild
        channel = message.channel
        author = message.author

        user_followers = await self.config.user_from_id(author.id).followers()
        # check to see if anyone is following this user in the channel
        if not user_followers.get(str(channel.id), None):
            return

        # check to see last active time is within threshold
        last_active_time = (await self.config.user_from_id(author.id).last_active_time()).get(str(channel.id), 0)
        now = time.time()

        # update new last active time
        async with self.config.user_from_id(author.id).last_active_time() as l:
            l[str(channel.id)] = now

        if not now > last_active_time + INACTIVITY_DELAY:
            # within inactivity threshold
            return

        # notify followers of message
        for follower in user_followers[str(channel.id)]:
            user = await self.get_user(follower)
            # need to make sure the follower is in the same guild
            # if not, no need to notify. instead unfollow them automatically
            member = guild.get_member(follower)
            if not user:
                # afaik this should never happen with the API fetch user
                continue

            if not member:
                # clean member since they aren't in the same guild anymore
                await self.unfollow(follower, author.id, channel=channel.id)
                continue

            # make sure they have access to the channel
            perms = channel.permissions_for(member)
            if not perms.read_messages:
                # if they no longer have access, silently unfollow them
                await self.unfollow(follower, author.id, channel=channel.id)
                continue

            try:
                # i send to user object since i think this will work so long as
                # in one of the shared guilds the user has dm from server members
                # turned on, when used in multiple guilds, compared to sending to
                # member object of a specific guild
                preview = message.content[:200] if message.content else "*No preview available*"
                await user.send(
                    f"**__Follower:__**\n**{author.mention} sent a message in {channel.mention} on the server `{guild.name}`**\n\n**Message Preview:**\n{preview}\n\n{message.jump_url}"
                )
            except discord.HTTPException:
                # couldn't dm user, pass
                pass

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if (await self.bot.cog_disabled_in_guild(self, member.guild)) or not after.channel:
            return

        guild = member.guild
        channel = after.channel

        user_followers = await self.config.user_from_id(member.id).followers()
        # check to see if anyone is following this user in the channel
        if not user_followers.get(str(channel.id), None):
            return

        # check to see last active time is within threshold
        last_active_time = (await self.config.user_from_id(member.id).last_active_time()).get(str(channel.id), 0)
        now = time.time()

        # update new last active time
        async with self.config.user_from_id(member.id).last_active_time() as l:
            l[str(channel.id)] = now

        if not now > last_active_time + INACTIVITY_DELAY:
            # within inactivity threshold
            return

        # notify followers of message
        for follower in user_followers[str(channel.id)]:
            user = await self.get_user(follower)
            # need to make sure the follower is in the same guild
            # if not, no need to notify. instead unfollow them automatically
            member = guild.get_member(follower)
            if not user:
                # afaik this should never happen with the API fetch user
                continue

            if not member:
                # clean member since they aren't in the same guild anymore
                await self.unfollow(follower, author.id, channel=channel.id)
                continue

            # make sure they have access to the channel
            perms = channel.permissions_for(member)
            if not perms.read_messages:
                # if they no longer have access, silently unfollow them
                await self.unfollow(follower, author.id, channel=channel.id)
                continue

            try:
                await user.send(
                    f"**__Follower:__**\n**{member.mention} joined the VC `{channel.name}` on the server `{guild.name}`**"
                )
            except discord.HTTPException:
                # couldn't dm user, pass
                pass
