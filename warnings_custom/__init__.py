from .warnings import Warnings_Custom


def setup(bot):
    bot.add_cog(Warnings_Custom(bot))
