import os
from .pony import Pony
from redbot.core import Config

def setup(bot):
    bot.add_cog(Pony())
