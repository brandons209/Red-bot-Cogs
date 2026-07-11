from .antibot import AntiBot

__red_end_user_data_statement__ = (
    "This cog stores per-guild moderation configuration, per-member automated-action "
    "timestamps and counters, and learned bot 'signatures' consisting of hashes/fingerprints "
    "of avatar, message, and role features. No verbatim message content is retained. "
    "Per-member data can be cleared by removing the member's guild data."
)


async def setup(bot):
    cog = AntiBot(bot)
    await bot.add_cog(cog)
    await cog.initialize()
