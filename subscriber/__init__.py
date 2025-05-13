from .subscriber import Subscriber

__red_end_user_data_statement__ = "This cog will not store personal data."


async def setup(bot):
    await bot.add_cog(Subscriber(bot))
