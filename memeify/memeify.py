from redbot.core import Config, commands
import re


class Memeify(commands.Cog):
    """Makes things memey."""

    def __init__(self, bot):
        super().__init__()

        self.config = Config.get_conf(self, identifier=2934875294, force_registration=True)
        self.bot = bot

    @commands.command()
    async def b(self, ctx, *, content: str = None):
        """Replaces all B's with :b:'s"""
        if not content:
            msg_c = ""
            # gets previous messages
            msg = await ctx.channel.history(limit=5).flatten()
            for i in msg[1:]:
                if i.clean_content:
                    msg_c = i.clean_content
                    break
            if msg_c:
                await ctx.send(self.__bify(msg_c, False))
            else:
                await ctx.send("Where's the 🅱️essage?")
        else:
            await ctx.send(self.__bify(ctx.message.clean_content, True))

    # takes a clean discord message and replaces all B's and
    # first characters with :b:, unless the word is 1
    # character long, a custon emoji, or a ping. unicode
    # emojis are a bit fucked tho
    def __bify(self, bify_str, cmd) -> str:
        mention = re.compile("^@|^#|^&")
        bify = bify_str.split()
        # remove first letter if it bifys the command message itself
        if cmd:
            bify.pop(0)
        b = []
        for i in bify:
            # no code blocks >:(
            i = i.replace("`", "")
            # special cases for custom emojis and mentions
            if i[0] == ":" and i[-1] == ":":
                b.append(i + " ")
                continue
            elif mention.match(i):
                b.append(i[0] + self.__bify_f(i[1:]) + " ")
                continue
            # adds the result to the list
            b.append(self.__bify_f(i) + " ")
        return "".join(b)

    def __bify_f(self, bif) -> str:
        vowel = re.compile("^[aeiouAEIOU]")
        if vowel.match(bif) and len(bif) > 1:
            # adds b in front of the word
            bif = "b" + bif
        elif len(bif) > 1:
            # replaces first letter with b
            bif = "b" + bif[1:]
        return bif.replace("b", "🅱️")
