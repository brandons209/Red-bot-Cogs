from .moreadmin import MoreAdmin


def setup(bot):
    bot.add_cog(MoreAdmin(bot))
