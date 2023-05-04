from redbot.core.bot import Red
from .welcome import Welcome

__red_end_user_data_statement__ = "This cog doesn't store any user data."


async def setup(bot: Red):
    await bot.add_cog(Welcome(bot=bot))
