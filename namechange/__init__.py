from .namechange import NameChange

__red_end_user_data_statement__ = "This cog does not store user data."


async def setup(bot):
    await bot.add_cog(NameChange(bot))
