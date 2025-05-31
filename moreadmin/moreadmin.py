from datetime import datetime, timedelta, timezone
from redbot.core.utils.chat_formatting import *
from redbot.core.utils import mod
from redbot.core.utils.menus import menu, DEFAULT_CONTROLS
from redbot.core import Config, checks, commands, modlog
from redbot.core.commands.converter import parse_timedelta
import discord
from redbot.core.utils.predicates import MessagePredicate

from .utils import *
from typing import List, Union, Optional, Dict
import asyncio, time

LOG_MSG = "[Moreadmin] {}"

# guild is guild name
BAN_DM_MESSAGE = "You have been banned from {guild} for {reason}."
BAITED_MESSAGE = "Hello {member}! You have added the {role} role to yourself in {guild}. This role is meant to capture bots that add the role to themselves. Please remove the role using the Channels & Roles section at the top of the server."


class MoreAdmin(commands.Cog):
    """
    Provides some more Admin commands to Red.
    """

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=9468294573, force_registration=True)

        default_guild = {
            "user_count_channel": None,
            "sus_user_channel": None,
            "sus_user_threshold": 0,
            "sus_user_kick_threshold": 0,
            "sus_user_kick_spammer": False,
            "ignore_bot_commands": False,
            "baited_role": None,
            "baited_channel": None,
            "ban_baited_after": None,
            "baited_message": BAITED_MESSAGE,
            "ban_dm": BAN_DM_MESSAGE,
        }

        default_role = {"addable": []}  # role ids who can add this role

        # maps message_time -> dict("channel_id":int, "message_id": int)
        default_member = {"baited": None, "notes": []}

        self.config.register_role(**default_role)
        self.config.register_member(**default_member)
        self.config.register_guild(**default_guild)

        #  add user count updater task
        self.loop_task = asyncio.create_task(self.loop())
        self.loop_task2 = asyncio.create_task(self.baited_loop())

    def cog_unload(self):
        self.loop_task.cancel()
        self.loop_task2.cancel()

    async def baited_loop(self):
        await self.bot.wait_until_ready()
        while not self.bot.is_closed():
            try:
                await self.check_baited_role()
            except asyncio.CancelledError:
                # normal exit
                break
            except Exception as e:
                print(LOG_MSG.format(f"Internal baited loop crashed, restarting in 10s, error: {e}"))
                await asyncio.sleep(10)

    async def check_baited_role(self):
        while True:
            for guild in self.bot.guilds:
                baited_role = await self.config.guild(guild).baited_role()
                if baited_role is None:
                    continue
                baited_role = guild.get_role(baited_role)
                if baited_role is None:
                    continue
                baited_channel = await self.config.guild(guild).baited_channel()
                baited_channel = guild.get_channel_or_thread(baited_channel)
                # check if anyone got baited, and send them a reminder to remove the role or get banned
                for member in baited_role.members:
                    baited_check = await self.config.member(member).baited()
                    ban_baited_after = await self.config.guild(guild).ban_baited_after()
                    # print(member, baited_check)
                    if ban_baited_after is not None:
                        ban_baited_after = timedelta(seconds=ban_baited_after)
                    if baited_check is None:
                        msg = await self.config.guild(guild).baited_message()
                        # send reminder and update baited time
                        send_channel = baited_channel if baited_channel is not None else member
                        try:
                            msg = msg.format(member=member.mention, role=bold(str(baited_role)), guild=guild)
                            if ban_baited_after:
                                msg += f"\n\nYou will be automatically **banned** from {guild} after {bold(humanize_timedelta(timedelta=ban_baited_after))} if no action is taken."
                            await send_channel.send(msg)
                        except:
                            pass
                        await self.config.member(member).baited.set(int(discord.utils.utcnow().timestamp()))
                    elif ban_baited_after is not None:
                        baited_check = datetime.fromtimestamp(baited_check, tz=timezone.utc)
                        now = discord.utils.utcnow()
                        if (now - baited_check) > ban_baited_after:
                            # automatically ban baited user, make modlog case if loaded
                            try:
                                reason = f"Automatically banned after having baited role {baited_role} for {humanize_timedelta(timedelta=ban_baited_after)}."
                                try:
                                    await modlog.create_case(
                                        self.bot, guild, now, "ban", member, moderator=guild.me, reason=reason
                                    )
                                except:
                                    pass
                                await guild.ban(
                                    member,
                                    reason=reason,
                                )
                            except Exception as e:
                                print(LOG_MSG.format(f"Failed baited ban for {member} in {guild}: {e}"))
                                try:
                                    await guild.owner.send(
                                        error(f"I cannot automatically ban baited users, please check permissions!")
                                    )
                                except:
                                    pass
                            finally:
                                await self.config.member(member).baited.clear()

            await asyncio.sleep(5)  # TODO change

    async def loop(self):
        await self.bot.wait_until_ready()
        while not self.bot.is_closed():
            try:
                await self.user_count_updater()
            except asyncio.CancelledError:
                # normal exit
                break
            except Exception as e:
                print(LOG_MSG.format(f"Internal loop crashed, restarting in 10s, error: {e}"))
                await asyncio.sleep(10)

    async def user_count_updater(self):
        SERVER_STATS_MSG = "USERS: {}/{}"
        SERVER_STATS_CHANNEL_MSG = "users-{}-{}"
        SLEEP_TIME = 500
        while True:
            for guild in self.bot.guilds:
                if await self.bot.cog_disabled_in_guild(self, guild):
                    continue
                channel = await self.config.guild(guild).user_count_channel()
                if channel:
                    channel = guild.get_channel_or_thread(channel)
                    online = len([m.status for m in guild.members if m.status != discord.Status.offline])
                    if isinstance(channel, discord.TextChannel):
                        title = SERVER_STATS_CHANNEL_MSG.format(online, len(guild.members))
                    else:
                        title = SERVER_STATS_MSG.format(online, len(guild.members))
                    try:
                        await channel.edit(name=title)
                    except Exception as e:
                        print(LOG_MSG.format(f"Failed updating user count for guild {guild}: {e}"))
                        try:
                            await guild.owner.send(
                                error(f"I cannot edit channel {channel} for user counts, please check permissions!")
                            )
                        except:
                            pass

            await asyncio.sleep(SLEEP_TIME)

    @commands.group(name="adminset")
    @commands.guild_only()
    @checks.admin_or_permissions(administrator=True)
    async def adminset(self, ctx):
        """
        Manage more admin settings.
        """
        pass

    @adminset.group(name="bait")
    async def adminset_baited(self, ctx):
        """
        Manage bot baiting functionality
        """
        pass

    @adminset_baited.command(name="role")
    async def adminset_baited_role(self, ctx, role: Union[discord.Role, str]):
        """
        Set the role for baiting bots
        The role should be user addable in either onboarding or role channels for proper function

        Pass `disable` to disable bait role function
        """
        if isinstance(role, str):
            if role.lower() == "disable":
                await self.config.guild(ctx.guild).baited_role.clear()
                await ctx.tick()
                return
            else:
                await ctx.send(error("Invalid role!"), delete_after=30, reference=ctx.message)
                return

        await self.config.guild(ctx.guild).baited_role.set(role.id)
        await ctx.tick()

    @adminset_baited.command(name="channel")
    async def adminset_baited_channel(
        self, ctx, channel: Union[discord.TextChannel, discord.VoiceChannel, discord.Thread, str]
    ):
        """
        Set the channel to message baited users in
        If no channel is set the user will be DMed the baited message instead

        Pass `disable` to remove baited channel
        """
        if isinstance(channel, str):
            if channel.lower() == "disable":
                await self.config.guild(ctx.guild).baited_channel.clear()
                await ctx.tick()
                return
            else:
                await ctx.send(error("Invalid channel!"), delete_after=30, reference=ctx.message)
                return

        await self.config.guild(ctx.guild).baited_channel.set(channel.id)
        await ctx.tick()

    @adminset_baited.command(name="autoban")
    @checks.bot_has_permissions(ban_members=True)
    async def adminset_baited_autoban(self, ctx, ban_after: str):
        """
        Set time to automatically ban a baited user after

        Pass `disable` to disable

        Interval should look like:
           5 minutes
           1 minute 30 seconds
           1 hour
           2 days
           30 days
           5h30m
           (etc)
        """
        if ban_after.lower() == "disable":
            await self.config.guild(ctx.guild).ban_baited_after.clear()
            await ctx.tick()
            return

        interval = parse_timedelta(ban_after)
        if not interval:
            await ctx.send(error("Invalid interval time!"), delete_after=30, reference=ctx.message)
            return

        await self.config.guild(ctx.guild).ban_baited_after.set(int(interval.total_seconds()))
        await ctx.tick()

    @adminset_baited.command(name="message")
    async def adminset_baited_message(self, ctx, *, message: Optional[str] = None):
        """
        Set message to be sent to the baited channel or DM to the baited user
        Pass with no message to see the current message.

        You can use these tags in your message:
        - {guild} - Name of the guild.
        - {member} - The member in question
        - {role} - The baited role.
        """
        if not message:
            curr = await self.config.guild(ctx.guild).baited_message()
            await ctx.send("**__Current message:__**")
            return await ctx.send(escape(curr, formatting=True))

        await self.config.guild(ctx.guild).baited_message.set(message)
        await ctx.tick()

    @adminset.command(name="user-count")
    async def adminset_user_count(self, ctx, *, channel: Union[discord.abc.GuildChannel, discord.Thread, str]):
        """
        Set channel to display guild user count.
        Pass "disable" to disable the user count channel
        """
        if isinstance(channel, str) and (channel.lower() == "disable" or channel.lower() == "off"):
            curr_channel = await self.config.guild(ctx.guild).user_count_channel()
            if not curr_channel:
                await ctx.send(error("No channel defined."), delete_after=30, reference=ctx.message)
                return

            await self.config.guild(ctx.guild).user_count_channel.set(None)
            await ctx.tick()
            return
        elif isinstance(channel, str):
            await ctx.send(error("Invalid channel input!"), delete_after=30, reference=ctx.message)
            return

        await self.config.guild(ctx.guild).user_count_channel.set(channel.id)
        await ctx.tick()

    @adminset.command(name="sus-channel")
    async def adminset_sus_user(
        self, ctx, *, channel: Union[discord.TextChannel, discord.VoiceChannel, discord.Thread, str]
    ):
        """
        Set channel to log new users.
        Pass "disable" to disable the user count channel
        Make sure to set threshold age for new account using [p]adminset sus-threshold
        """
        if isinstance(channel, str) and (channel.lower() == "disable" or channel.lower() == "off"):
            curr_channel = await self.config.guild(ctx.guild).sus_user_channel()
            if not curr_channel:
                await ctx.send(error("No channel defined."), delete_after=30, reference=ctx.message)
                return

            await self.config.guild(ctx.guild).sus_user_channel.set(None)
            await ctx.tick()
            return
        elif isinstance(channel, str):
            await ctx.send(error("Invalid channel input!"), delete_after=30, reference=ctx.message)
            return
        await self.config.guild(ctx.guild).sus_user_channel.set(channel.id)
        await ctx.tick()

    @adminset.command(name="sus-threshold")
    async def adminset_sus_threshold(self, ctx, *, threshold: str):
        """
        Set threshold for classifying users as new.

        Pass "disable" to disable

        Threshold should look like:
           5 minutes
           1 minute 30 seconds
           1 hour
           2 days
           30 days
           5h30m
           (etc)
        """
        if threshold.lower() == "disable":
            await self.config.guild(ctx.guild).sus_user_threshold.set(0)
            await ctx.tick()
            return

        interval = parse_timedelta(threshold)
        if not interval:
            await ctx.send(error("Invalid threshold!"), delete_after=30, reference=ctx.message)
            return

        await self.config.guild(ctx.guild).sus_user_threshold.set(int(interval.total_seconds()))
        await ctx.tick()

    @adminset.command(name="sus-kick-spammer")
    @checks.bot_has_permissions(kick_members=True)
    async def adminset_sus_kick_spammer(self, ctx, *, kick_spammers: bool):
        """
        Automatically kick users marked as suspected spammers by Discord on join.
        """
        await self.config.guild(ctx.guild).sus_user_kick_spammer.set(kick_spammers)
        await ctx.tick()

    @adminset.command(name="sus-kick")
    @checks.bot_has_permissions(kick_members=True)
    async def adminset_sus_kick(self, ctx, *, threshold: str):
        """
        Set threshold for kicking new accounts with DM

        Pass "disable" to disable

        Intervals look like:
           5 minutes
           1 minute 30 seconds
           1 hour
           2 days
           30 days
           5h30m
           (etc)
        """
        if threshold.lower() == "disable":
            await self.config.guild(ctx.guild).sus_user_kick_threshold.set(0)
            await ctx.tick()
            return

        interval = parse_timedelta(threshold)
        if not interval:
            await ctx.send(error("Invalid threshold!"), delete_after=30, reference=ctx.message)
            return

        await self.config.guild(ctx.guild).sus_user_kick_threshold.set(int(interval.total_seconds()))
        await ctx.tick()

    @adminset.command(name="ban-dm-msg")
    async def adminset_ban_dm_msg(self, ctx, *, msg: Optional[str] = None):
        """
        Set a message to be DMed to a user when they are banned using the bandm command

        Use {guild} to put the guild name in the message, {member} to put the member's name,
        and {reason} to put the reason

        Run empty to see current message
        """
        if not msg:
            curr = await self.config.guild(ctx.guild).ban_dm()
            await ctx.send("**__Current message:__**")
            return await ctx.send(escape(curr, formatting=True))

        await self.config.guild(ctx.guild).ban_dm.set(msg)
        await ctx.tick()

    async def note_menu(self, ctx, member: discord.Member, message: Optional[discord.Message] = None) -> list:
        color = await ctx.embed_color()

        # defines deleting a note for the user
        async def delete_note(
            ctx: commands.GuildContext,
            pages: list,
            controls: dict,
            message: discord.Message,
            page: int,
            timeout: float,
            emoji: str,
        ):
            async with self.config.member(member).notes() as notes:
                del notes[page]
            # resend menu, delete old menu with removed note
            if len(pages) <= 1:
                # no more notes, delete menu
                try:
                    await message.delete()
                except discord.NotFound:
                    pass
                return

            # remove reaction
            if ctx.channel.permissions_for(ctx.me).manage_messages:
                try:
                    await message.remove_reaction("\N{NO ENTRY SIGN}", ctx.author)
                except discord.HTTPException:
                    pass

            # call menu function again with updated menu
            await self.note_menu(ctx, member, message)

        notes = await self.config.member(member).notes()
        embeds = []
        for i, note in enumerate(notes):
            embed = discord.Embed(title=f"Notes for {member.display_name}", color=color)
            mod = ctx.guild.get_member(note["moderator"])
            mod = "Mod id({})".format(note["moderator"]) if not mod else mod.display_name
            embed = embed.set_author(name=mod)
            for page in pagify(note["note"], page_length=1000):
                embed = embed.add_field(name="Note", value=page)
            embed = embed.set_footer(text=f"Page {i+1} out of {len(notes)}")
            embeds.append(embed)

        controls = DEFAULT_CONTROLS.copy()
        controls.update({"\N{NO ENTRY SIGN}": delete_note})
        await menu(ctx, embeds, controls, message=message)

    @commands.hybrid_group()
    @commands.guild_only()
    @checks.mod()
    async def notes(self, ctx):
        """
        Manage notes for a user
        """
        pass

    @notes.command(name="add")
    @commands.guild_only()
    @checks.mod()
    async def notes_add(self, ctx, member: discord.Member, *, note: str):
        """
        Add a new note to a user.
        """
        async with self.config.member(member).notes() as notes:
            data = {"moderator": ctx.author.id, "note": note}
            notes.append(data)

        await ctx.tick()

    @notes.command(name="list")
    @commands.guild_only()
    @checks.mod()
    async def notes_list(self, ctx, member: discord.Member):
        """
        List notes for a user.

        Delete notes by clicking the no_entry_sign emoji
        """
        notes = await self.config.member(member).notes()
        if not notes:
            await ctx.send("That user has no notes on them.")
            return

        await self.note_menu(ctx, member)

    @commands.command(name="giverole")
    @checks.mod_or_permissions(manage_roles=True)
    @checks.bot_has_permissions(manage_roles=True)
    async def admin_addrole(self, ctx, user: discord.Member, *, role: discord.Role):
        """
        Add a role to a user.
        **Must be setup before hand with `[p]adminset`**
        Admins will bypass role checks.
        """
        author = ctx.author
        reason = f"Added by {author} (id: {author.id})"
        if mod.is_admin_or_superior(self.bot, author):
            try:
                await user.add_roles(role, reason=reason)
            except:
                await ctx.send(error("Adding role failed!"), delete_after=30, reference=ctx.message)
            return

        roles = {r.id for r in author.roles if r.name != "@everyone"}
        addable = await self.config.role(role).addable()
        roles &= set(addable)

        if roles:
            await user.add_roles(role, reason=reason)
        else:
            await ctx.send(
                error("You do not have the proper roles to add this role."), delete_after=30, reference=ctx.message
            )

    @commands.command(name="remrole")
    @checks.mod()
    @checks.bot_has_permissions(manage_roles=True)
    async def admin_remrole(self, ctx, user: discord.Member, *, role: discord.Role):
        """
        Removes a role to a user.
        **Must be setup before hand with `[p]adminset`**
        Admins will bypass role checks.
        """
        author = ctx.author
        reason = f"Removed by {author} (id: {author.id})"
        if mod.is_admin_or_superior(self.bot, author):
            try:
                await user.remove_roles(role, reason=reason)
            except:
                await ctx.send(error("Removing role failed!"), delete_after=30, reference=ctx.message)
            return

        roles = {r.id for r in author.roles if r.name != "@everyone"}
        addable = await self.config.role(role).addable()
        roles &= set(addable)

        if roles:
            await user.remove_roles(role, reason=reason)
        else:
            await ctx.send(
                error("You do not have the proper roles to remove this role."), delete_after=30, reference=ctx.message
            )

    @commands.command(name="channelfix")
    @checks.admin_or_permissions(administrator=True)
    @checks.bot_has_permissions(manage_channels=True, manage_roles=True)
    @commands.guild_only()
    async def channelfix(self, ctx: commands.Context, *channels: discord.abc.GuildChannel):
        """
        Fixes newly created channels not being displayed to current users when onboarding is setup
        You can supply a list of channel mentions to perform this action on multiple channels

        This only needs to be applied to newly created channels under categories that are not set as a default category (i.e channels that require a specific role for access)
        The fix works by removing access to the members then adding a role that grants access. Simply toggling the view permission a role a user already has will not work.
        Users who gain the role that grants access to the channel after channel creation will see the channel without explicitly selecting the channel in the `Channels & Roles` section

        New channels that are created are not immeditaly visible to users unless they have the `show all channels` setting enabled.
        This command fixes this by:
        1. Setting the channel so only those with the Administrator permission can access it
        2. Creates a temporary role
        3. Allow permissions to the channel for the temporary role
        4. Adds the temporary role to add members
        5. Restore previous access permissions to the channel
        6. Deletes the temporary role

        This is a slow process but should show the channel for everyone after completion.
        **WARNING** if the bot crashes, goes offline, or a Discord outage occurs during this process your permission structure may be left in a locked down state. You can simply remove the temp role created and revert permissions on the affect channels to restore previous permissions.
        """
        pred = MessagePredicate.yes_or_no(ctx)
        await ctx.send(
            warning(
                "This is a slow process if you have a large number of members, its better if you supply all channels you want to fix at once. Also note that if the bot crashes, or an error occurs, settings will not be cleaned up, you'll have to delete the temporary role and fix the permissions on the affect channel(s) manually. Continue?"
            ),
            delete_after=120,
        )
        try:
            await self.bot.wait_for("message", check=pred, timeout=60)
        except asyncio.TimeoutError:
            await ctx.send(info("Timed out, cancelled."), delete_after=30)
            return
        if not pred.result:
            await ctx.send(info("Cancelling command."), delete_after=30)
            return

        guild = ctx.guild
        temp_role = await guild.create_role(
            reason=f"Fixing channel display issues for {humanize_list([c.name for c in channels])}",
            name="Onboard Channel Fix",
        )

        channel_permissions: List[
            Dict[Union[discord.Role, discord.Member, discord.Object], discord.PermissionOverwrite]
        ] = [c.overwrites for c in channels]

        view_permission = discord.Permissions.none()
        view_permission.view_channel = True

        deny_overwrite = discord.PermissionOverwrite.from_pair(discord.Permissions.none(), view_permission)
        allow_overwrite = discord.PermissionOverwrite.from_pair(view_permission, discord.Permissions.none())

        for i, channel in enumerate(channels):
            overwrites = channel_permissions[i]
            overwrites = {k: deny_overwrite for k in overwrites.keys()}
            overwrites[temp_role] = allow_overwrite
            try:
                await channel.edit(overwrites=overwrites)
            except Exception as e:
                await ctx.reply(
                    error(
                        f"There was an error modifying {channel.mention}: {e}\n\nProcess has been cancelled and permissions have NOT been reverted for the channels {humanize_list([c.mention for c in channels])}"
                    )
                )
                return

        # now add the role to every user:
        start = time.perf_counter()
        total = len(guild.members)
        await ctx.send(info("Adding temporary role to all members."))
        update_message = info("Processing {} members... \nProgress: {}")
        update_m = await ctx.send(update_message.format(total, "N/A"))
        for i, member in enumerate(guild.members):
            try:
                await member.add_roles(temp_role)
            except Exception as e:
                await ctx.reply(warning(f"Failed to edit {member}: {e}"))
            finally:
                await asyncio.sleep(0.2)

            now = time.perf_counter()
            elapsed = now - start
            avg = elapsed / i if i > 0 else 0
            remaining = (total - i) * avg

            hrs, rem = divmod(remaining, 3600)
            mins, secs = divmod(rem, 60)
            eta_str = f"{int(hrs)}:{int(mins):02d}:{secs:04.1f}"
            progress_string = f"Iter {i+1}/{total} — elapsed {elapsed:.1f}s — ETA {eta_str}"

            try:
                update_m = await update_m.edit(content=update_message.format(total, progress_string))
            except:
                update_m = await ctx.send(update_message.format(total, progress_string))

        # revert back
        await ctx.reply(
            info("All members have been processed, reverting channel permissions and deleting the temporary role.")
        )

        for i, channel in enumerate(channels):
            overwrites = channel_permissions[i]
            try:
                await channel.edit(overwrites=overwrites)
            except Exception as e:
                await ctx.reply(error(f"There was an error reverting permissions for {channel.mention}: {e}"))

        # delete the role
        try:
            await temp_role.delete()
            await ctx.reply(
                info("Permissions reverted and temporary role deleted, I am finished with the fix!"),
                mention_author=False,
            )
        except Exception as e:
            await ctx.reply(warning(f"Failed to delete temporary role, please do so manually: {e}"))

    @commands.hybrid_command(name="pingable")
    @checks.mod()
    @checks.bot_has_permissions(manage_roles=True)
    @commands.guild_only()
    async def pingable(self, ctx, seconds: int, *, role: discord.Role):
        """
        Sets a role to be pingable for <seconds> amount of seconds.

        A time of 0 will just toggle the pingable status.

        Role should be a role name (case sensitive) or role ID.
        """
        if seconds < 0:
            await ctx.send(
                error("Please enter a time greater than or equal to 0."), delete_after=30, reference=ctx.message
            )
            return

        if seconds == 0:
            current_status = True is not role.mentionable
            await ctx.send("Setting pingable status to {} now.".format("ON" if current_status else "OFF"))
            await role.edit(mentionable=current_status)
        else:
            await ctx.send("Setting {} to be pingable for {} seconds.".format(role.name, seconds))
            updated_role = await role.edit(mentionable=True)
            await asyncio.sleep(seconds)
            await updated_role.edit(mentionable=False)

    @commands.hybrid_command(hidden=True)
    @checks.mod()
    @checks.bot_has_permissions(send_messages=True)
    @commands.guild_only()
    async def say(self, ctx, *, content: str):
        await ctx.send(escape(content, mass_mentions=True), allowed_mentions=discord.AllowedMentions.all())

    @commands.hybrid_command(hidden=True)
    @commands.guild_only()
    async def selfdm(self, ctx, *, content: str):
        try:
            await ctx.author.send(content, allowed_mentions=discord.AllowedMentions.all())
        except:
            await ctx.send(
                error(
                    "I couldn't send you the DM, make sure to turn on messages from server members! Here is the message:"
                )
            )
            await ctx.send(content)

    @commands.hybrid_command()
    @checks.mod()
    @commands.guild_only()
    async def edit(
        self,
        ctx,
        channel: Union[discord.TextChannel, discord.VoiceChannel, discord.Thread],
        message_id: str,
        *,
        msg: Optional[str] = None,
    ):
        """
        Edit any message sent by Aurelia.
        Needs message ID of message to edit, and the channel the message is in.

        Can also edit attachments by adding attachments to the command message
        """
        try:
            message = await channel.fetch_message(int(message_id))
        except:
            await ctx.send(error("Sorry, that message could not be found."), delete_after=30, reference=ctx.message)
            return

        attach = ctx.message.attachments

        files: Union[List[discord.File], None] = []
        if attach:
            for a in attach:
                files.append(
                    await a.to_file(
                        spoiler=a.is_spoiler(),
                    )
                )

        try:
            await message.edit(content=msg, attachments=files, allowed_mentions=discord.AllowedMentions.all())
            await ctx.tick()
        except:
            await ctx.send(
                error("Could not edit message, check my permissions."), delete_after=30, reference=ctx.message()
            )

    @commands.hybrid_command()
    @commands.guild_only()
    @checks.admin_or_permissions(administrator=True)
    @checks.bot_has_permissions(send_messages=True)
    async def send(
        self,
        ctx,
        channel: Union[discord.TextChannel, discord.VoiceChannel, discord.Thread],
        *,
        msg: Optional[str] = None,
    ):
        """
        Sends a message to a channel from Aurelia.

        Attach files to the command message to send attachments as well
        """
        attach = ctx.message.attachments

        files: Union[List[discord.File], None] = []
        if attach:
            for a in attach:
                files.append(
                    await a.to_file(
                        spoiler=a.is_spoiler(),
                    )
                )

        try:
            await channel.send(content=msg, files=files, allowed_mentions=discord.AllowedMentions.all())
            await ctx.tick()
        except:
            await ctx.send(error("Could not send message in that channel."), delete_after=30, reference=ctx.message)

    @commands.command()
    @commands.guild_only()
    @checks.admin_or_permissions(administrator=True)
    async def react(
        self,
        ctx,
        channel: Union[discord.TextChannel, discord.VoiceChannel, discord.Thread],
        message_id: int,
        emoji: Union[discord.Emoji, str],
    ):
        """
        Have the bot react to a message

        The bot must be able to access the emoji: i.e in the guild where the emoji is from
        """
        try:
            message = await channel.fetch_message(message_id)
        except:
            await ctx.send(error("Sorry, that message could not be found."), delete_after=30, reference=ctx.message)
            return

        try:
            await message.add_reaction(emoji)
            await ctx.tick()
        except discord.NotFound:
            await ctx.send(error(f"I could not find the emoji `{emoji}`"), delete_after=30, reference=ctx.message)
        except discord.Forbidden:
            await ctx.send(
                error(
                    "I do not have permissions to react to that message. I need read message history and add reactions if its a new reaction being added to the message."
                ),
                delete_after=30,
                reference=ctx.message,
            )
        except discord.HTTPException:
            # assume it couldnt find Emoji
            await ctx.send(error(f"I could not find the emoji `{emoji}`"), delete_after=30, reference=ctx.message)

    @commands.hybrid_command()
    @commands.guild_only()
    @checks.mod()
    async def get(
        self,
        ctx,
        channel: Union[discord.TextChannel, discord.VoiceChannel, discord.Thread],
        message_id: str,
    ):
        """
        Gets a message with it's formatting from Aurelia.

        Discord now allows you to right click a message and copy all of the text including formatting.
        """
        try:
            message = await channel.fetch_message(int(message_id))
        except:
            await ctx.send(error("Sorry, that message could not be found."), delete_after=30, reference=ctx.message)
            return

        if message.content == "":
            await ctx.send("(no message content)")
        else:
            await ctx.send("{}".format(escape(message.content, formatting=True, mass_mentions=True)))

    @commands.hybrid_command()
    @commands.guild_only()
    @checks.mod()
    async def getall(
        self, ctx, channel: Union[discord.TextChannel, discord.VoiceChannel, discord.Thread], message_id: str
    ):
        """
        Gets ALL messages with it's formatting from Aurelia after the specified message.

        For now, limit is 100 messages
        """
        messages = []
        try:
            message = await channel.fetch_message(int(message_id))
        except:
            await ctx.send(error("Sorry, that message could not be found."), delete_after=30, reference=ctx.message)
            return

        async for m in channel.history(limit=100, after=message.created_at):
            if m.author == ctx.guild.me:
                messages.append(m)

        for message in messages:
            if message.content == "":
                await ctx.send("(no message content)")
            else:
                await ctx.send("{}".format(escape(message.content, formatting=True, mass_mentions=True)))
            await asyncio.sleep(0.2)

    @commands.hybrid_command()
    @commands.guild_only()
    @checks.admin_or_permissions(ban_members=True)
    @checks.bot_has_permissions(ban_members=True)
    async def bandm(self, ctx, member: discord.Member, days: Optional[int] = 1, *, reason: Optional[str] = None):
        """
        Ban a member and have the bot DM them a message

        By default, deletes last day of messages
        """
        ban_command = self.bot.get_command("ban")

        if not ban_command:
            await ctx.send("The Mod cog is required for this command to work. Please load the Mod cog.")
            return

        dm_msg = await self.config.guild(ctx.guild).ban_dm()
        guild = ctx.guild.name
        member_name = member.name

        try:
            await member.send(dm_msg.format(guild=guild, member=member_name, reason=reason))
        except discord.HTTPException:
            await ctx.send(warning("I could not send the DM message."), delete_after=30)
            pass

        await ctx.invoke(ban_command, user=member, days=days, reason=reason)
        await ctx.tick()

    ### Listeners ###
    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        # clear baited status on role remove
        if before.roles == after.roles:
            return
        guild = before.guild
        baited_role = await self.config.guild(guild).baited_role()
        baited_role = guild.get_role(baited_role)
        if baited_role is None:
            return
        if baited_role in before.roles and baited_role not in after.roles:
            await self.config.member(after).baited.clear()

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if await self.bot.cog_disabled_in_guild(self, member.guild):
            return
        sus_threshold = await self.config.guild(member.guild).sus_user_threshold()
        sus_kick_threshold = await self.config.guild(member.guild).sus_user_kick_threshold()
        sus_kick_spammers = await self.config.guild(member.guild).sus_user_kick_spammer()
        if not (sus_threshold or sus_kick_threshold or sus_kick_spammers):
            return

        channel = await self.config.guild(member.guild).sus_user_channel()
        channel = member.guild.get_channel_or_thread(channel)
        if not (channel or sus_kick_threshold or sus_kick_spammers):
            return

        age = int((discord.utils.utcnow() - member.created_at).total_seconds())
        is_spammer = member.public_flags.spammer

        if channel:
            if age < sus_threshold:
                if (sus_kick_threshold and age < sus_kick_threshold) or (is_spammer and sus_kick_spammers):
                    data = discord.Embed(title="NEW ACCOUNT KICKED", colour=member.colour)
                else:
                    data = discord.Embed(title="NEW ACCOUNT DETECTED", colour=member.colour)

                data.add_field(name="Account Age", value=parse_seconds(age))
                data.add_field(name="Spammer", value=is_spammer)
                data.add_field(name="Threshold", value=parse_seconds(sus_threshold))

                data.set_footer(text=f"User ID:{member.id}")

                name = str(member)
                name = " ~ ".join((name, member.nick)) if member.nick else name

                avatar = member.display_avatar

                if avatar:
                    data.set_author(name=name, url=avatar.url)
                    data.set_thumbnail(url=avatar.url)
                else:
                    data.set_author(name=name)

                if sus_kick_threshold and age < sus_kick_threshold:
                    data.add_field(name="Kick Threshold", value=parse_seconds(sus_kick_threshold))
                    try:
                        await member.send(
                            f"Hello, you have been kicked from `{member.guild}` because your account is too new. Please try again later."
                        )
                    except:
                        pass
                    try:
                        await member.guild.kick(
                            member, reason=f"Account age too new, threshold: {parse_seconds(sus_kick_threshold)}"
                        )
                    except:
                        data.add_field(name=error("KICK FAILED!"), value="Please check bot permissions!")
                elif is_spammer and sus_kick_spammers:
                    try:
                        await member.send(
                            f"Hello, you have been kicked from `{member.guild}` because you are marked as a suspected spammer. Please resolve this issue before rejoining."
                        )
                    except:
                        pass
                    try:
                        await member.guild.kick(member, reason=f"Suspected Spammer")
                    except:
                        data.add_field(name=error("KICK FAILED!"), value="Please check bot permissions!")

                await channel.send(embed=data)
            elif (sus_kick_threshold and age < sus_kick_threshold) or (is_spammer and sus_kick_spammers):
                data = discord.Embed(title="NEW ACCOUNT KICKED", colour=member.colour)
                data.add_field(name="Account Age", value=parse_seconds(age))
                data.add_field(name="Spammer", value=is_spammer)
                data.add_field(name="Kick Threshold", value=parse_seconds(sus_kick_threshold))
                data.set_footer(text=f"User ID:{member.id}")

                name = str(member)
                name = " ~ ".join((name, member.nick)) if member.nick else name

                avatar = member.display_avatar

                if avatar:
                    data.set_author(name=name, url=avatar.url)
                    data.set_thumbnail(url=avatar.url)
                else:
                    data.set_author(name=name)

                if sus_kick_threshold and age < sus_kick_threshold:
                    data.add_field(name="Kick Threshold", value=parse_seconds(sus_kick_threshold))
                    try:
                        await member.send(
                            f"Hello, you have been kicked from `{member.guild}` because your account is too new. Please try again later."
                        )
                    except:
                        pass
                    try:
                        await member.guild.kick(
                            member, reason=f"Account age too new, threshold: {parse_seconds(sus_kick_threshold)}"
                        )
                    except:
                        data.add_field(name=error("KICK FAILED!"), value="Please check bot permissions!")
                elif is_spammer and sus_kick_spammers:
                    try:
                        await member.send(
                            f"Hello, you have been kicked from `{member.guild}` because you are marked as a suspected spammer. Please resolve this issue before rejoining."
                        )
                    except:
                        pass
                    try:
                        await member.guild.kick(member, reason=f"Suspected Spammer")
                    except:
                        data.add_field(name=error("KICK FAILED!"), value="Please check bot permissions!")

                await channel.send(embed=data)
        elif (sus_kick_threshold and age < sus_kick_threshold) or (is_spammer and sus_kick_spammers):
            if sus_kick_threshold and age < sus_kick_threshold:
                try:
                    await member.send(
                        f"Hello, you have been kicked from `{member.guild}` because your account is too new. Please try again later."
                    )
                except:
                    pass
                try:
                    await member.guild.kick(
                        member, reason=f"Account age too new, threshold: {parse_seconds(sus_kick_threshold)}"
                    )
                except:
                    pass
            elif is_spammer and sus_kick_spammers:
                try:
                    await member.send(
                        f"Hello, you have been kicked from `{member.guild}` because you are marked as a suspected spammer. Please resolve this issue before rejoining."
                    )
                except:
                    pass
                try:
                    await member.guild.kick(member, reason=f"Suspected Spammer")
                except:
                    pass
