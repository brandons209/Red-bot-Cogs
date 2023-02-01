from .core import RoleManagement

__red_end_user_data_statement__ = "This will only store birthdays, sticky, and subscribed roles for users."


def setup(bot):
    cog = RoleManagement(bot)
    bot.add_cog(cog)
    cog.init()
