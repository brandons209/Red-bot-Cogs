from redbot.core.utils.chat_formatting import *
from redbot.core import Config, checks, commands, bank
from typing import Literal
import discord
import asyncio


class PoorError(commands.CheckFailure):
    pass


# 0 -> member, 1 -> guild
NEW_RECEIPT_MESSAGE = "Hello {0.mention}! This is will be your receipt for commands you pay for in {1.name}.\nThe message below will auto update as you pay for commands. I will pin the message for you so you can refer back to this to track your spending."

# 0 -> recepit number, 1 -> command name, 2->command cost, 3 -> currency name
RECEIPT_MESSAGE = "{0}. {1}: {2} {3}\n"

MAX_MSG_LEN = 2000


class CostManager(commands.Cog):
    """
    Allows customizing costs for any commands loaded into read,
    and also set users who are exempt from costs on a per member or per role level.
    Hierarchy: user > role > guild_role
    """

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=13291493293, force_registration=True)

        # commands: {
        #   command_name: {
        #      cost: int
        #      user_ids: {user_id:cost}
        #      role_ids: {role_id:cost} # cost can be 0 to make free
        #    },
        #    ...
        # }
        default_guild = {"FREE_ROLES": [], "COMMANDS": {}}
        self.config.register_guild(**default_guild)
        self.config.register_member(receipt=0)
        self.bot.before_invoke(self.cost_checker)

    def cog_unload(self):
        self.bot.remove_before_invoke_hook(self.cost_checker)

    # permission hook checker for cost of command
    async def cost_checker(self, ctx):

        cost = await self.get_cost(ctx)

        if cost == 0:
            return None

        try:
            await bank.withdraw_credits(ctx.author, cost)
            await self.update_receipt(ctx, cost)
        except ValueError:
            raise PoorError(f"member: {ctx.author.id}, guild: {ctx.guild.id}")

    async def get_cost(self, ctx, member=None, command=None):
        """
        Get cost of a command, respecting hierarchy
        """
        if isinstance(ctx.channel, discord.DMChannel):
            return 0
        guild = ctx.guild
        if not member:
            member = ctx.author
        member_roles = {r.id for r in member.roles if r.name != "@everyone"}
        if not command:
            command = ctx.command.name

        guild_data = await self.config.guild(guild).all()
        command_data = guild_data["COMMANDS"]

        # check if settings for command
        if command not in command_data.keys():
            return 0

        command_data = command_data[command]
        charged_roles = set(command_data.get("role_ids", {}).keys())
        found_roles = charged_roles & member_roles
        cost = 0

        # check user cost
        if str(member.id) in command_data.get("user_ids", {}).keys():
            cost = command_data["user_ids"][str(member.id)]
        # check role cost, choose lowest cost if mutliple roles found.
        elif found_roles:
            cost = min([command_data["role_ids"][r] for r in found_roles])
        else:  # get normal cost for command and check guild free roles
            cost = command_data["cost"]
            found_roles = set(guild_data["FREE_ROLES"]) & member_roles
            if found_roles:
                cost = 0

        return cost

    async def update_receipt(self, ctx, cost):
        """
        Update user's receipt, or make a new one if its new receipt or old one is somehow missing.
        """
        guild = ctx.guild
        member = ctx.author
        command = ctx.command.name
        receipt = await self.config.member(member).receipt()

        channel = member.dm_channel
        if not channel:
            await member.create_dm()

        channel = member.dm_channel
        msg_receipt = None
        if receipt > 0:
            try:
                msg_receipt = await channel.fetch_message(receipt)
            except (Forbidden, HTTPException):
                return
            except NotFound:
                pass

        if not msg_receipt:
            try:
                await channel.send(NEW_RECEIPT_MESSAGE.format(member, guild))
            except:
                if receipt != -1:  # send mention if first time getting this message
                    await ctx.send(
                        f"Hey {member.mention}, please turn on DMs from server members in your settings so I can send you receipts for purchase of commands.",
                        allowed_mentions=discord.AllowedMentions.all(),
                    )

                    await self.config.member(member).receipt.set(-1)
                return

            currency_name = await bank.get_currency_name(guild)
            msg_receipt = await channel.send(RECEIPT_MESSAGE.format(1, command, cost, currency_name))
            await msg_receipt.pin()
            await self.config.member(member).receipt.set(msg_receipt.id)
            return

        # msg already found, so update it
        currency_name = await bank.get_currency_name(guild)
        content = msg_receipt.content.split("\n")
        # TODO: this is really messy but ill fix it...
        last_num = int(content[-1].split(".")[0])
        content.append(RECEIPT_MESSAGE.format(last_num + 1, command, cost, currency_name))

        while len("\n".join(content)) > MAX_MSG_LEN:
            del content[0]

        content = "\n".join(content)

        await msg_receipt.edit(content=content)

    async def clean_data(self, guild):
        async with self.config.guild(guild).FREE_ROLES() as free:
            roles = [guild.get_role(id) for id in free]
            free = [r.id for r in roles if r is not None]

        async with self.config.guild(guild).COMMANDS() as c:
            for command_name in list(c.keys()):
                data = c[command_name]
                for user_id in data.get("user_ids", {}).keys():
                    if not guild.get_member(int(user_id)):
                        del c[command_name]["user_ids"][user_id]
                for role_id in data.get("role_ids", {}).keys():
                    if not guild.get_role(int(role_id)):
                        del c[command_name]["role_ids"][role_id]

    # check validity of arguments
    def arg_check(self, cost: int, command: str):
        if not self.bot.get_command(command) or cost < 0:
            return False

        return True

    # format list of items
    @staticmethod
    def format_list(*items, join="and", delim=", "):
        if len(items) > 1:
            return (" %s " % join).join((delim.join(items[:-1]), items[-1]))
        elif items:
            return items[0]
        else:
            return ""

    @commands.group(name="costset", invoke_without_command=True)
    @commands.guild_only()
    @checks.admin()
    async def costset(self, ctx, cost: int, *, command_name: str = None):
        """
        Sets and manage cost/bypasses of commands.
        """
        if ctx.invoked_subcommand:
            return

        if not self.arg_check(cost, command_name):
            await ctx.send("Invalid cost or command!")
            return

        async with self.config.guild(ctx.guild).COMMANDS() as c:
            if not command_name in c.keys():
                c[command_name] = {}
            c[command_name]["cost"] = cost

        await ctx.tick()

    @costset.command(name="role")
    async def cost_set_role(self, ctx, command_name: str, cost: int, *, role: discord.Role):
        """
        Set cost of command for specific role.
        Set to 0 to make command free for role.
        """
        if not self.arg_check(cost, command_name):
            await ctx.send("Invalid cost or command!")
            return

        async with self.config.guild(ctx.guild).COMMANDS() as c:
            if not command_name in c.keys():
                c[command_name] = {}
            if not "role_ids" in c[command_name].keys():
                c[command_name]["role_ids"] = {}
            c[command_name]["role_ids"][str(role.id)] = cost

        await ctx.tick()

    @costset.command(name="user")
    async def cost_set_user(self, ctx, command_name: str, cost: int, *, member: discord.Member):
        """
        Set cost of command for specific user.
        Set to 0 to make command free for user.
        """
        if not self.arg_check(cost, command_name):
            await ctx.send("Invalid cost or command!")
            return

        async with self.config.guild(ctx.guild).COMMANDS() as c:
            if not command_name in c.keys():
                c[command_name] = {}
            if not "user_ids" in c[command_name].keys():
                c[command_name]["user_ids"] = {}

            c[command_name]["user_ids"][str(member.id)] = cost

        await ctx.tick()

    @costset.command(name="clear")
    async def cost_set_clear(self, ctx):
        """
        Clear missing roles/members in cost config.
        """
        await self.clean_data(ctx.guild)

        await ctx.tick()

    @costset.command(name="owner-clear")
    @checks.is_owner()
    async def cost_set_owner_clear(self, ctx):
        """
        Clear missing roles/members in every cost config.
        """
        for guild in self.bot.guilds:
            await self.clean_data(guild)

        await ctx.tick()

    @costset.command(name="free-roles")
    async def cost_set_free_roles(self, ctx, *, role_list: str = None):
        """
        Set roles who can use all commands for free in server.

        **Note**: This only applies to commands whose cost was set with this cog.
        Role list should be a list of one or more **role names or ids** seperated by commas.
        Roles in role list will be removed if already in the free role list, or added if they are not.

        Role names are case sensitive!

        Don't pass a role list to see the current roles
        """
        if not role_list:
            curr = await self.config.guild(ctx.guild).FREE_ROLES()
            if not curr:
                await ctx.send("No roles defined.")
            else:
                curr = [ctx.guild.get_role(role_id) for role_id in curr]
                not_found = len([r for r in curr if r is None])
                curr = [r.name for r in curr if curr is not None]
                if not_found:
                    await ctx.send(
                        f"{not_found} roles weren't found, please run {ctx.prefix}costset clear to remove these roles.\nFree Roles: {self.format_list(*curr)}"
                    )
                else:
                    await ctx.send(f"Free Roles: {self.format_list(*curr)}")
            return

        role_list = role_list.strip().split(",")
        role_list = [r.strip() for r in role_list]
        not_found = set()
        found = set()
        added = set()
        removed = set()
        for role_name in role_list:
            role = discord.utils.find(lambda r: r.name == role_name, ctx.guild.roles)
            # if couldnt find by role name, try to find by role id
            if role is None:
                role = discord.utils.find(lambda r: r.id == role_name, ctx.guild.roles)

            if role is None:
                not_found.add(role_name)
                continue

            found.add(role)

        if not_found:
            await ctx.send(
                warning("These roles weren't found, please try again: {}".format(self.format_list(*not_found)))
            )
            return

        async with self.config.guild(ctx.guild).FREE_ROLES() as free:
            for role in found:
                if role.id in free:
                    free.remove(role.id)
                    removed.add(role.name)
                else:
                    free.append(role.id)
                    added.add(role.name)
        msg = ""
        if added:
            msg += "Added: {}\n".format(self.format_list(*added))
        if removed:
            msg += "Removed: {}".format(self.format_list(*removed))

        await ctx.send(msg)

    @costset.command(name="list")
    async def cost_set_list(self, ctx):
        """
        List current cost settings for the guild
        """
        guild = ctx.guild
        guild_data = await self.config.guild(guild).all()
        free_roles = [guild.get_role(r) for r in guild_data["FREE_ROLES"]]
        free_roles = self.format_list(*[r.name for r in free_roles if r is not None])
        commands = guild_data["COMMANDS"]

        msg = f"Guild Free Roles: {free_roles}\n\nCommands:\n"

        for command_name, data in commands.items():
            msg += f"\t{command_name}: {data['cost']}\n"
            msg += "\t\tRole Costs:\n"
            for role_id, cost in data.get("role_ids", {}).items():
                role = guild.get_role(int(role_id))
                if not role:
                    continue
                msg += f"\t\t\t{role.name}: {cost}\n"

            msg += "\t\tUser Costs:\n"
            for user_id, cost in data.get("user_ids", {}).items():
                user = guild.get_member(int(user_id))
                if not user:
                    continue
                msg += f"\t\t\t{user.name}: {cost}\n"

        msg = pagify(msg)
        for m in msg:
            await ctx.send(box(m, lang="python"))

    @commands.command(name="cost")
    @commands.guild_only()
    async def get_cost_command(self, ctx, command: str):
        """
        Get cost of a command.
        """
        if not self.arg_check(0, command):
            await ctx.send(warning(f"Command `{command}` not found!"))
            return

        cost = await self.get_cost(ctx, command=command)
        if cost == 0:
            await ctx.send(f"{command} is free for you!")
            return
        else:
            currency_name = await bank.get_currency_name(ctx.guild)
            await ctx.send(f"{command} costs `{cost}` {currency_name} for you.")

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        await self.clean_data(member.guild)

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role):
        await self.clean_data(role.guild)

    # Listens for poorerror
    @commands.Cog.listener()
    async def on_command_error(self, ctx, exception):
        if isinstance(exception, PoorError):
            cost = await self.get_cost(ctx)
            currency_name = await bank.get_currency_name(ctx.guild)
            balance = await bank.get_balance(ctx.author)
            message = await ctx.send(
                f"Sorry {ctx.author.name}, you do not have enough {currency_name} to use that command. (Cost: {cost}, Balance: {balance})",
                allowed_mentions=discord.AllowedMentions.all(),
            )
            await asyncio.sleep(10)
            await message.delete()

    async def red_delete_data_for_user(
        self,
        *,
        requester: Literal["discord_deleted_user", "owner", "user", "user_strict"],
        user_id: int,
    ):
        pass
