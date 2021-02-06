from .reactpoll import ReactPoll

__red_end_user_data_statement__ = "This cog won't store user data."

def setup(bot):
    n = ReactPoll(bot)
    bot.add_cog(n)
