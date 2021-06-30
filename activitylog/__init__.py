from .activitylog import ActivityLogger

__red_end_user_data_statement__ = "Depending on setup, can log user messages, voice channel activity, audit actions in guilds, activity statistics per guild, user name changes, and any moderation actions per guild."


def setup(bot):
    n = ActivityLogger(bot)
    bot.add_cog(n)
