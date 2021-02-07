from .moreadmin import MoreAdmin

__red_end_user_data_statement__ = "This will store a user's last few messages (depending on configuration), and also notes made by mods/admins on user."


def setup(bot):
    bot.add_cog(MoreAdmin(bot))
