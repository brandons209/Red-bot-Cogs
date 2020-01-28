from .reactpoll import ReactPoll


def setup(bot):
    n = ReactPoll(bot)
    bot.add_cog(n)
