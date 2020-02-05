from .disable import Disable


def setup(bot):
    bot.add_cog(Disable(bot))
