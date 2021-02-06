from .shootout import Shootout

__red_end_user_data_statement__ = "This cog won't store anything for a user."


def setup(bot):
    bot.add_cog(Shootout(bot))
