from .patreon_roles import Patreon

__red_end_user_data_statement__ = "This cog will save data about patreon's subscription history for each user"


async def setup(bot):
    await bot.add_cog(Patreon(bot))
