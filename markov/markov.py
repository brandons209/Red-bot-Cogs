from redbot.core.utils.chat_formatting import *
from redbot.core import Config, checks, commands
import discord
import random


class Markov(commands.Cog):
    """ Generate text based on what your members say per channel"""

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=5989735216541313, force_registration=True)

        default_guild = {"model": {}, "prefixes": [], "max_len": 200}
        self.config.register_guild(**default_guild)

    @commands.group()
    @checks.admin_or_permissions(administrator=True)
    @commands.guild_only()
    async def markovset(self, ctx):
        """ Manage Markov Settings """
        pass

    @markovset.command(name="clear")
    async def markovset_clear(self, ctx, *, channel: discord.TextChannel):
        """ Clear data for a specific channel """
        async with self.config.guild(ctx.guild).model() as model:
            del model[str(channel.id)]

        await ctx.tick()

    @markovset.command(name="prefix")
    async def markovset_prefixes(self, ctx, *, prefixes: str = None):
        """ Set prefixes for bots in your server
        This is so markov won't log bot commands.
        """
        if not prefixes:
            current = await self.config.guild(ctx.guild).prefixes()
            curr = [f"`{p}`" for p in current]
            if not current:
                await ctx.send("No prefixes set, setting this bot's prefix.")
                await self.config.guild(ctx.guild).prefixes.set([ctx.clean_prefix])
                return

            await ctx.send("Current Prefixes: " + humanize_list(curr))
            return

        prefixes = [p for p in prefixes.split(" ")]
        await self.config.guild(ctx.guild).prefixes.set(prefixes)
        prefixes = [f"`{p}`" for p in prefixes]
        await ctx.send("Prefixes set to: " + humanize_list(prefixes))

    @markovset.command(name="len")
    async def markovset_length(self, ctx, length: int = None):
        """
        Set max characters of generated text.

        Max size limited by discord is 3000.
        """
        if not length:
            curr = await self.config.guild(ctx.guild).max_len()
            await ctx.send(f"Current max length of generated text is `{curr}` characters.")
            return

        await self.config.guild(ctx.guild).max_len.set(length)
        await ctx.tick()

    @commands.command(name="markov")
    @commands.guild_only()
    @commands.cooldown(rate=1, per=10, type=commands.BucketType.user)
    @checks.bot_has_permissions(embed_links=True)
    async def markov(self, ctx, *, starting_text: str = None):
        """ Generate text using markov chains!

        Text generated is based on what users say in the current channel
        """
        model = await self.config.guild(ctx.guild).model()
        try:
            model = model[str(ctx.channel.id)]
        except KeyError:
            await ctx.send(error("This channel has no data, try talking in it for a bit first!"))
            return

        last_word = starting_text.split(" ")[-1] if starting_text else None

        if not starting_text:
            markov_text = [random.choice(list(model.keys()))]
        elif not model[last_word]:
            markov_text = [last_word, random.choice(list(model.keys()))]
        else:
            markov_text = [last_word, random.choice(model[last_word])]

        max_len = await self.config.guild(ctx.guild).max_len()

        tries = 0
        max_tries = 20
        while len(markov_text) < max_len and tries < max_tries:
            if "?" in markov_text[-1]:
                break
            if "\r" in markov_text[-1]:
                break
            if "." in markov_text[-1]:
                break
            if "!" in markov_text[-1]:
                break

            # make sure word is in the model and there is data for the word
            if markov_text[-1] in model and model[markov_text[-1]]:
                markov_text.append(random.choice(model[markov_text[-1]]))
            else:
                markov_text.append(random.choice(list(model.keys())))
                tries += 1

        markov_text = " ".join(markov_text)
        member = ctx.author
        embed = discord.Embed(title="Generated Text", description=markov_text, colour=member.colour)

        if member.avatar:
            avatar = member.avatar_url_as(static_format="png")
            embed.set_thumbnail(url=avatar)

        embed.set_footer(text=f"Generated by {member.display_name}")
        await ctx.send(embed=embed)

    # Listener
    @commands.Cog.listener()
    async def on_message(self, message):
        # updates model
        content = message.content
        if not content or message.author == message.guild.me:
            return

        # check if this is a bot message
        prefixes = await self.config.guild(message.guild).prefixes()
        for prefix in prefixes:
            if prefix == content[: len(prefix)]:
                return

        async with self.config.guild(message.guild).model() as model:
            content = content.split(" ")
            try:
                model[str(message.channel.id)]
            except:
                model[str(message.channel.id)] = {}

            for i in range(len(content) - 1):
                if content[i] not in model[str(message.channel.id)]:
                    model[str(message.channel.id)][content[i]] = list()

                model[str(message.channel.id)][content[i]].append(content[i + 1])
