from redbot.core import Config, commands
import re
import random
import string

mention = re.compile("^@|^#|^&")
custom_emoji = re.compile("<:[^:]+:\d{18}>")
vowel = re.compile("^[aeiouAEIOU]")


class Memeify(commands.Cog):
    """Makes things memey."""

    # ------------ common ------------
    def __init__(self, bot):
        super().__init__()

        self.config = Config.get_conf(self, identifier=2934875294, force_registration=True)
        self.bot = bot

    async def __get_content(self, ctx, content):
        if not content:
            msg_c = ""
            # gets previous messages
            msg = await ctx.channel.history(limit=5).flatten()
            for i in msg[1:]:
                if i.clean_content:
                    msg_c = i.clean_content
                    break
            if msg_c:
                return msg_c, False
            else:
                return
        else:
            return ctx.message.clean_content, True

    # ------------ bify ------------
    @commands.command()
    async def bify(self, ctx, *, content: str = None):
        """Replaces all B's with :b:'s"""
        msg_c = await self.__get_content(ctx, content)
        if len(msg_c) != 2:
            await ctx.send("Where's the 🅱️essage?")
        else:
            await ctx.send(self.__bify(*msg_c))

    # takes a clean discord message and replaces all B's and
    # first characters with :b:, unless the word is 1
    # character long, a custon emoji, or a ping. unicode
    # emojis are a bit fucked tho
    def __bify(self, bify_str, cmd) -> str:
        bify = bify_str.split(" ")
        # remove first letter if it bifys the command message itself
        if cmd:
            bify.pop(0)
        b = []
        for i in bify:
            # no code blocks >:(
            i = i.replace("`", "")
            # special cases for custom emojis and mentions
            if custom_emoji.search(i):
                b.append(i + " ")
                continue
            elif mention.match(i):
                b.append(i[0] + self.__bify_f(i[1:]) + " ")
                continue
            # adds the result to the list
            b.append(self.__bify_f(i) + " ")
        return "".join(b)

    def __bify_f(self, bif) -> str:
        if vowel.match(bif) and len(bif) > 1:
            # adds b in front of the word
            bif = "b" + bif
        elif len(bif) > 1:
            # replaces first letter with b
            bif = "b" + bif[1:]
        return bif.replace("b", "🅱️")

    # ------------ frenchify ------------
    @commands.command()
    async def frenchify(self, ctx, *, content: str = None):
        """Writes a message with a french accent"""
        msg_c = await self.__get_content(ctx, content)
        if len(msg_c) != 2:
            await ctx.send("No message")
        else:
            await ctx.send(self.__french_pre_f(*msg_c))

    def __french_pre_f(self, french, cmd):
        emoji_list = []
        if cmd:
            french_cmd_fix = french.split(" ")
            french_str = " ".join(french_cmd_fix[1:])

        emoji_match = re.finditer(custom_emoji, french_str)
        for i in emoji_match:
            emoji_list.append(i.group(0))
        french_list = re.split(custom_emoji, french_str)

        final = []
        for i in french_list:
            final.append(self.__french(i))
            if emoji_list:
                final.append(emoji_list.pop(0))

        return "".join(final)

    def __french(self, text):
        text = text.replace("age", "aje")
        text = text.replace("ale", "aile")
        text = text.replace("ant", "ent")
        text = text.replace("ared", "aired")
        text = text.replace("ay", "ai")
        text = text.replace("blem", "blaim")
        text = text.replace("ble", "buhl")
        text = text.replace("bout", "but")
        text = text.replace("ck", "k")
        text = text.replace("eal", "eahl")
        text = text.replace("ear", "air")
        text = text.replace("ess", "ez")
        text = text.replace("ew", "u")
        text = text.replace("gen", "jen")
        text = text.replace("gon", "jen")
        text = text.replace("ies", "ees")
        text = text.replace("ill", "eehl")
        text = text.replace("ing", "eng")
        text = text.replace("ired", "iaired")
        text = text.replace("ire", "iyaire")
        text = text.replace("ise", "ize")
        text = text.replace("ising", "izeeng")
        text = text.replace("ist", "eest")
        text = text.replace("ith", "iv")
        text = text.replace("it's", "eet eez")
        text = text.replace("i've", "I have")
        text = text.replace("lar", "lair")
        text = text.replace("logic", "lojic")
        text = text.replace("loth", "luth")
        text = text.replace("ment", "mont")
        text = text.replace("ol", "ul")
        text = text.replace("ool", "oo-el")
        text = text.replace("oom", "uhm")
        text = text.replace("orl", "hirl")
        text = text.replace("or", "air")
        text = text.replace("our", "ur")
        text = text.replace("oute", "oote")
        text = text.replace("out", "oot")
        text = text.replace("shion", "she-on")
        text = text.replace("sion", "she-on")
        text = text.replace("some", "zum")
        text = text.replace("stion", "stshe-on")
        text = text.replace("suit", "zoot")
        text = text.replace("them", "zem")
        text = text.replace("thing", "theeng")
        text = text.replace("tion", "she-on")
        text = text.replace("tle", "-tell")
        text = text.replace("ture", "tuair")
        text = text.replace("ty", "tay")
        text = text.replace("ver", "vair")
        text = text.replace("you've", "you have")

        text_arr = text.split(" ")

        for key, word in enumerate(text_arr):

            if self.__compare_format(word) == "hello":
                text_arr[key] = "'allo 'allo"
            elif self.__compare_format(word) == "hi":
                text_arr[key] = "'allo"
            elif self.__compare_format(word) != "hello" and self.__compare_format(word) != "hi":
                if word != "the" and word[:1] == "h":
                    text_arr[key] = "'" + word[1:]

            if self.__compare_format(word) == "i":
                text_arr[key] = "ai"

            if self.__compare_format(word) == "yes":
                text_arr[key] = "oui"
            if self.__compare_format(word) == "no":
                text_arr[key] = "non"

            if self.__compare_format(word) == "mister" or self.__compare_format(word) == "sir":
                text_arr[key] = "Monsieur"
            if (
                self.__compare_format(word) == "miss"
                or self.__compare_format(word) == "missus"
                or self.__compare_format(word) == "madame"
            ):
                text_arr[key] = "Madamoiselle"

            if self.__compare_format(word) == "it":
                text_arr[key] = "eet"
            if self.__compare_format(word) == "is":
                text_arr[key] = "eez"
            if self.__compare_format(word) == "in":
                text_arr[key] = "een"
            if self.__compare_format(word) == "and":
                option = random.randrange(1, 5)
                if option == 1:
                    text_arr[key] = "et"

            if self.__compare_format(word) == "my":
                text_arr[key] = "mon"
            if self.__compare_format(word) == "one":
                text_arr[key] = "un"
            if self.__compare_format(word) == "two":
                text_arr[key] = "deux"

            if self.__compare_format(word)[-2:] == "ly":
                text_arr[key] = word[:-2] + "-lee"
            if self.__compare_format(word)[-3:] == "tre":
                text_arr[key] = word[:-3] + "tair"
            if self.__compare_format(word)[-2:] == "ke":
                text_arr[key] = word[:-2] + "k"

            if self.__compare_format(word) == "the":
                option = random.randrange(1, 4)
                if option == 1:
                    text_arr[key] = "le"
                elif option == 2:
                    text_arr[key] = "la"
                elif option == 3:
                    text_arr[key] = "ze"

            if self.__compare_format(word) == "that":
                text_arr[key] = "zat"
            if self.__compare_format(word) == "they":
                text_arr[key] = "zey"
            if self.__compare_format(word) == "this":
                text_arr[key] = "zis"
            if self.__compare_format(word) == "their":
                text_arr[key] = "zeir"
            if self.__compare_format(word) == "there":
                text_arr[key] = "zere"
            if "er" in self.__compare_format(word) and self.__compare_format(word) != "there":
                text_arr[key] = text_arr[key].replace("er", "air")
            if self.__compare_format(word) == "then":
                text_arr[key] = "zen"
            if self.__compare_format(word) == "these":
                text_arr[key] = "zese"
            if self.__compare_format(word) == "so":
                text_arr[key] = "zo"

            if self.__compare_format(word) == "french":
                text_arr[key] = "francais"

            if self.__compare_format(word) == "shit":
                text_arr[key] = "merde"
            if self.__compare_format(word) == "god":
                text_arr[key] = "Dieu"

        text = " ".join(text_arr)
        text = text.replace("beee", "be-ee")
        text = self.__make_funny_es(text)
        " ".join(w.capitalize() for w in text.split())

        return text

    def __compare_format(self, word):
        word = word.translate(str.maketrans("", "", string.punctuation))
        word = word.lower()
        return word

    def __make_funny_es(self, text):
        bits = text.split("e")
        text = ""

        for bit in bits:
            option = random.randrange(1, 5)
            if option == 4:
                text += bit + "eacute"
            else:
                text += bit + "e"

        text = text.replace("eeacute", "ee")
        text = text.replace("eacutee", "ee")
        text = text.replace("eacuteeacute", "ee")

        if text.endswith("eacute"):
            text = text[:-6]
        elif text.endswith("e"):
            text = text[:-1]

        return text
