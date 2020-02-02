import os
from .roleplay import RolePlay
from redbot.core import Config


def setup(bot):
    bot.add_cog(RolePlay(bot))
