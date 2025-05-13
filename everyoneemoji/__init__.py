from .core import EveryoneEmoji

__red_end_user_data_statement__ = "This cog stores no data."


async def setup(bot):
    await bot.add_cog(EveryoneEmoji(bot))
