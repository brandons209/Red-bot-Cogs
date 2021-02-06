from . import core

__red_end_user_data_statement__ = "This cog only stores internal variables per user."

def setup(bot):
    bot.add_cog(core.EconomyTrickle(bot))
