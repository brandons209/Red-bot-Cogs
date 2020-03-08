from .roletracker import RoleTracker


async def setup(bot):
    roletracker = RoleTracker(bot)
    await roletracker.initialize()
    bot.add_cog(roletracker)
