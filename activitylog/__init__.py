from .activitylog import ActivityLogger


async def setup(bot):
    n = ActivityLogger(bot)
    await n.initialize()
    bot.add_cog(n)
