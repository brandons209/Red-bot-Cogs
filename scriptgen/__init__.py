from .script import ScriptGen

__red_end_user_data_statement__ = "This cog does not persistently store data or metadata about users."


async def setup(bot):
    await bot.add_cog(ScriptGen(bot))
