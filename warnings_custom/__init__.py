from .warnings import Warnings_Custom


async def setup(bot):
    await bot.add_cog(Warnings_Custom(bot))
