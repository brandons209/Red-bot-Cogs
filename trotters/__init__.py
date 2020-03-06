from .trotters import Trotters


async def setup(bot):
    trotters = Trotters(bot)
    await trotters.initialize()
    bot.add_cog(trotters)
