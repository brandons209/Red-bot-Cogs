from .isolate import Isolate

__red_end_user_data_statement__ = "This cog stores members who are currently isolated for moderation purposes."


async def setup(bot):
    isolate = Isolate(bot)
    await isolate.initialize()
    bot.add_cog(isolate)
