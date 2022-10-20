# NOTE: this file contains backports or unintroduced features of next versions of dpy (as for 1.7.3)
import discord
from discord.http import Route


async def create_thread(
    bot, channel: discord.TextChannel, name: str, archive: int = 1440, message: discord.Message = None,
):
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

    reason = "Thread Rotation"
    fields = {"name": name, "auto_archive_duration": archive}

    if message is not None:
        r = Route(
            "POST",
            "/channels/{channel_id}/messages/{message_id}/threads",
            channel_id=channel.id,
            message_id=message.id,
        )
    else:
        fields["type"] = 11
        r = Route("POST", "/channels/{channel_id}/threads", channel_id=channel.id,)

    return (await bot.http.request(r, json=fields, reason=reason))["id"]


async def send_thread_message(
    bot, thread_id: int, content: str, mention_roles: list = [],
):
    """
    Send a message in a thread, allowing pings for roles

    Args:
        bot (Red): The bot object
        thread_id (int): ID of the thread
        content (str): The message to send
        mention_roles (list, optional): List of role ids to allow mentions. Defaults to [].

    Returns:
        int: ID of the new message
    """
    fields = {"content": content, "allowed_mentions": {"roles": mention_roles}}

    r = Route("POST", "/channels/{channel_id}/messages", channel_id=thread_id,)

    return (await bot.http.request(r, json=fields))["id"]


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
