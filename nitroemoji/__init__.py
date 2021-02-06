from .nitroemoji import NitroEmoji

__red_end_user_data_statement__ = "This cog will store a user's custom emojis in each guild."


async def setup(bot):
    n = NitroEmoji(bot)
    await n.initialize()
    bot.add_cog(n)
