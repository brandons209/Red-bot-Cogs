from .trickortreat import TrickorTreat

__red_end_user_data_statement__ = "This doesn't store any user data."


def setup(bot):
    bot.add_cog(TrickorTreat(bot))
