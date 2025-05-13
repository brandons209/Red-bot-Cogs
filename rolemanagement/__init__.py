from .core import RoleManagement

__red_end_user_data_statement__ = "This will only store birthdays, sticky, and subscribed roles for users."


async def setup(bot):
    cog = RoleManagement(bot)
    await bot.add_cog(cog)
    cog.init()
