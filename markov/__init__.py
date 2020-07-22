from .markov import Markov


def setup(bot):
    bot.add_cog(Markov(bot))
