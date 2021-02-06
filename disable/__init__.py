from .disable import Disable

__red_end_user_data_statement__ = "This cog won't store any data for users."


def setup(bot):
    bot.add_cog(Disable(bot))
