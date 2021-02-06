from .activitylog import ActivityLogger

__red_end_user_data_statement__ = "Depending on setup, can log user messages, voice channel activity, audit actions in guilds, activity statistics per guild, user name changes, and any moderation actions per guild."


async def setup(bot):
    n = ActivityLogger(bot)
    await n.initialize()
    bot.add_cog(n)
