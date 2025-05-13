from .watchlist import Watchlist


async def setup(bot):
    await bot.add_cog(Watchlist(bot))
