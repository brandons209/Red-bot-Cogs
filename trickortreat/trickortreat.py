from redbot.core.utils.chat_formatting import *
from redbot.core import Config, checks, commands, bank
from redbot.core.utils.predicates import MessagePredicate
from typing import Literal
import discord
import asyncio
import random
import time
from .utils import parse_timedelta, display_time

MAX_MSG_LEN = 1900


class TrickorTreat(commands.Cog):
    """
    Modified payday command to give you some treats, or sometimes a trick!
    """

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=5894564654561635, force_registration=True)
        default_guild = {
            "treat_msgs": [
                "Aurelia likes your costume!",
                "A house is giving out your favorite candy!",
                'You win the "best costume" competition!',
                "Your Halloween party is a massive hit!",
                "Your front lawn is the spookiest in the whole neighborhood!",
                "You and your friends have a Halloween movie marathon!",
                "You managed to repulse a vampire with garlic!",
                "You got invited to the biggest Halloween party!",
                "Your crush said they liked your costume!",
                "You enter a graveyard filled with dancing skeletons. Time to party!",
                "A little ghost noticed your ghost costume and wants to be your friend!",
                "You notice someone disguised as one of your favorite characters! You approach them and they let you take a picture with them!",
                "A house is giving out FULL SIZED CHOCOLATE BARS! Best night ever!",
                "You got to scare someone really good with your costume!",
                "After an awesome night out, you fill your tummy with delicious candy! All is good.",
            ],
            "trick_msgs": [
                "A hole tears in your candy bag and you lose a bunch of candies before you fix it!",
                "You're wearing the same costume as someone else! Someone’s gonna have to change.",
                "It starts raining and your spooky getup is ruined! Oh no!",
                "This house is only giving out... CANDY CORN! THE HORROR! THE HORROR!",
                "All the Halloween candy at the store is sold out!",
                "You got lost in a cemetery where the dead is rising! Ruuuuuun!",
                "Your ghost costume made a real ghost angry and he started to haunt you!",
                "A witch turns you into a frog!",
                "A vampire attacks you because you forgot your garlic necklace at home. Uh-oh!",
                "A black cat crosses your path and you trip, dropping a bunch of candies!",
                "You wandered in the woods and got lost when you suddenly see what looks like a very tall and slender man in the distance.",
                "You slipped in a puddle and dropped candies in a sewer opening where you hear some laughing. Suddenly a red balloon appears from inside.",
                "You and your friends go to a lake, when suddenly something.. or someone is coming out of it, holding a machete.",
                "As you walk with your friends, you suddenly hear the sound of a chainsaw revving up from behind you. It’s rapidly getting closer.",
                "You got sick and had to miss trick or treating! :(",
            ],
            "treat_amount": 500,
            "treat_chance": 0.4,
            "pay_delay": 1200,
        }

        default_member = {"last_pay": 0}

        self.config.register_guild(**default_guild)
        self.config.register_member(**default_member)

    @commands.group()
    @commands.guild_only()
    @checks.admin()
    async def totset(self, ctx):
        """
        Manage your tricks and treats!
        """
        pass

    @totset.command()
    async def amount(self, ctx, amount: int):
        """
        Set the amount of currency to give on a treat
        """
        if amount <= 0:
            await ctx.send(error("Please use an amount greater than 0."))
            return
        await self.config.guild(ctx.guild).treat_amount.set(amount)
        await ctx.tick()

    @totset.command()
    async def chance(self, ctx, chance: float):
        """
        Set the chance for a treat to occur

        Chance should be between 0 and 1.
        """

        if chance <= 0 or chance > 1:
            await ctx.send(error("Please use a chance amount between 0 and 1."))
            return

        await self.config.guild(ctx.guild).treat_chance.set(chance)
        await ctx.tick()

    @totset.command()
    async def delay(self, ctx, *, delay: str):
        """
        Set delay between trick or treats.

        Delay can be an interval like:

        15 minutes
        30 seconds
        5 minutes 30 seconds
        10m30s

        4 hours
        4h30m
        """

        delta = parse_timedelta(delay)

        if not delta:
            await ctx.send(error("Unrecognized delay, try again."))
            return

        await self.config.guild(ctx.guild).pay_delay.set(delta.total_seconds())

        await ctx.send(f"Delay set to {display_time(delta.total_seconds())}")
        await ctx.tick()

    @totset.group(name="treatmsg")
    async def treatmsg(self, ctx):
        """
        Manage messages sent for getting a treat.
        """
        pass

    @treatmsg.command(name="add")
    async def treatmsg_add(self, ctx, *, msg: str):
        """
        Add a new possible message sent for a treat
        """

        async with self.config.guild(ctx.guild).treat_msgs() as treat_msgs:
            treat_msgs.append(msg)

        await ctx.tick()

    @treatmsg.command(name="del")
    async def treatmsg_del(self, ctx):
        """
        Delete one of the treat messages
        """

        async with self.config.guild(ctx.guild).treat_msgs() as treat_msgs:
            if not treat_msgs:
                await ctx.send(warning("No messages defined!"))
                return
            msg = "\n".join(f"{i+1}. {m}" for i, m in enumerate(treat_msgs))

            for page in pagify(msg):
                await ctx.send(box(page))

            await ctx.send("Choose the number of the message to delete.")
            pred = MessagePredicate.valid_int()

            try:
                await self.bot.wait_for("message", check=pred, timeout=30)
            except asyncio.TimeoutError:
                await ctx.send("Took too long.")
                return

            if pred.result < 1 or pred.result > len(treat_msgs):
                await ctx.send(error("Please choose one of the messages."))
                return

            del treat_msgs[pred.result - 1]

        await ctx.send("Deleted message.")

    @treatmsg.command(name="list")
    async def treatmsg_list(self, ctx):
        """
        List all treat messages
        """

        async with self.config.guild(ctx.guild).treat_msgs() as treat_msgs:
            if not treat_msgs:
                await ctx.send(warning("No messages defined!"))
                return

            msg = "\n".join(f"{i+1}. {m}" for i, m in enumerate(treat_msgs))

            for page in pagify(msg):
                await ctx.send(box(page))

    @totset.group(name="trickmsg")
    async def trickmsg(self, ctx):
        """
        Manage messages sent for getting a trick.
        """
        pass

    @trickmsg.command(name="add")
    async def trickmsg_add(self, ctx, *, msg: str):
        """
        Add a new possible message sent for a trick
        """

        async with self.config.guild(ctx.guild).trick_msgs() as trick_msgs:
            trick_msgs.append(msg)

        await ctx.tick()

    @trickmsg.command(name="del")
    async def trickmsg_del(self, ctx):
        """
        Delete one of the trick messages
        """

        async with self.config.guild(ctx.guild).trick_msgs() as trick_msgs:
            if not trick_msgs:
                await ctx.send(warning("No messages defined!"))
                return
            msg = "\n".join(f"{i+1}. {m}" for i, m in enumerate(trick_msgs))

            for page in pagify(msg):
                await ctx.send(box(page))

            await ctx.send("Choose the number of the message to delete.")
            pred = MessagePredicate.valid_int()

            try:
                await self.bot.wait_for("message", check=pred, timeout=30)
            except asyncio.TimeoutError:
                await ctx.send("Took too long.")
                return

            if pred.result < 1 or pred.result > len(trick_msgs):
                await ctx.send(error("Please choose one of the messages."))
                return

            del trick_msgs[pred.result - 1]

        await ctx.send("Deleted message.")

    @trickmsg.command(name="list")
    async def trickmsg_list(self, ctx):
        """
        List all trick messages
        """

        async with self.config.guild(ctx.guild).trick_msgs() as trick_msgs:
            if not trick_msgs:
                await ctx.send(warning("No messages defined!"))
                return

            msg = "\n".join(f"{i+1}. {m}" for i, m in enumerate(trick_msgs))

            for page in pagify(msg):
                await ctx.send(box(page))

    @commands.command()
    @commands.guild_only()
    async def trickortreat(self, ctx):
        """
        Get a treat, or maybe a sneaky trick!
        """
        guild = ctx.guild
        delay = await self.config.guild(guild).pay_delay()
        last_pay = await self.config.member(ctx.author).last_pay()
        next_pay = last_pay + delay
        if time.time() < next_pay:
            await ctx.send(
                f"Too soon {ctx.author.mention}, gotta find another house! The next house is {display_time(next_pay - time.time())} away."
            )
            return

        currency_name = await bank.get_currency_name(guild)
        amount = await self.config.guild(guild).treat_amount()
        chance = await self.config.guild(guild).treat_chance()

        if random.random() < chance:
            # treat!
            msg = random.choice(await self.config.guild(guild).treat_msgs())
            if len(msg) < MAX_MSG_LEN:
                await ctx.send(f"**{msg}**\n\nYou got {amount} {currency_name} {ctx.author.mention}!")
            else:
                await ctx.send(f"{random.choice(treat_msgs)}")
                await ctx.send(f"You got {amount} {currency_name} {ctx.author.mention}!")

            try:
                await bank.deposit_credits(ctx.author, amount)
            except errors.BalanceTooHigh as exc:
                await bank.set_balance(author, exc.max_balance)
                await ctx.send(
                    _(
                        "You've reached the maximum amount of {currency}! "
                        "Please spend some more \N{GRIMACING FACE}\n\n"
                        "You currently have {new_balance} {currency}."
                    ).format(currency=currency_name, new_balance=humanize_number(exc.max_balance))
                )
        else:
            # trick!
            msg = random.choice(await self.config.guild(guild).trick_msgs())
            if len(msg) < MAX_MSG_LEN:
                await ctx.send(f"**{msg}**\n\nYou lost {amount} {currency_name} {ctx.author.mention}!")
            else:
                await ctx.send(f"{random.choice(treat_msgs)}")
                await ctx.send(f"You lost {amount} {currency_name} {ctx.author.mention}!")

            bal = await bank.get_balance(ctx.author)
            if bal < amount:
                await bank.withdraw_credits(ctx.author, bal)
            else:
                await bank.withdraw_credits(ctx.author, amount)

        await self.config.member(ctx.author).last_pay.set(time.time())

    async def red_delete_data_for_user(
        self,
        *,
        requester: Literal["discord_deleted_user", "owner", "user", "user_strict"],
        user_id: int,
    ):
        pass
