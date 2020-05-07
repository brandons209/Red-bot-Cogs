from .rules import Rules


def setup(bot):
    bot.add_cog(Rules(bot))
