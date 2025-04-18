from copy import copy
from datetime import timedelta
from dateutil import parser
import asyncio
import discord

from redbot.core import Config, checks, commands
from redbot.core.commands.requires import PrivilegeLevel
from redbot.core.i18n import Translator
from redbot.core.utils.predicates import MessagePredicate

_ = Translator("Warnings", __file__)


def calculate_total_points(warnings: dict, expiration_time: int = 0) -> int:
    """
    Calculates total warning points taking into account the expiration time set.
    Warnings that don't have a date set (warnings made before switching to custom cog) will not be added.

    Args:
        warnings (dict): Dictionary of user's warnings
        expiration_time (int): expiration time delta in seconds.

    Returns:
        int: The adjusted points
    """
    if expiration_time == 0:
        return sum([w["points"] for w in warnings.values()])

    delta = timedelta(seconds=expiration_time)
    now = discord.utils.utcnow()
    total = 0
    for w in warnings.values():
        if not w.get("date", None):
            continue
        date = parser.parse(w["date"])
        if date > (now - delta):
            total += w["points"]
    return total


def check_warning_expired(warning: dict, expiration_time: int = 0) -> bool:
    """
    Returns whether the specified warning was expired.

    Args:
        warning (dict): Dictionary representing the warning
        expiration_time (int, optional): Expiration time set for guild. Defaults to 0.

    Returns:
        bool: If the warning has expired or not
    """
    if expiration_time == 0:
        return False
    delta = timedelta(seconds=expiration_time)
    now = discord.utils.utcnow()
    # if date doesn't exist, assume expired
    try:
        date = parser.parse(warning.get("date", ""))
    except:
        return True

    if date > (now - delta):
        return False
    else:
        return True


async def warning_points_add_check(config: Config, ctx: commands.Context, user: discord.Member, points: int):
    """Handles any action that needs to be taken or not based on the points"""
    guild = ctx.guild
    guild_settings = config.guild(guild)
    act = {}
    async with guild_settings.actions() as registered_actions:
        for a in registered_actions:
            # Actions are sorted in decreasing order of points.
            # The first action we find where the user is above the threshold will be the
            # highest action we can take.
            if points >= a["points"]:
                act = a
                break
    if act and act["exceed_command"] is not None:  # some action needs to be taken
        await create_and_invoke_context(ctx, act["exceed_command"], user)


async def warning_points_remove_check(config: Config, ctx: commands.Context, user: discord.Member, points: int):
    guild = ctx.guild
    guild_settings = config.guild(guild)
    act = {}
    async with guild_settings.actions() as registered_actions:
        for a in registered_actions:
            if points >= a["points"]:
                act = a
            else:
                break
    if act and act["drop_command"] is not None:  # some action needs to be taken
        await create_and_invoke_context(ctx, act["drop_command"], user)


async def create_and_invoke_context(realctx: commands.Context, command_str: str, user: discord.Member):
    m = copy(realctx.message)
    m.content = command_str.format(user=user.mention, prefix=realctx.prefix)
    fctx = await realctx.bot.get_context(m, cls=commands.Context)
    try:
        await realctx.bot.invoke(fctx)
    except (commands.CheckFailure, commands.CommandOnCooldown):
        # reinvoke bypasses checks and we don't want to run bot owner only commands here
        if fctx.command.requires.privilege_level < PrivilegeLevel.BOT_OWNER:
            await fctx.reinvoke()


def get_command_from_input(bot, userinput: str):
    com = None
    orig = userinput
    while com is None:
        com = bot.get_command(userinput)
        if com is None:
            userinput = " ".join(userinput.split(" ")[:-1])
        if len(userinput) == 0:
            break
    if com is None:
        return None, _("I could not find a command from that input!")

    if com.requires.privilege_level >= PrivilegeLevel.BOT_OWNER:
        return (
            None,
            _("That command requires bot owner. I can't allow you to use that for an action"),
        )
    return "{prefix}" + orig, None


async def get_command_for_exceeded_points(ctx: commands.Context):
    """Gets the command to be executed when the user is at or exceeding
    the points threshold for the action"""
    await ctx.send(
        _(
            "Enter the command to be run when the user **exceeds the points for "
            "this action to occur.**\n**If you do not wish to have a command run, enter** "
            "`none`.\n\nEnter it exactly as you would if you were "
            "actually trying to run the command, except don't put a prefix and "
            "use `{user}` in place of any user/member arguments\n\n"
            "WARNING: The command entered will be run without regard to checks or cooldowns. "
            "Commands requiring bot owner are not allowed for security reasons.\n\n"
            "Please wait 15 seconds before entering your response."
        )
    )
    await asyncio.sleep(15)

    await ctx.send(_("You may enter your response now."))

    try:
        msg = await ctx.bot.wait_for("message", check=MessagePredicate.same_context(ctx), timeout=30)
    except asyncio.TimeoutError:
        return None
    else:
        if msg.content == "none":
            return None

    command, m = get_command_from_input(ctx.bot, msg.content)
    if command is None:
        await ctx.send(m)
        return None

    return command


async def get_command_for_dropping_points(ctx: commands.Context):
    """
    Gets the command to be executed when the user drops below the points
    threshold

    This is intended to be used for reversal of the action that was executed
    when the user exceeded the threshold
    """
    await ctx.send(
        _(
            "Enter the command to be run when the user **returns to a value below "
            "the points for this action to occur.** Please note that this is "
            "intended to be used for reversal of the action taken when the user "
            "exceeded the action's point value.\n**If you do not wish to have a command run "
            "on dropping points, enter** `none`.\n\nEnter it exactly as you would "
            "if you were actually trying to run the command, except don't put a prefix "
            "and use `{user}` in place of any user/member arguments\n\n"
            "WARNING: The command entered will be run without regard to checks or cooldowns. "
            "Commands requiring bot owner are not allowed for security reasons.\n\n"
            "Please wait 15 seconds before entering your response."
        )
    )
    await asyncio.sleep(15)

    await ctx.send(_("You may enter your response now."))

    try:
        msg = await ctx.bot.wait_for("message", check=MessagePredicate.same_context(ctx), timeout=30)
    except asyncio.TimeoutError:
        return None
    else:
        if msg.content == "none":
            return None
    command, m = get_command_from_input(ctx.bot, msg.content)
    if command is None:
        await ctx.send(m)
        return None

    return command
