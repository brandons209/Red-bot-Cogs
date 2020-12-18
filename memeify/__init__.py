from .memeify import Memeify


def setup(bot):
    bot.add_cog(Memeify(bot))
