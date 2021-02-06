from .leveler import Leveler

__red_end_user_data_statement__ = "Stores some level info like experience, profile description/picture, and message ID of user's last message in guild."


def setup(bot):
    n = Leveler(bot)
    bot.add_listener(n.listener, "on_message")
    bot.add_cog(n)
