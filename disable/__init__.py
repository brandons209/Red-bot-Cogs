from .disable import Disable

__red_end_user_data_statement__ = "This cog won't store any data for users."


async def setup(bot):
    await bot.add_cog(Disable(bot))
