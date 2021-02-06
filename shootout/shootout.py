#
# Cog based off of Redjumpman's Russian Roulette
# https://github.com/Redjumpman/Jumper-Plugins/blob/a5a55e3968cb366bf257cb0e886a1c30588e85ef/russianroulette/russianroulette.py
#
from redbot.core import bank, commands, checks, Config
from redbot.core.utils.chat_formatting import *
import asyncio, contextlib, discord, random, shlex
from typing import Literal


class Shootout(commands.Cog):
    default_config = {
        "cost": 50,
        "Messages": ["Shoot!", "Draw!", "Fire!", "Kill!"],
        "Sessions": [],
        "Times": {"lobby": 60, "delay": 10, "fuzzy": 3},
        "Victory": [
            "{winner} has won the shootout! {amount} {currency} has been deposited to their account!",
            "Looks like {winner} is the fastest shot in the server! They were given the pot of {amount} {currency}",
            "{winner} must practice. That draw time was insane! The pot of {amount} {currency} belongs to them.",
            "{winner} fires their gun, and all of their enemies fall to the ground! They claim the bounty of {amount} {currency}.",
        ],
    }
    session_config = {
        "Channel": None,
        "Pot": 0,
        "Players": [],
        "Active": False,
    }

    def __init__(self, bot):
        super().__init__()
        self.bot = bot
        self.config = Config.get_conf(self, identifier=163490961253466112, force_registration=True)
        self.config.register_guild(**self.default_config)

    async def red_delete_data_for_user(self, **kwargs):
        """Nothing to delete."""
        return

    async def game_checks(self, ctx, settings) -> bool:
        session = await self.get_session_from_context(ctx)
        if bool(session["Active"]):
            await ctx.send("There's already a shootout! Wait for them to finish!")
            return False
        if ctx.author.id in session["Players"]:
            await ctx.send("You're already waiting for the shootout!")
            return False
        try:
            await bank.withdraw_credits(ctx.author, settings["cost"])
            return True
        except ValueError:
            currency = await bank.get_currency_name(ctx.guild)
            await ctx.send("Insufficient funds! This game requires {} {}".format(settings["cost"], currency))
            return False

    async def add_player(self, ctx, cost):
        session = await self.get_session_from_context(ctx)

        current_pot = session["Pot"]
        session["Pot"] = current_pot + cost

        session["Players"].append(ctx.author.id)
        num_players = len(session["Players"])

        await self.save_session_to_config(ctx, session)

        if num_players == 1:
            wait = await self.config.guild(ctx.guild).Times.lobby()
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
        session = await self.get_session_from_context(ctx)
        players = [ctx.guild.get_member(player) for player in session["Players"]]
        filtered_players = [player for player in players if isinstance(player, discord.Member)]
        if len(filtered_players) < 2:
            try:
                await bank.deposit_credits(ctx.author, session["Pot"])
            except BalanceTooHigh as e:
                await bank.set_balance(ctx.author, e.max_balance)
            await ctx.send("A shootout with yourself means just shooting at some bottles. For that, no charge.")
            await self.clear_session(ctx)
            return
        listen_message = await self.get_random_draw_message(ctx)
        session["Active"] = True
        await self.save_session_to_config(ctx, session)
        await ctx.send(
            'A shootout is about to start! When I say "Draw!",  type `{}` to shoot your weapon! First person who shoots wins!'.format(
                listen_message
            )
        )

        await asyncio.sleep((await self.get_random_wait_time(ctx)))

        await ctx.send("Draw!")

        def check(m):
            return m.content.lower() == listen_message.lower() and m.channel == ctx.channel and m.author in players

        message = await self.bot.wait_for("message", check=check)
        winner = message.author
        await self.end_game(ctx, winner)

    async def end_game(self, ctx, winner: discord.Member):
        currency = await bank.get_currency_name(ctx.guild)
        session = await self.get_session_from_context(ctx)
        total = session["Pot"]
        try:
            await bank.deposit_credits(winner, total)
        except BalanceTooHigh as e:
            await bank.set_balance(winner, e.max_balance)
        await ctx.send(
            (await self.get_random_win_message(ctx)).format(winner=winner.mention, amount=total, currency=currency)
        )
        await self.clear_session(ctx)

    async def get_random_draw_message(self, ctx) -> str:
        return random.choice((await self.config.guild(ctx.guild).Messages()))

    async def get_random_win_message(self, ctx) -> str:
        return random.choice((await self.config.guild(ctx.guild).Victory()))

    async def get_random_wait_time(self, ctx) -> int:
        delay = await self.config.guild(ctx.guild).Times.delay()
        fuzzy = await self.config.guild(ctx.guild).Times.fuzzy()
        return random.randint(delay - fuzzy, delay + fuzzy)

    async def get_session_from_context(self, ctx):
        channel_id = ctx.channel.id
        sessions = await self.config.guild(ctx.guild).Sessions()
        # Check through all of our currently loaded sessions
        for session in sessions:
            if session["Channel"] == channel_id:
                return session
        # Session for this channel does not exist
        new_session = self.session_config.copy()
        new_session["Channel"] = channel_id
        sessions.append(new_session)
        await self.config.guild(ctx.guild).Sessions.set(sessions)
        return new_session

    async def save_session_to_config(self, ctx, the_session) -> None:
        sessions = await self.config.guild(ctx.guild).Sessions()
        for index, session in enumerate(sessions):
            if session["Channel"] == the_session["Channel"]:
                sessions[index] = the_session
        await self.config.guild(ctx.guild).Sessions.set(sessions)

    async def clear_session(self, ctx) -> None:
        sessions = await self.config.guild(ctx.guild).Sessions()
        for index, session in enumerate(sessions):
            if session["Channel"] == ctx.channel.id:
                sessions.remove(session)
        await self.config.guild(ctx.guild).Sessions.set(sessions)

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

    @soset.group(name="draw")
    async def soset_draw(self, ctx):
        """Root command for draw messages.

        This is the message that will be listened to when the game has started.

        One will randomly be selected per game from the registered list."""
        pass

    @soset_draw.command(name="list")
    async def soset_draw_list(self, ctx):
        """List all of the draw messages currently registered."""
        messages = await self.config.guild(ctx.guild).Messages()

        msg = "Draws:\n\n"
        partial = []
        for index, message in enumerate(messages, start=1):
            partial.append("{}. {}".format(index, message))

        msg += "\n".join(partial)
        for page in pagify(msg):
            await ctx.send(box(page))
        return

    @soset_draw.command(name="add")
    async def soset_draw_add(self, ctx, *, draw: str):
        """Adds a random draw message.

        There are no formatting options for this command. The entire input will be used as the draw.

        Spaces are accepted.
        """

        messages = await self.config.guild(ctx.guild).Messages()
        messages.append(draw)
        await self.config.guild(ctx.guild).Messages.set(messages)
        return await ctx.tick()

    @soset_draw.command(name="rem")
    async def soset_draw_rem(self, ctx, msg_id: int):
        """Removes a draw from the list given the `msg_id` from `[p]soset draw list`."""
        msg_id -= 1
        if msg_id < 0:
            return await ctx.send("Message id must be positive.")
        messages = await self.config.guild(ctx.guild).Messages()
        try:
            to_remove = messages.pop(msg_id)
        except IndexError:
            return await ctx.send("That is an invalid path number.")
        await self.config.guild(ctx.guild).Messages.set(messages)
        return await ctx.tick()

    @soset.group(name="victory")
    async def soset_victory(self, ctx):
        """Root command for the random victory messages."""
        pass

    @soset_victory.command(name="list")
    async def soset_victory_list(self, ctx):
        """List all the victories."""
        victories = await self.config.guild(ctx.guild).Victory()

        msg = "Victories:\n\n"
        partial = []
        for index, victory in enumerate(victories, start=1):
            partial.append("{}. {}".format(index, victory))

        msg += "\n".join(partial)
        for page in pagify(msg):
            await ctx.send(box(page))
        return

    @soset_victory.command(name="add")
    async def soset_victory_add(self, ctx, *, victory: str):
        """Adds a random victory message the bot displays when someone wins.
        - {winner} will be replaced by the winner's mention.
        - {amount} will be replaced by the amount of currency won.
        - {currency} will be replaced by the name of the currency.


        As an example,
        `{winner} has won the shootout! {amount} {currency} has been deposited to their account!` is a valid victory.
        """
        if "{winner}" not in victory:
            await ctx.send("{winner} tag isn't in your victory message!")
        if "{amount}" not in victory:
            await ctx.send("{amount} tag isn't in your victory message!")
        if "{currency}" not in victory:
            await ctx.send("{currency} tag isn't in your victory message!")
        victories = await self.config.guild(ctx.guild).Victory()
        victories.append(victory)
        await self.config.guild(ctx.guild).Victory.set(victories)
        return await ctx.tick()

    @soset_victory.command(name="rem")
    async def soset_victory_rem(self, ctx, vic_id: int):
        """Removes a victory from the list given the `vic_id` from `[p]soset victory list`."""
        vic_id -= 1
        if vic_id < 0:
            return await ctx.send("Victory id must be positive.")
        victories = await self.config.guild(ctx.guild).Victory()
        try:
            to_remove = victories.pop(vic_id)
        except IndexError:
            return await ctx.send("That is an invalid path number.")
        await self.config.guild(ctx.guild).Victory.set(victories)
        return await ctx.tick()

    @soset.command(name="lobby")
    async def soset_wait(self, ctx, wait: int):
        """Sets the wait time until the shootout starts after player 1 runs the command.
        Also known as the lobby time.
        """
        if wait < 0:
            return await ctx.send("Get your negativity out of here!")
        if wait > 120:
            if await self.confirm_long_wait_time(ctx):
                await self.config.guild(ctx.guild).Times.lobby.set(wait)
                await ctx.tick()
            else:
                return await ctx.send("Cancelling setting.")
        else:
            await self.config.guild(ctx.guild).Times.lobby.set(wait)
            await ctx.tick()

    @soset.command(name="delay")
    async def soset_delay(self, ctx, wait: int):
        """Sets the delay time between when the bot displays the message to shoot, and when it accepts messages.
        This is also known as the delay time."""
        if wait < 0:
            return await ctx.send("Get your negativity out of here!")
        fuzzy = await self.config.guild(ctx.guild).Times.fuzzy()
        if (wait - fuzzy) < 0:
            return await ctx.send(
                f"New delay value would set delay - fuzzy value less than 0. With currency fuzzy value, delay needs to be at least {fuzzy}"
            )
        if wait > 120:
            if await self.confirm_long_wait_time(ctx):
                await self.config.guild(ctx.guild).Times.delay.set(wait)
                await ctx.tick()
            else:
                return await ctx.send("Cancelling setting.")
        await self.config.guild(ctx.guild).Times.delay.set(wait)
        await ctx.tick()

    @soset.command(name="fuzzy")
    async def soset_fuzzy(self, ctx, wait: int):
        """Sets the fuzzy time to set the randomness between when the bot sends the shoot message and when it accepts messages.
        This is also known as the fuzzy time.

        Specifically, the fuzzy time is used to determine the min and max value of the wait time. The actual wait time is a random number between `delay - fuzzy` and `delay + fuzzy`.

        ```python
        return random.randomint(delay - fuzzy, delay + fuzzy)
        ```
        """
        if wait < 0:
            return await ctx.send("Get your negativity out of here!")
        delay = await self.config.guild(ctx.guild).Times.delay()
        if (delay - wait) < 0:
            return await ctx.send(
                f"New fuzzy value would set delay - fuzzy value less than 0. With current delay value, fuzzy needs to be at least {delay}"
            )
        if (delay + wait) > 120:
            if await self.confirm_long_wait_time(ctx):
                await self.config.guild(ctx.guild).Times.fuzzy.set(wait)
            else:
                return await ctx.send("Cancelling setting.")
        await self.config.guild(ctx.guild).Times.fuzzy.set(wait)
        await ctx.tick()

    async def confirm_long_wait_time(self, ctx) -> bool:
        query = await ctx.send(
            "Long wait times can cause users to leave the game and the bot to potentially experience issues. If you want to set this anyway, type `yes`."
        )
        try:

            def check(m):
                return m.channel == ctx.channel and m.author == ctx.author

            message = await self.bot.wait_for("message", check=check, timeout=15)
            if message.content.lower() == "yes":
                with contextlib.suppress(discord.Forbidden):
                    await message.delete()
                await query.delete()
                return True
            else:
                await query.delete()
                return False
        except asyncio.TimeoutError:
            await query.delete()
            return False

    @soset.group(name="admin")
    @commands.guild_only()
    @checks.admin_or_permissions(administrator=True)
    async def soset_admin(self, ctx):
        """Perform administrator only commands. Useful debugging commands provided.

        **These commands require the Administrator permission node.**"""
        pass

    @soset_admin.group(name="reset")
    async def soset_admin_reset(self, ctx):
        """Clear session data. Useful if you break something."""
        pass

    @soset_admin_reset.command(name="channel")
    async def soset_admin_reset_channel(self, ctx):
        """Clears session data for this channel. Useful for if you break something.
        **THIS COMMAND CLEARS SESSION FOR THIS CHANNELS. DO NOT USE WHILE A GAME IS IN SESSION, OR IT WILL BE DESTROYED.**
        """
        await self.clear_session(ctx)
        await ctx.tick()
        return

    @soset_admin_reset.command(name="all")
    async def soset_admin_reset_all(self, ctx):
        """Clears all session data. Useful for if you break something.
        **THIS COMMAND CLEARS ALL SESSION FOR ALL CHANNELS DATA. DO NOT USE WHILE GAMES ARE IN SESSION, OR THEY WILL BE DESTROYED.**
        """
        await self.config.guild(ctx.guild).Sessions.clear()
        await ctx.tick()

    @soset_admin.command(name="dump")
    async def soset_admin_dump(self, ctx):
        """Dumps the entire config for this guild."""
        await ctx.send("{}".format(await self.config.guild(ctx.guild).all()))
