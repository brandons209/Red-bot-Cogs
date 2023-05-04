from .timehelper import TimeHelper

__red_end_user_data_statement__ = "This cog stores a user's timezone, if set by the user."


async def setup(bot):
    await bot.add_cog(TimeHelper(bot))
