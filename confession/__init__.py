from .confession import Confession

__red_end_user_data_statement__ = "This cog won't store anything for a user."


async def setup(bot):
    n = Confession()
    await bot.add_cog(n)
