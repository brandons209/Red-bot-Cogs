from .punish import Punish

__red_end_user_data_statement__ = "This will store who is currently punished in each guild."

async def setup(bot):
    punish = Punish(bot)
    await punish.initialize()
    bot.add_cog(punish)
