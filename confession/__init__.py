from .confession import Confession

__red_end_user_data_statement__ = "This cog won't store anything for a user."


def setup(bot):
    n = Confession()
    bot.add_cog(n)
