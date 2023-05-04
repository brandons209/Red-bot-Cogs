from .roletracker import RoleTracker

__red_end_user_data_statement__ = "This cog stores the users who have a trackable role."


async def setup(bot):
    roletracker = RoleTracker(bot)
    await roletracker.initialize()
    await bot.add_cog(roletracker)
