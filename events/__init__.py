from .events import Events


def setup(bot):
    n = Events(bot)
    bot.add_cog(n)
    bot.loop.create_task(n.update_events())
