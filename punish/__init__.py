from .punish import Punish

async def setup(bot):
    punish = Punish(bot)
    await punish.initialize()
    bot.add_cog(punish)
