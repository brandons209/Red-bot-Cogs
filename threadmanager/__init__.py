from .thread_manager import ThreadManager

__red_end_user_data_statement__ = "This doesn't store any user data."


async def setup(bot):
    await bot.add_cog(ThreadManager(bot))
