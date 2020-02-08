from .isolate import Isolate


async def setup(bot):
    isolate = Isolate(bot)
    await isolate.initialize()
    bot.add_cog(isolate)
