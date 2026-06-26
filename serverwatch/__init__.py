from .serverwatch import ServerWatch

__red_end_user_data_statement__ = (
    "This cog does not store personal data. It stores game server connection details "
    "(host/port) and notification settings configured by server admins."
)


async def setup(bot):
    await bot.add_cog(ServerWatch(bot))
