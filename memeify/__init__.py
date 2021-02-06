from .memeify import Memeify

__red_end_user_data_statement__ = "This cog does not store user data."

def setup(bot):
    bot.add_cog(Memeify(bot))
