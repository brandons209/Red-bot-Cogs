
from .birthday import Birthdays


def setup(bot):
    bot.add_cog(Birthdays(bot))
