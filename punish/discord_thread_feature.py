# NOTE: this file contains backports or unintroduced features of next versions of dpy (as for 1.7.3)
import discord
from discord.http import Route


class THREAD_TYPES:
    PUBLIC_THREAD = 11
    PRIVATE_THREAD = 12


async def create_thread(
    bot,
    channel: discord.TextChannel,
    name: str,
    archive: int = 1440,
    invitable: bool = False,
    thread_type: int = THREAD_TYPES.PRIVATE_THREAD,
    rate_limit: int = 0,
):
    """
    Creates a new thread in the channel from the message

    Args:
        channel (TextChannel): The channel the thread will be apart of
        name (str): The name of the thread
        archive (int, Optional): The archive duration. Can be 60, 1440, 4320, and 10080 seconds
        invitable (bool, Optional): Whether non moderators can add other non-moderators to a thread. Only used for private threads
        thread_type (int, Optional): The type of thread (public or private)
        rate_limit(int, Optional): Set the rate limit for users, from 0-21600 seconds

    Returns:
        int: The channel ID of the newly created thread

    Note:
        The guild must be boosted for longer thread durations then a day. The archive parameter will automatically be scaled down if the feature is not present.

        Raises HTTPException 400 if thread creation fails
    """
    guild = channel.guild
    if archive > 10080:
        archive = 10080

    if thread_type == THREAD_TYPES.PRIVATE_THREAD and "PRIVATE_THREADS" not in guild.features:
        raise AttributeError("Your guild requires Level 2 Boost to use private threads.")

    fields = {
        "name": name,
        "auto_archive_duration": archive,
        "type": thread_type,
        "invitable": invitable,
        "rate_limit_per_user": rate_limit,
    }
    reason = "Punish Thread Creation"

    r = Route("POST", "/channels/{channel_id}/threads", channel_id=channel.id,)

    return (await bot.http.request(r, json=fields, reason=reason))["id"]


async def add_user_thread(bot, channel: int, member: discord.Member):
    """
    Add a user to a thread

    Args:
        channel (int): The channel id that represents the thread
        member (Member): The member to add to the thread
    """
    reason = "Punish Add Member"

    r = Route("POST", "/channels/{channel_id}/thread-members/{user_id}", channel_id=channel, user_id=member.id,)

    return await bot.http.request(r, reason=reason)
