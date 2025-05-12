# redbot/discord
from redbot.core.utils.chat_formatting import *
from redbot.core import Config, checks, commands
from redbot.core.commands.converter import parse_timedelta
from redbot.core.utils.predicates import MessagePredicate
import discord
import emoji

import asyncio, bisect
from datetime import timedelta, timezone, datetime
from typing import Union, Optional, Literal, Tuple
from random import choice

NO_NICKNAME = "#" * 40
SHUT_DEFAULT_MSGs = [
    "SHUT UP {target}!!!",
    "cease {target}.",
    "ₛₕᵤₜ👌",
    "{author} slams a bowling ball over {target}'s mouth for a hot second!",
    "{author} stuffs {target} in a soundproof closet",
    "{author} zips up {target}'s lips with flex seal.",
    "{author} gags {target} with a dirty sock.",
]


class MayhemMaker(commands.Cog):
    """
    Allow users to cause (controlled) mayhem in a guild!
    """

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=574243463248323838, force_registration=True)

        default_guild = {
            "allowed_roles": [],
            "allowed_users": [],
            "disallowed_users": [],
            "current_changes": {
                "name": {},
                "role": {},
                "shut": {},
                "reaction": {},
            },
            "max_duration": 900,
            "max_actions": 1,  # max number of mayhem actions a user can take at once (not implemented)
            "mayhem_roles": [],
            "usage_cooldowns": {  # cooldowns for usage of each command
                "name": 60,
                "shut": 60,
                "role": 60,
                "reaction": 60,
            },
            "applied_cooldowns": {  # cooldowns for application on a specific user for each command
                "name": 300,
                "shut": 900,
                "role": 300,
                "reaction": 300,
            },
            "level_integration_usage_cooldowns": {
                "name": {},
                "shut": {},
                "role": {},
                "reaction": {},
            },
            "level_integration_applied_cooldowns": {
                "name": {},
                "shut": {},
                "role": {},
                "reaction": {},
            },
            "level_integration_max_duration": {},
            "shut_messages": SHUT_DEFAULT_MSGs,
        }
        default_member = {
            "last_used": {
                "name": 0,
                "shut": 0,
                "role": 0,
                "reaction": 0,
            },
            "last_applied": {
                "name": 0,
                "shut": 0,
                "role": 0,
                "reaction": 0,
            },
        }
        self.config.register_guild(**default_guild)
        self.config.register_member(**default_member)

        self.actions = ["name", "role", "shut", "reaction"]
        self.level_cog = None
        self.task = asyncio.create_task(self.loop())

    def cog_unload(self):
        if self.task is not None:
            self.task.cancel()

    async def loop(self):
        await self.bot.wait_until_ready()
        self.level_cog = self.bot.get_cog("LevelUp")
        while True:
            try:
                await self.loop_task()
            except asyncio.CancelledError:
                break
            except Exception as e:
                import traceback

                traceback.print_exc()
                print(f"[MayhemMaker] Internal loop crashed, restarting in 10s. {e}")
                await asyncio.sleep(10)

    async def loop_task(self):
        force_check = True
        while True:
            await self.update_mayhem(force_check=force_check)
            await asyncio.sleep(30)
            force_check = False

    async def update_mayhem(self, force_check: bool = False):
        for guild in self.bot.guilds:
            to_remove = {k: [] for k in self.actions}
            to_change = {k: {} for k in self.actions}
            for action, action_data in (await self.config.guild(guild).current_changes()).items():
                now = discord.utils.utcnow()
                for member_id, data in action_data.items():
                    end_time = discord.utils.utcnow().fromtimestamp(data["end_time"]).astimezone(timezone.utc)
                    member = guild.get_member(int(member_id))

                    if member is None:
                        to_remove[action].append(member_id)
                        continue

                    if now > end_time:
                        # name change is past due
                        to_change[action][member] = data
                        to_remove[action].append(member_id)
                    elif force_check:
                        if action == "name" and member.display_name != data["new_nick"]:
                            await self.apply_action(member, action, data["new_nick"])
                        elif action == "role":
                            role = guild.get_role(data["role"])
                            if role and role not in member.roles:
                                await self.apply_action(member, action, role)
                            else:  # couldnt find role
                                pass

            # print("=" * 25)
            # print(guild.name)
            # print("remove", to_remove)
            # print("change", to_change)
            async with self.config.guild(guild).current_changes() as current_changes:
                # print("current", current_changes)
                for action, remove in to_remove.items():
                    for mid in remove:
                        del current_changes[action][mid]

            # rollback mayhem changes
            for action, action_data in to_change.items():
                for member, data in action_data.items():
                    if action == "name":
                        if data["old_nick"] == NO_NICKNAME:
                            await self.apply_action(member, action, None)
                        else:
                            await self.apply_action(member, action, data["old_nick"])
                    elif action == "role":
                        role = guild.get_role(data["role"])
                        if role:
                            await self.remove_role(member, role)
                        else:  # roll doesnt exist or some other issue, just pass
                            pass

    async def check_can_change(self, member: discord.Member):
        roles = await self.config.guild(member.guild).allowed_roles()
        members = await self.config.guild(member.guild).allowed_users()
        disallow_members = await self.config.guild(member.guild).disallowed_users()

        if member.id in disallow_members:
            return False

        for role in member.roles:
            if role.id in roles:
                return True

        if member.id in members:
            return True

        return False

    async def check_cooldown(
        self,
        member: discord.Member,
        target: discord.Member,
        action: Literal["name", "shut", "role", "reaction"],
    ) -> Tuple[bool, str, datetime]:
        guild = member.guild
        now = discord.utils.utcnow()
        usage_cooldown = (await self.config.guild(guild).usage_cooldowns())[action]
        applied_cooldown = (await self.config.guild(guild).applied_cooldowns())[action]

        member_last_used = (await self.config.member(member).last_used())[action]
        target_last_used = (await self.config.member(target).last_applied())[action]
        member_last_used = now.fromtimestamp(member_last_used).astimezone(timezone.utc)
        target_last_used = now.fromtimestamp(target_last_used).astimezone(timezone.utc)

        if self.level_cog is not None:
            member_level: int = await self.level_cog.get_level(member)
            target_level: int = await self.level_cog.get_level(target)
            # check level cooldowns, default to global cooldowns otherwise
            lvl_usage_cooldowns = (await self.config.guild(guild).level_integration_usage_cooldowns())[action]
            lvls = sorted(list(lvl_usage_cooldowns.keys()))
            member_usage_cooldown = 0
            if lvl_usage_cooldowns:
                member_usage_cooldown = bisect.bisect_left(lvls, str(member_level))
                if member_usage_cooldown != len(
                    lvl_usage_cooldowns
                ):  # if false then member has a higher level then configured
                    member_usage_cooldown = lvl_usage_cooldowns[lvls[member_usage_cooldown]]

            lvl_applied_cooldowns = (await self.config.guild(guild).level_integration_applied_cooldowns())[action]
            lvls = sorted(list(lvl_applied_cooldowns.keys()))
            target_applied_cooldown = 0
            if lvl_applied_cooldowns:
                target_applied_cooldown = bisect.bisect_left(lvls, str(target_level))
                if target_applied_cooldown != len(lvl_applied_cooldowns):
                    target_applied_cooldown = lvl_applied_cooldowns[lvls[target_applied_cooldown]]

            if member_usage_cooldown:
                usage_cooldown = member_usage_cooldown
            if target_applied_cooldown:
                usage_cooldown = target_applied_cooldown

        usage_cooldown = timedelta(seconds=usage_cooldown)
        applied_cooldown = timedelta(seconds=applied_cooldown)

        # check last usage of the action from member
        if now - member_last_used < usage_cooldown:
            return True, "usage", now + (usage_cooldown - (now - member_last_used))
        # check last applied of the action onto target
        if now - target_last_used < applied_cooldown:
            return True, "applied", now + (applied_cooldown - (now - target_last_used))

        return False, "", now

    async def apply_mayhem(
        self,
        ctx: commands.Context,
        member: discord.Member,
        action: Literal["name", "shut", "role", "reaction"],
        duration: Optional[str] = None,
        mayhem_item: Optional[Union[discord.Role, str, discord.Emoji]] = None,
    ):
        """
        Applies a mayhem action to the user

        Args:
            author (discord.Member): member requesting the action
            member (discord.Member): member to apply action to
            action (str): The action to apply
            mayhem_item (Union[discord.Role, str]): The item to add/change for the member
            duration (str): How long to apply the action for

        Returns:
            bool: whether the action was successful or not
        """
        if not (await self.check_can_change(member)):
            await ctx.send(error("That user cannot suffer from mayhem!"), delete_after=30, reference=ctx.message)
            return

        now = discord.utils.utcnow()
        on_cooldown, cooldown_type, next_usage = await self.check_cooldown(ctx.author, member, action)
        if on_cooldown:
            if cooldown_type == "usage":
                await ctx.send(
                    warning(f"You can use {action} again <t:{int(next_usage.timestamp())}:R>."),
                    delete_after=(next_usage - now).total_seconds(),
                    reference=ctx.message,
                )
                return
            elif cooldown_type == "applied":
                await ctx.send(
                    warning(
                        f"`{member.display_name}` can have {action} used against them <t:{int(next_usage.timestamp())}:R>."
                    ),
                    delete_after=(next_usage - now).total_seconds(),
                    reference=ctx.message,
                )
                return

        max_duration = await self.config.guild(member.guild).max_duration()
        if self.level_cog is not None:
            lvl_maxduration = await self.config.guild(member.guild).level_integration_max_duration()
            lvls = sorted(list(lvl_maxduration.keys()))
            member_level = await self.level_cog.get_level(ctx.author)
            if lvl_maxduration:
                idx = bisect.bisect_left(lvls, str(member_level))
                if idx != len(lvl_maxduration):
                    max_duration = lvl_maxduration[lvls[idx]]

        if action != "shut":
            time = parse_timedelta(duration)
            if time is None:
                await ctx.send(error("Invalid time duration!"), delete_after=30, reference=ctx.message)
                return
            if time > timedelta(seconds=max_duration):
                await ctx.send(
                    error(f"Duration too long, max duration is {humanize_timedelta(seconds=max_duration)}."),
                    delete_after=30,
                    reference=ctx.message,
                )
                return
        else:
            time = timedelta(seconds=60)

        current = await self.config.guild(ctx.guild).current_changes()
        current_action = current[action]
        if str(member.id) in current_action:
            end_time = current_action[str(member.id)]["end_time"]
            await ctx.send(
                error(
                    f"`{member.display_name}` is already suffering from that action! Please wait until <t:{end_time}> to get them again."
                ),
                reference=ctx.message,
            )
            return

        data = {
            "action": action,
            "end_time": int((now + time).astimezone(now.astimezone().tzinfo).timestamp()),
            "author": ctx.author.id,
        }

        if action == "name" and isinstance(mayhem_item, str):
            if len(mayhem_item) > 32 or len(mayhem_item) < 2:
                await ctx.send(
                    error("Nickname must be 2 to 32 characters in length!"), delete_after=30, reference=ctx.message
                )
                return

            data["old_nick"] = member.nick if member.nick is not None else NO_NICKNAME
            data["new_nick"] = mayhem_item

            result = await self.apply_action(member, action, mayhem_item)
            if not result:
                await ctx.send(
                    error(
                        f"It seem's I couldn't change `{member.display_name}'s` nickname, please contact a staff member to check my role hierarchy."
                    ),
                    delete_after=30,
                    reference=ctx.message,
                )
                return

            async with self.config.guild(ctx.guild).current_changes() as current_changes:
                current_changes[action][str(member.id)] = data

            await ctx.send(
                f"`{member.display_name}'s` nickname changed to `{mayhem_item}` until <t:{data['end_time']}>."
            )

            try:
                await member.send(
                    info(
                        f"**Name changed in {ctx.guild}**\n\nYour name was changed to `{mayhem_item}` by {ctx.author.mention} until <t:{data['end_time']}>."
                    )
                )
            except:
                pass
        elif action == "role" and isinstance(mayhem_item, discord.Role):
            data["role"] = mayhem_item.id
            result = await self.apply_action(member, action, mayhem_item)
            if not result:
                await ctx.send(
                    error(
                        f"It seem's I couldn't add {mayhem_item.name} to`{member.display_name}` , please contact a staff member to check my role hierarchy."
                    ),
                    delete_after=30,
                    reference=ctx.message,
                )
                return

            async with self.config.guild(ctx.guild).current_changes() as current_changes:
                current_changes[action][str(member.id)] = data

            await ctx.send(f"`{mayhem_item.name}` added to `{member.display_name}`  until <t:{data['end_time']}>.")

            try:
                await member.send(
                    info(
                        f"**Role added in {ctx.guild}**\n\n`{mayhem_item.name}` has been added to you by {ctx.author.mention} until <t:{data['end_time']}>."
                    )
                )
            except:
                pass
        elif action == "shut":
            result = await self.apply_action(member, action, mayhem_item)
            if not result:
                await ctx.send(
                    error(
                        f"It seem's I couldn't timeout `{member.display_name}`, please contact a staff member to check my role hierarchy."
                    ),
                    delete_after=30,
                    reference=ctx.message,
                )
                return
            # tell them to SHUT IT
            msgs = await self.config.guild(ctx.guild).shut_messages()
            msg = choice(msgs)
            await ctx.send(msg.format(author=ctx.author.mention, target=member.mention))

            # success!
            async with self.config.guild(ctx.guild).current_changes() as current_changes:
                current_changes[action][str(member.id)] = data
        elif action == "reaction":
            data["emoji"] = mayhem_item.id if isinstance(mayhem_item, discord.Emoji) else mayhem_item
            await ctx.tick()
            async with self.config.guild(ctx.guild).current_changes() as current_changes:
                current_changes[action][str(member.id)] = data

        # update cooldowns
        async with self.config.member(ctx.author).last_used() as last_used:
            last_used[action] = now.timestamp()

        async with self.config.member(member).last_applied() as last_applied:
            last_applied[action] = now.timestamp()

    @staticmethod
    async def remove_role(member: discord.Member, role: discord.Role):
        try:
            await member.remove_roles(role, reason="Mayhem role expired")
            return True
        except discord.Forbidden:
            return False
        except discord.HTTPException:
            return False

    @staticmethod
    async def apply_action(
        member: discord.Member,
        action: Literal["name", "shut", "role", "reaction"],
        mayhem_item: Optional[Union[discord.Role, str]],
    ):
        if action == "name" and (isinstance(mayhem_item, str) or mayhem_item == None):
            try:
                await member.edit(nick=mayhem_item)
                return True
            except discord.Forbidden:
                return False
            except discord.HTTPException:
                return False
        elif action == "shut":
            try:
                await member.timeout(timedelta(seconds=60), reason="Mayhem target of shut command")
                return True
            except discord.Forbidden:
                return False
            except discord.HTTPException:
                return False
        elif action == "role" and isinstance(mayhem_item, discord.Role):
            try:
                await member.add_roles(mayhem_item, reason="Mayhem target of role command")
                return True
            except discord.Forbidden:
                return False
            except discord.HTTPException:
                return False

    # @commands.command()
    # async def test(self, ctx):
    #    await self.update_namechanges()

    @commands.hybrid_command(name="name")
    @commands.guild_only()
    @checks.bot_has_permissions(manage_nicknames=True)
    @commands.cooldown(1, 5, commands.BucketType.member)
    async def namechange(self, ctx, member: discord.Member, interval: str, *, new_name: str):
        """
        Time should be a combination of s, m, h, d, w in this format:
            `5m30s` = 5 minutes 30 seconds
            `1w3d` = 1 week 3 days
            `10m` = 10 minutes
            etc...
        """
        await self.apply_mayhem(ctx, member, "name", interval, new_name)

    @commands.hybrid_command(name="shut")
    @commands.guild_only()
    @checks.bot_has_permissions(moderate_members=True)
    @commands.cooldown(1, 5, commands.BucketType.member)
    async def shut(self, ctx: commands.Context, member: discord.Member):
        """
        Shut up someone for 60 seconds
        """
        await self.apply_mayhem(ctx, member, "shut")

    @commands.hybrid_command(name="role")
    @commands.guild_only()
    @checks.bot_has_permissions(manage_roles=True)
    @commands.cooldown(1, 5, commands.BucketType.member)
    async def role(
        self,
        ctx: commands.Context,
        member: Optional[discord.Member] = None,
        interval: Optional[str] = None,
        *,
        role: Optional[discord.Role] = None,
    ):
        """
        Add a role to someone, run with no arguments to get the roles you can add to someone.
        """
        current_roles = await self.config.guild(ctx.guild).mayhem_roles()
        roles = [ctx.guild.get_role(rid) for rid in current_roles]
        roles = [r for r in roles if r is not None]
        if not member:
            if not roles:
                await ctx.send(info("No roles set for mayhem!"), delete_after=30)
                return
            else:
                await ctx.send(info(f"Current Roles you can add: {humanize_list([inline(r.name) for r in roles])}"))
                return
        if role not in roles:
            await ctx.send(error(f"I cannot add that role to {member.display_name}!"))
            return
        await self.apply_mayhem(ctx, member, "role", interval, role)

    @commands.command(name="autoreact")
    @commands.guild_only()
    @checks.bot_has_permissions(read_message_history=True, add_reactions=True)
    @commands.cooldown(1, 5, commands.BucketType.member)
    async def react(
        self,
        ctx: commands.Context,
        member: discord.Member,
        interval: str,
        *,
        react_emoji: Union[discord.Emoji, str],
    ):
        """
        Set an emoji that I will react to every message against member
        """
        if isinstance(react_emoji, str) and emoji.demojize(react_emoji) == react_emoji:
            await ctx.send(error(f"Unknown emoji {react_emoji}!"), delete_after=30, reference=ctx.message)
            return
        await self.apply_mayhem(ctx, member, "reaction", interval, react_emoji)

    @commands.hybrid_command(name="optin")
    @commands.guild_only()
    async def mayhem_optin(self, ctx: commands.Context):
        """
        Opt in or out of mayhem being forced against you

        Run the command again to toggle your opt in status
        """
        member = ctx.author
        async with self.config.guild(ctx.guild).allowed_users() as allowed_users:
            if member.id not in allowed_users:
                allowed_users.append(member.id)
                await ctx.tick()
            else:
                allowed_users.remove(member.id)
                await ctx.tick()
                await ctx.send(
                    info("You have opted out of being the victim of mayhem."), delete_after=30, reference=ctx.message
                )

    @commands.group(name="mayhemset")
    @checks.admin()
    @commands.guild_only()
    async def mayhemset(self, ctx):
        """
        Manage your mayhem
        """
        pass

    @mayhemset.group(name="shutmessages")
    async def mayhemset_shutmessages(self, ctx: commands.Context):
        """
        Manage the messages sent on shut command
        """
        pass

    @mayhemset_shutmessages.command(name="add")
    async def mayhemset_shutmessages_add(self, ctx: commands.Context, *, msg: str):
        """
        Add a new shut command message

        You can use `{author}` to represent the user who initaited the command and `{target}` to represent the target of the command in your message
        """
        async with self.config.guild(ctx.guild).shut_messages() as shut_messages:
            if msg not in shut_messages:
                shut_messages.append(msg)
        await ctx.tick()

    @mayhemset_shutmessages.command(name="del")
    async def mayhemset_shutmessages_del(self, ctx: commands.Context):
        """
        Delete a shut command message
        """
        async with self.config.guild(ctx.guild).shut_messages() as shut_messages:
            msg = "### Select the number you want to delete:\n"
            messages = msg + box("\n".join([f"{i+1}. {m}" for i, m in enumerate(shut_messages)]))
            for page in pagify(messages):
                await ctx.send(page)

            pred = MessagePredicate.positive(ctx)
            try:
                await self.bot.wait_for("message", check=pred, timeout=120)
            except asyncio.TimeoutError:
                await ctx.send(warning("Took too long! Cancelling..."))
                return
            idx = int(pred.result) - 1
            if idx > len(shut_messages):
                await ctx.send(warning("Invalid number! Cancelling..."))
                return
            msg = shut_messages.pop(idx)
            await ctx.send(info(f"Deleted shut message `{idx + 1}. {msg}`"))

    @mayhemset_shutmessages.command(name="list")
    async def mayhemset_shutmessages_list(self, ctx: commands.Context):
        """
        List all shut messages.
        """
        async with self.config.guild(ctx.guild).shut_messages() as shut_messages:
            msg = "### Shut messages:\n"
            messages = msg + box("\n".join([f"{i+1}. {m}" for i, m in enumerate(shut_messages)]))
            for page in pagify(messages):
                await ctx.send(page)

    @mayhemset.command(name="list")
    async def mayhemset_list(self, ctx: commands.Context):
        """
        List all users currently affected by mayhem
        """
        current = await self.config.guild(ctx.guild).current_changes()
        msg = ""
        for action in self.actions:
            msg += f"# {action.capitalize()}\n"
            for member_id in current[action].keys():
                member = ctx.guild.get_member(int(member_id))
                if member:
                    msg += f"- {member.mention}\n"
            if len(current[action]) == 0:
                msg += "- None\n"
        await ctx.send_interactive(pagify(msg))

    @mayhemset.command(name="maxduration")
    async def mayhemset_max_duration(self, ctx: commands.Context, max_duration: int):
        """
        Set max time a mayhem action can be applied for

        If using levelup integration:
        This will be the default duration if no level is specified for the max duration
        """
        await self.config.guild(ctx.guild).max_duration.set(max_duration)
        await ctx.tick()

    @mayhemset.group(name="levelup")
    async def mayhemset_levelup(self, ctx: commands.Context):
        """
        Manage levelup integration settings
        """
        pass

    @mayhemset_levelup.command(name="list")
    async def mayhemset_levelup_list(self, ctx: commands.Context):
        """
        List LevelUp integration settings
        """
        usage_cooldowns = await self.config.guild(ctx.guild).level_integration_usage_cooldowns()
        applied_cooldowns = await self.config.guild(ctx.guild).level_integration_applied_cooldowns()
        max_duration = await self.config.guild(ctx.guild).level_integration_max_duration()

        msg = "# Max Duration:\n"
        if max_duration:
            for level, maxduration in max_duration.items():
                msg += f"   - Level `{level}`: `{humanize_timedelta(seconds=maxduration)}`\n"
        else:
            msg += "   - No levels set\n"

        msg += "# Cooldowns:\n## Usage Cooldowns:\n"
        for action, cooldowns in usage_cooldowns.items():
            msg += f"### {action}:\n"
            if cooldowns:
                for level, cooldown in cooldowns.items():
                    msg += f"   - Level `{level}`: {humanize_timedelta(seconds=cooldown)}\n"
            else:
                msg += "   - No levels set\n"

        msg += "## Applied Cooldowns:\n"
        for action, cooldowns in applied_cooldowns.items():
            msg += f"### {action}:\n"
            if cooldowns:
                for level, cooldown in cooldowns.items():
                    msg += f"   - Level `{level}`: {humanize_timedelta(seconds=cooldown)}\n"
            else:
                msg += "   - No levels set\n"

        for page in pagify(msg):
            await ctx.send(page)

    @mayhemset_levelup.group(name="cooldown", aliases=["cooldowns"])
    async def mayhemset_levelup_cooldown(self, ctx: commands.Context):
        """
        Manage levelup integration cooldowns
        """
        pass

    @mayhemset_levelup_cooldown.command(name="usage")
    async def mayhemset_levelup_cooldown_usage(
        self,
        ctx: commands.Context,
        action: Literal["name", "shut", "role", "reaction"],
        level: int,
        cooldown: int,
    ):
        """
        Set how long a user must wait before using a mayhem action again based on their level.

        Set cooldown to 0 to remove cooldown for that level.

        Levels added will act as as a ceiling, meaning that levels below the specified `level` can use mayhem commands after the `cooldown` set for that level.
        Example:
        [p]mayhemset levelup cooldown usage name 5 120
        [p]mayhemset levelup cooldown usage name 10 300

        Users level [0, 5] will have a cooldown of 120 seconds for name (including level 5)
        Users level (5, 10] will have a cooldown of 300 seconds for name (including level 10)
        Users above level 10 will use the default cooldown set by [p]mayhemset cooldown usage
        """
        if not self.level_cog:
            return await ctx.reply(
                error(
                    "LevelUp cog not loaded, please contact the bot owner to load the cog. If you just loaded the LevelUp cog reload MayhemMaker."
                ),
                mention_author=False,
            )
        async with self.config.guild(ctx.guild).level_integration_usage_cooldowns() as lvl_usage_cooldowns:
            if cooldown == 0:
                try:
                    del lvl_usage_cooldowns[action][level]
                except:
                    pass
            else:
                lvl_usage_cooldowns[action][level] = cooldown
            await ctx.tick()

    @mayhemset_levelup_cooldown.command(name="apply")
    async def mayhemset_levelup_cooldown_apply(
        self,
        ctx: commands.Context,
        action: Literal["name", "shut", "role", "reaction"],
        level: int,
        cooldown: int,
    ):
        """
        Set how long a user is protected from a mayhem command after being attacked based on their level.

        Set cooldown to 0 to remove cooldown for that level.

        Levels added will act as as a ceiling, meaning that levels below the specified `level` will have `cooldown` applied to them before that mayhem action can be used against them again
        Example:
        [p]mayhemset levelup cooldown apply name 5 300
        [p]mayhemset levelup cooldown apply name 10 900

        Users level [0, 5] will have a 300 second protection against name.
        Users level (5, 10] will have a 900 second protection against name.
        Users above level 10 will have the default cooldownset by [p]mayhemset cooldown apply protection time
        """
        if not self.level_cog:
            return await ctx.reply(
                error(
                    "LevelUp cog not loaded, please contact the bot owner to load the cog. If you just loaded the LevelUp cog reload MayhemMaker."
                ),
                mention_author=False,
            )
        async with self.config.guild(ctx.guild).level_integration_applied_cooldowns() as lvl_apply_cooldowns:
            if cooldown == 0:
                try:
                    del lvl_apply_cooldowns[action][level]
                except:
                    pass
            else:
                lvl_apply_cooldowns[action][level] = cooldown
            await ctx.tick()

    @mayhemset_levelup.command(name="maxduration")
    async def mayhemset_levelup_maxduration(
        self,
        ctx: commands.Context,
        level: int,
        maxduration: int,
    ):
        """
        Add a cooldown for a specific level

        Set maxduration to 0 to remove the cooldown for the specified level

        Levels added will act as as a ceiling, meaning that levels below the specified `level` can use mayhem commands with the `maxduration` set for that level.
        Example:
        [p]mayhemset levelup maxduration name 5 120
        [p]mayhemset levelup maxduration name 10 300

        Users level [0, 5] can set a max duration of 120 seconds for name (including level 5)
        Users level (5, 10] can set a max duration of 300 seconds for name (including level 10)
        Users above level 10 will use the default max duration set by [p]mayhemset maxduration
        """
        if not self.level_cog:
            return await ctx.reply(
                error(
                    "LevelUp cog not loaded, please contact the bot owner to load the cog. If you just loaded the LevelUp cog reload MayhemMaker."
                ),
                mention_author=False,
            )
        async with self.config.guild(ctx.guild).level_integration_max_duration() as lvl_maxduration:
            if maxduration == 0:
                try:
                    del lvl_maxduration[level]
                except:
                    pass
            else:
                lvl_maxduration[level] = maxduration
            await ctx.tick()

    @mayhemset.group(name="cooldown", aliases=["cooldowns"])
    async def mayhemset_cooldown(self, ctx):
        """
        Manage mayhem cooldowns.

        If using levelup integration:
        This will manage the default cooldown duration if no level is specified for a cooldown
        """
        pass

    @mayhemset_cooldown.command(name="usage")
    async def mayhemset_cooldown_usage(
        self,
        ctx: commands.Context,
        action: Literal["name", "shut", "role", "reaction"],
        cooldown: str,
    ):
        """
        Set how long a user must wait before using a mayhem action again.

        Cooldown can be any time interval:
        - 60s
        - 5 minutes
        - 1 hour
        etc.
        """
        new_cooldown = parse_timedelta(cooldown)
        if not new_cooldown:
            await ctx.send(error("Invalid cooldown interval!"), delete_after=30, reference=ctx.message)
            return
        async with self.config.guild(ctx.guild).usage_cooldowns() as usage_cooldowns:
            usage_cooldowns[action] = new_cooldown.total_seconds()
            await ctx.tick()

    @mayhemset_cooldown.command(name="apply")
    async def mayhemset_cooldown_apply(
        self,
        ctx: commands.Context,
        action: Literal["name", "shut", "role", "reaction"],
        cooldown: str,
    ):
        """
        Set how long a user is protected from a mayhem command after being attacked.

        Cooldown can be any time interval:
        - 60s
        - 5 minutes
        - 1 hour
        etc.
        """
        new_cooldown = parse_timedelta(cooldown)
        if not new_cooldown:
            await ctx.send(error("Invalid cooldown interval!"), delete_after=30, reference=ctx.message)
            return
        async with self.config.guild(ctx.guild).applied_cooldowns() as applied_cooldowns:
            applied_cooldowns[action] = new_cooldown.total_seconds()
            await ctx.tick()

    @mayhemset_cooldown.command(name="list")
    async def mayhemset_cooldown_list(
        self,
        ctx: commands.Context,
    ):
        """
        List all default cooldowns.
        """
        usage_cooldowns = await self.config.guild(ctx.guild).usage_cooldowns()
        applied_cooldowns = await self.config.guild(ctx.guild).applied_cooldowns()
        max_duration = await self.config.guild(ctx.guild).max_duration()

        msg = f" # Usage:\n- name: `{humanize_timedelta(seconds=usage_cooldowns['name'])}`\n- shut: `{humanize_timedelta(seconds=usage_cooldowns['shut'])}`\n- role: `{humanize_timedelta(seconds=usage_cooldowns['role'])}`\n- reaction: `{humanize_timedelta(seconds=usage_cooldowns['reaction'])}`\n# Applied:\n- name: `{humanize_timedelta(seconds=applied_cooldowns['name'])}`\n- shut: `{humanize_timedelta(seconds=applied_cooldowns['shut'])}`\n- role: `{humanize_timedelta(seconds=applied_cooldowns['role'])}`\n- reaction: `{humanize_timedelta(seconds=applied_cooldowns['reaction'])}`\n### Max Mayhem Duration: `{humanize_timedelta(seconds=max_duration)}`"
        await ctx.send(msg)

    @mayhemset.group(name="roles")
    async def mayhemset_roles(self, ctx):
        """
        Set the roles a user must have for getting mayhemed
        """
        pass

    @mayhemset_roles.command(name="add")
    async def mayhemset_roles_add(self, ctx, *, role: discord.Role):
        """
        Add a role for name changing
        """
        async with self.config.guild(ctx.guild).allowed_roles() as allowed_roles:
            if role.id not in allowed_roles:
                allowed_roles.append(role.id)
                await ctx.tick()
            else:
                await ctx.send(error(f"`{role}` is already added!"), delete_after=30)

    @mayhemset_roles.command(name="del")
    async def mayhemsetroles_del(self, ctx, *, role: discord.Role):
        """
        Remove a role from name changing
        """
        async with self.config.guild(ctx.guild).allowed_roles() as allowed_roles:
            if role.id in allowed_roles:
                allowed_roles.remove(role.id)
                await ctx.tick()
            else:
                await ctx.send(error(f"`{role}` is not in the allowed list!"), delete_after=30)

    @mayhemset_roles.command(name="list")
    async def mayhemset_roles_list(self, ctx):
        """
        View all roles that allow name changing.
        """
        roles = await self.config.guild(ctx.guild).allowed_roles()
        roles = [ctx.guild.get_role(r) for r in roles]

        msg = [f"{r.mention}\n" for r in roles if r is not None]
        msg = "Current roles:\n" + "".join(msg)

        for page in pagify(msg, page_length=1800, shorten_by=22):
            await ctx.send(page)

    @mayhemset.group(name="mayhemroles")
    async def mayhemset_mayhem_roles(self, ctx):
        """
        Set roles members can add to others
        """
        pass

    @mayhemset_mayhem_roles.command(name="add")
    async def mayhemset_mayhem_roles_add(self, ctx, *, role: discord.Role):
        """
        Add a role for name changing
        """
        async with self.config.guild(ctx.guild).mayhem_roles() as mayhem_roles:
            if role.id not in mayhem_roles:
                mayhem_roles.append(role.id)
                await ctx.tick()
            else:
                await ctx.send(error(f"`{role}` is already added!"), delete_after=30)

    @mayhemset_mayhem_roles.command(name="del")
    async def mayhemset_mayhem_roles_del(self, ctx, *, role: discord.Role):
        """
        Remove a role from name changing
        """
        async with self.config.guild(ctx.guild).mayhem_roles() as mayhem_roles:
            if role.id in mayhem_roles:
                mayhem_roles.remove(role.id)
                await ctx.tick()
            else:
                await ctx.send(error(f"`{role}` is not in the allowed list!"), delete_after=30)

    @mayhemset_mayhem_roles.command(name="list")
    async def mayhemset_mayhem_roles_list(self, ctx):
        """
        View all roles that allow name changing.
        """
        roles = await self.config.guild(ctx.guild).mayhem_roles()
        roles = [ctx.guild.get_role(r) for r in roles]

        msg = [f"{r.mention}\n" for r in roles if r is not None]
        msg = info("Current roles:\n") + "".join(msg)

        for page in pagify(msg, page_length=1800, shorten_by=22):
            await ctx.send(page)

    @mayhemset.group(name="user")
    @checks.admin()
    async def mayhemset_user(self, ctx):
        """
        Set specific users for allowing them to be the subject of mayhem
        """
        pass

    @mayhemset_user.command(name="add")
    async def mayhemset_user_add(self, ctx, *, member: discord.Member):
        """
        Add a member for mayhem
        """
        async with self.config.guild(ctx.guild).allowed_users() as allowed_users:
            if member.id not in allowed_users:
                allowed_users.append(member.id)
                await ctx.tick()
            else:
                await ctx.send(error(f"`{member}` is already added!"), delete_after=30)

    @mayhemset_user.command(name="del")
    async def mayhemset_user_del(self, ctx, *, member: discord.Member):
        """
        Remove a member from name changing
        """
        async with self.config.guild(ctx.guild).allowed_users() as allowed_users:
            if member.id in allowed_users:
                allowed_users.remove(member.id)
                await ctx.tick()
            else:
                await ctx.send(error(f"`{member}` is not in the allowed list!"), delete_after=30)

    @mayhemset_user.command(name="list")
    async def mayhemset_user_list(self, ctx):
        """
        View all members that allow mayhem.
        """
        members = await self.config.guild(ctx.guild).allowed_users()
        members = [ctx.guild.get_member(m) for m in members]

        msg = [f"{m.mention}\n" for m in members if m is not None]
        msg = "Current members:\n" + "".join(msg)

        for page in pagify(msg, page_length=1800, shorten_by=22):
            await ctx.send(page)

    ### Listeners ###
    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        # check if nickname changed
        if before.nick != after.nick:
            current = await self.config.guild(before.guild).current_changes()
            current = current["name"]
            if str(before.id) in current and current[str(before.id)]["new_nick"] != after.nick:
                await self.apply_action(after, "name", current[str(before.id)]["new_nick"])
        if before.roles != after.roles:
            current = await self.config.guild(before.guild).current_changes()
            current = current["role"]
            rids = [r.id for r in after.roles]
            if str(before.id) in current and current[str(before.id)]["role"] not in rids:
                role = after.guild.get_role(current[str(before.id)]["role"])
                await self.apply_action(after, "role", role)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if isinstance(message.channel, discord.abc.PrivateChannel):
            return
        current = await self.config.guild(message.guild).current_changes()
        current = current["reaction"]
        if str(message.author.id) in current:
            react_emoji = current[str(message.author.id)]["emoji"]
            # convert to custom emoji if its one or leave as is for unicode
            react_emoji = react_emoji if isinstance(react_emoji, str) else message.guild.get_emoji(react_emoji)
            try:
                await message.add_reaction(react_emoji)
            except:
                pass
