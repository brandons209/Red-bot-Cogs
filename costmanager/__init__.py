from .manager import CostManager

def setup(bot):
    bot.add_cog(CostManager(bot))
