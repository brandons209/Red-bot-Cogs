from redbot.core.utils.chat_formatting import *
from redbot.core import Config, checks, commands
from redbot.core.utils.mod import is_admin_or_superior
from discord.ext.commands import DisabledCommand
from typing import Literal
import discord


class DisabledError(commands.CheckFailure):
    pass


DEFAULT_MSG = warning("Sorry, `{0}` is disabled! Please contact a server admin for assistance.")


class Disable(commands.Cog):
    """
    Quickly disable all commands in a guild.
    """

    def __init__(self, bot):
        self.config = Config.get_conf(self, identifier=768437593, force_registration=True)
        self.config.register_guild(disabled_message=DEFAULT_MSG, disabled=False)
        self.bot = bot
        self.bot.before_invoke(self.disabler)

    def cog_unload(self):
        self.bot.remove_before_invoke_hook(self.disabler)

    async def disabler(self, ctx):
        if isinstance(ctx.channel, discord.DMChannel):
            return
        if await self.config.guild(ctx.guild).disabled() and not await is_admin_or_superior(self.bot, ctx.author):
            raise DisabledError(f"Command {ctx.command.name} is disabled in {ctx.guild.name}.")

    @commands.group(name="disable")
    @commands.guild_only()
    @checks.admin()
    async def disable(self, ctx):
        """
        Disable all commands for a bot.

        Only admins can use commands when commands are disabled in the server.
        """
        pass

    @disable.command(name="toggle")
    async def disable_toggle(self, ctx):
        """
        Toggles disabled state of commands.
        """
        current = await self.config.guild(ctx.guild).disabled()
        current = current != True
        await self.config.guild(ctx.guild).disabled.set(current)
        await ctx.tick()

    @disable.command(name="message")
    async def disable_message(self, ctx, *, msg: str = None):
        """
        Change default error message.
        Use {0} to get name of command.
        Pass no message to see current message.
        """
        if not msg:
            current = await self.config.guild(ctx.guild).disabled_message()
            await ctx.send(current)
            return

        await self.config.guild(ctx.guild).disabled_message.set(msg)
        await ctx.tick()

    @commands.Cog.listener()
    async def on_command_error(self, ctx, exception):
        if await self.bot.cog_disabled_in_guild(self, ctx.guild):
            return
        if isinstance(exception, DisabledError):
            msg = await self.config.guild(ctx.guild).disabled_message()
            await ctx.send(msg.format(ctx.command.name))

    async def red_delete_data_for_user(
        self,
        *,
        requester: Literal["discord_deleted_user", "owner", "user", "user_strict"],
        user_id: int,
    ):
        pass
