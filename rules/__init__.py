from .rules import Rules

__red_end_user_data_statement__ = "This only stores rules added by admins of guilds."


def setup(bot):
    bot.add_cog(Rules(bot))
