from .core import EveryoneEmoji


def setup(bot):
    bot.add_cog(EveryoneEmoji(bot))
