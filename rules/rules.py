import discord
from redbot.core import checks, commands, Config
from redbot.core.utils import chat_formatting as chat
from redbot.core.utils.menus import menu, DEFAULT_CONTROLS
import asyncio
from typing import Union, Literal


class Rules(commands.Cog):
    """Simple way to quickly list server and channel rules."""

    def __init__(self, bot):
        self.config = Config.get_conf(self, identifier=875454235448, force_registration=True)
        self.bot = bot

        # maps rule number(str) -> rule(str)
        default_guild = {"rules": {}}
        default_channel = {"rules": {}}

        self.config.register_guild(**default_guild)
        self.config.register_channel(**default_channel)

    @commands.group(invoke_without_command=True, aliases=["r"])
    @commands.guild_only()
    async def rule(self, ctx, rule_num: int = None):
        """ Display guild and channel rules """
        if ctx.invoked_subcommand:
            return
        elif rule_num is not None:
            rules = await self.config.guild(ctx.guild).rules()
            try:
                await ctx.send(rules[str(rule_num)])
            except KeyError:
                await ctx.send(chat.error("That rule doesn't exist!"))
        else:
            await self.bot.send_help_for(ctx, self.rule)

    @rule.command(name="list")
    async def rule_list(self, ctx):
        """ List all guild rules """
        rules = await self.config.guild(ctx.guild).rules()
        embeds = []
        rules_keys = sorted([int(r) for r in rules.keys()])
        num_rules = len(rules_keys)
        for i, rule_num in enumerate(rules_keys):
            embed = discord.Embed(title=f"{ctx.guild.name} rules", colour=ctx.guild.me.colour)
            embed.add_field(name=f"Rule {rule_num}", value=rules[str(rule_num)])
            embed.set_footer(text=f"Page {i+1} of {num_rules}")
            embeds.append(embed)

        if not embeds:
            await ctx.send(chat.warning("No rules defined."))
            return

        await menu(ctx, embeds, DEFAULT_CONTROLS)

    @rule.group(invoke_without_command=True, name="channel", aliases=["ch", "c"])
    async def rule_channel(self, ctx, rule_num: int, channel: Union[discord.TextChannel, discord.VoiceChannel] = None):
        """
        Display channel rule. Defaults to current channel.

        For voice channels, use the voice channel ID
        """
        if ctx.invoked_subcommand:
            return

        if channel:
            rules = await self.config.channel(channel).rules()
        else:
            rules = await self.config.channel(ctx.channel).rules()

        try:
            await ctx.send(rules[str(rule_num)])
        except KeyError:
            await ctx.send(chat.error("That rule doesn't exist!"))

    @rule_channel.command(name="list")
    async def rule_channel_list(self, ctx, channel: Union[discord.TextChannel, discord.VoiceChannel] = None):
        """
        List all rules for a channel
        Defaults to current channel.

        For voice channels, use the voice channel ID
        """
        if channel:
            rules = await self.config.channel(channel).rules()
        else:
            channel = ctx.channel
            rules = await self.config.channel(channel).rules()

        embeds = []
        rules_keys = sorted([int(r) for r in rules.keys()])
        num_rules = len(rules_keys)
        for i, rule_num in enumerate(rules_keys):
            embed = discord.Embed(title=f"{channel.name} rules", colour=ctx.guild.me.colour)
            embed.add_field(name=f"Rule {rule_num}", value=rules[str(rule_num)])
            embed.set_footer(text=f"Page {i+1} of {num_rules}")
            embeds.append(embed)

        if not embeds:
            await ctx.send(chat.warning("No rules defined."))
            return

        await menu(ctx, embeds, DEFAULT_CONTROLS)

    @rule.group(invoke_without_command=True, name="set")
    @checks.admin_or_permissions(administrator=True)
    async def rule_set(self, ctx, rule_num: int = None, *, rule: str = None):
        """
        Set a guild rule
        Will overwrite an existing rule of the same number.
        """
        if ctx.invoked_subcommand:
            return
        elif rule_num is not None and rule is not None:
            async with self.config.guild(ctx.guild).rules() as rules:
                rules[str(rule_num)] = rule
            await ctx.tick()
        elif rule_num is not None:
            rules = await self.config.guild(ctx.guild).rules()
            try:
                await ctx.send(rules[str(rule_num)])
            except KeyError:
                await ctx.send(chat.error("That rule doesn't exist!"))
        else:
            await self.bot.send_help_for(ctx, self.rule_set)

    @rule_set.command(name="channel", aliases=["ch", "c"])
    async def rule_set_channel(
        self, ctx, rule_num: int, channel: Union[discord.TextChannel, discord.VoiceChannel], *, rule: str
    ):
        """
        Set a channel rule. Can use channel mention or ID.

        For voice channels, use the voice channel ID.
        """
        async with self.config.channel(channel).rules() as rules:
            rules[str(rule_num)] = rule
        await ctx.tick()

    async def red_delete_data_for_user(
        self,
        *,
        requester: Literal["discord_deleted_user", "owner", "user", "user_strict"],
        user_id: int,
    ):
        pass
