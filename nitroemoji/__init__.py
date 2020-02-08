from .nitroemoji import NitroEmoji


async def setup(bot):
    n = NitroEmoji(bot)
    await n.initialize()
    bot.add_cog(n)
