from .campaign import CampaignCog


async def setup(bot):
    await bot.add_cog(CampaignCog(bot))
