from .shootout import Shootout

__red_end_user_data_statement__ = "This cog won't store anything for a user."


async def setup(bot):
    await bot.add_cog(Shootout(bot))
