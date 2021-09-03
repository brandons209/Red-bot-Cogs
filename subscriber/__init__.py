from .subscriber import Subscriber

__red_end_user_data_statement__ = "This cog will not store personal data."


def setup(bot):
    bot.add_cog(Subscriber(bot))
