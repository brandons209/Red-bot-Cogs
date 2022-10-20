# NOTE: this file contains backports or unintroduced features of next versions of dpy (as for 1.7.3)
import discord
from discord.http import Route


async def create_thread(bot, channel: discord.TextChannel, message: discord.Message, name: str, archive: int = 1440):
    """
    Creates a new thread in the channel from the message

    Args:
        channel (TextChannel): The channel the thread will be apart of
        message (Message): The discord message the thread will start with
        name (str): The name of the thread
        archive (int): The archive duration. Can be 60, 1440, 4320, and 10080.

    Returns:
        int: The channel ID of the newly created thread

    Note:
        The guild must be boosted for longer thread durations then a day. The archive parameter will automatically be scaled down if the feature is not present.

        Raises HTTPException 400 if thread creation fails
    """
    guild = channel.guild
    if archive > 10080:
        archive = 10080

    fields = {"name": name, "auto_archive_duration": archive}
    reason = "Thread Manager"

    r = Route(
        "POST", "/channels/{channel_id}/messages/{message_id}/threads", channel_id=channel.id, message_id=message.id,
    )

    return (await bot.http.request(r, json=fields, reason=reason))["id"]


async def add_user_thread(bot, channel: int, member: discord.Member):
    """
    Add a user to a thread

    Args:
        channel (int): The channel id that represents the thread
        member (Member): The member to add to the thread
    """
    reason = "Thread Manager"

    r = Route("POST", "/channels/{channel_id}/thread-members/{user_id}", channel_id=channel, user_id=member.id,)

    return await bot.http.request(r, reason=reason)


async def get_active_threads(bot, guild: discord.Guild):
    """
    Get all active threads in the guild

    Args:
        guild (Guild): The guild to get active threads in

    Returns:
        list(int): List of thread IDs of each actuvate thread
    """

    reason = "Thread Manager"

    r = Route("GET", "/guilds/{guild_id}/threads/active", guild_id=guild.id,)

    res = await bot.http.request(r, reason=reason)

    return [t["id"] for t in res["threads"]]
