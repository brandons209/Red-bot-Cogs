#
# Cog based off of Redjumpman's Russian Roulette
# https://github.com/Redjumpman/Jumper-Plugins/blob/a5a55e3968cb366bf257cb0e886a1c30588e85ef/russianroulette/russianroulette.py
#
from redbot.core import bank, commands, checks, Config
import discord
import asyncio


class Shootout(commands.Cog):
    default_config = {
        "cost": 50,
        "message": "Shoot!",
        "wait_time": 60,
        "Session": {"Pot": 0, "Players": [], "Active": False},
    }

    def __init__(self, bot):
        super().__init__()
        self.bot = bot
        self.config = Config.get_conf(self, identifier=163490961253466112, force_registration=True)
        default_config = {
            "cost": 50,
            "message": "Shoot!",
            "wait_time": 60,
            "Session": {"Pot": 0, "Players": [], "Active": False},
        }
        self.config.register_guild(**self.default_config)

    async def red_delete_data_for_user(self, **kwargs):
        """Nothing to delete."""
        return

    async def game_checks(self, ctx, settings) -> bool:
        if bool(settings["Session"]["Active"]):
            await ctx.send("There's already a shootout! Wait for them to finish!")
            return False
        if ctx.author.id in settings["Session"]["Players"]:
            await ctx.send("You're already waiting for the shootout!")
            return False
        try:
            await bank.withdraw_credits(ctx.author, settings["cost"])  # <- Might raise a ValueError!
            return True
        except ValueError:
            currency = await bank.get_currency_name(ctx.guild)
            await ctx.send("Insufficient funds! This game requires {} {}".format(settings["cost"], currency))
            return False

    async def add_player(self, ctx, cost):
        current_pot = await self.config.guild(ctx.guild).Session.Pot()
        await self.config.guild(ctx.guild).Session.Pot.set(value=(current_pot + cost))

        async with self.config.guild(ctx.guild).Session.Players() as players:
            players.append(ctx.author.id)
            num_players = len(players)

        if num_players == 1:
            wait = await self.config.guild(ctx.guild).wait_time()
            await ctx.send(
                "{0.author.mention} is gathering players for a shootout!\n"
                "Type `{0.prefix}shootout` to join in!\n"
                "The round will start in {1} seconds.".format(ctx, wait)
            )
            await asyncio.sleep(wait)
            await self.start_game(ctx)
        else:
            await ctx.send("{} joined the shootout!".format(ctx.author.mention))

    async def start_game(self, ctx):
        settings = await self.config.guild(ctx.guild).Session.all()
        players = [ctx.guild.get_member(player) for player in settings["Players"]]
        filtered_players = [player for player in players if isinstance(player, discord.Member)]
        if len(filtered_players) < 2:
            try:
                await bank.deposit_credits(ctx.author, settings["Pot"])
            except BalanceTooHigh as e:
                await bank.set_balance(ctx.author, e.max_balance)
            await ctx.send("A shootout with yourself means just shooting at some bottles. For that, no charge.")
            await self.config.guild(ctx.guild).Session.clear()
            return
        listen_message = await self.config.guild(ctx.guild).message()
        await self.config.guild(ctx.guild).Session.Active.set(True)
        await ctx.send(
            "The shootout has started! Draw your weapons and type `{}` to shoot your weapon! First person who shoots wins!".format(
                listen_message
            )
        )

        def check(m):
            return m.content.lower() == listen_message.lower() and m.channel == ctx.channel and m.author in players

        message = await self.bot.wait_for("message", check=check)
        winner = message.author
        await self.end_game(ctx, winner)

    async def end_game(self, ctx, winner: discord.Member):
        currency = await bank.get_currency_name(ctx.guild)
        total = await self.config.guild(ctx.guild).Session.Pot()
        try:
            await bank.deposit_credits(winner, total)
        except BalanceTooHigh as e:
            await bank.set_balance(winner, e.max_balance)
        await ctx.send(
            "{} has won the shootout! {} {} has been deposited to their account!".format(
                winner.mention, total, currency
            )
        )
        await self.config.guild(ctx.guild).Session.clear()

    @commands.command()
    @commands.guild_only()
    async def shootout(self, ctx):
        """Start or join a shootout!

        A shootout is a game where players can join by putting up money into the pot (if configured).

        The bot will send a message to chat saying to begin and what message to type to win.

        First person who types the message wins the entire pot! (Even if that pot is 0).

        The game will not start if no other players have joined, and any cost will be refunded.

        There is no maximum number of players.
        """
        settings = await self.config.guild(ctx.guild).all()
        if await self.game_checks(ctx, settings):
            await self.add_player(ctx, settings["cost"])

    @commands.group()
    @commands.guild_only()
    @checks.mod_or_permissions(manage_guild=True)
    async def soset(self, ctx):
        """Change settings to Shootout"""
        pass

    @soset.command(name="bet")
    async def soset_bet(self, ctx, amount: int):
        """Sets the bet amount for a shootout"""
        if amount < 0:
            return await ctx.send("Get your negativity out of here!")
        await self.config.guild(ctx.guild).cost.set(amount)
        await ctx.tick()
        return

    @soset.command(name="message")
    async def soset_message(self, ctx, message: str):
        """Sets the message that the bot listens for during shootout games. Only affects new games!"""
        await self.config.guild(ctx.guild).message.set(message)
        await ctx.tick()
        return

    @soset.command(name="wait")
    async def soset_wait(self, ctx, wait: int):
        """Sets the wait time until the shootout starts after player 1 runs the command."""
        if wait < 0:
            return await ctx.send("Get your negativity out of here!")
        await self.config.guild(ctx.guild).wait_time.set(wait)
        await ctx.tick()

    @commands.guild_only()
    @checks.admin_or_permissions(administrator=True)
    @commands.command(hidden=True)
    async def shootout_reset(self, ctx):
        """This command clears all session data. Useful for if you break something."""
        await self.config.guild(ctx.guild).Session.clear()
        await ctx.tick()

    @commands.guild_only()
    @checks.admin_or_permissions(administrator=True)
    @commands.command(hidden=True)
    async def shootout_dump_config(self, ctx):
        """This command dumps the current config data."""
        await ctx.send("{}".format(await self.config.guild(ctx.guild).all()))
