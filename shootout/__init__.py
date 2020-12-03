from .shootout import Shootout


def setup(bot):
    bot.add_cog(Shootout(bot))
