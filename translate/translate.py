import discord
import logging
from typing import Optional, Union

from discord.ext.commands.errors import BadArgument
from redbot.core import Config, checks, commands, version_info, VersionInfo
from redbot.core.i18n import Translator, cog_i18n
from redbot.core.utils.chat_formatting import humanize_list, error

from .api import FlagTranslation, GoogleTranslateAPI
from .converters import ChannelUserRole
from .errors import GoogleTranslateAPIError

"""
Translator cog

Cog credit to aziz#5919 for the idea and

Links

Wiki                                                https://goo.gl/3fxjSA
GitHub                                              https://goo.gl/oQAQde
Support the developer                               https://goo.gl/Brchj4
Invite the bot to your guild                       https://goo.gl/aQm2G7
Join the official development guild                https://discord.gg/uekTNPj
"""

BASE_URL = "https://translation.googleapis.com"
_ = Translator("Translate", __file__)
log = logging.getLogger("red.trusty-cogs.Translate")


@cog_i18n(_)
class Translate(GoogleTranslateAPI, commands.Cog):
    """
    Translate messages using Google Translate
    """

    __author__ = ["Aziz", "TrustyJAID"]
    __version__ = "2.3.7"

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, 156434873547585, force_registration=True)
        default_guild = {
            "reaction": False,
            "text": False,
            "whitelist": [],
            "blacklist": [],
            "count": {"characters": 0, "requests": 0, "detect": 0},
            "autosend": [],
        }
        default = {
            "cooldown": {"past_flags": [], "timeout": 0, "multiple": False},
            "count": {"characters": 0, "requests": 0, "detect": 0},
        }
        self.config.register_guild(**default_guild)
        self.config.register_global(**default)
        self.cache = {
            "translations": [],
            "cooldown_translations": {},
            "guild_messages": [],
            "guild_reactions": [],
            "cooldown": {},
            "guild_blacklist": {},
            "guild_whitelist": {},
            "autolangs": {},
        }
        self._key: Optional[str] = None
        self._clear_cache = self.bot.loop.create_task(self.cleanup_cache())
        self._save_loop = self.bot.loop.create_task(self.save_usage())
        self._guild_counter = {}
        self._global_counter = {}

    def format_help_for_context(self, ctx: commands.Context) -> str:
        """
        Thanks Sinbad!
        """
        pre_processed = super().format_help_for_context(ctx)
        return f"{pre_processed}\n\nCog Version: {self.__version__}"

    async def red_delete_data_for_user(self, **kwargs):
        """
        Nothing to delete
        """
        return

    async def init(self) -> None:
        try:
            key = await self.config.api_key()
        except AttributeError:
            return
        try:
            central_key = await self.bot.get_shared_api_tokens("google_translate")
        except AttributeError:
            # Red 3.1 support
            central_key = await self.bot.db.api_tokens.get_raw("google_translate", default={})
        if not central_key:
            try:
                await self.bot.set_shared_api_tokens("google_translate", api_key=key)
            except AttributeError:
                await self.bot.db.api_tokens.set_raw("google_translate", value={"api_key": key})
        await self.config.api_key.clear()
        self._global_counter = await self.config.count()
        all_guilds = await self.config.all_guilds()
        for g_id, data in all_guilds.items():
            self._guild_counter[g_id] = data["count"]

    @commands.command()
    async def translate(
        self,
        ctx: commands.Context,
        to_language: FlagTranslation,
        *,
        message: Union[discord.Message, str],
    ) -> None:
        """
        Translate messages with Google Translate

        `<to_language>` is the language you would like to translate
        `<message>` is the message to translate, this can be words you want
        to translate, a channelID-messageID from SHIFT + clicking a message and copying ID,
        a message ID from the current channel, or message link
        """
        if not await self._get_google_api_key():
            msg = _("The bot owner needs to set an api key first!")
            await ctx.send(msg)
            return
        author = ctx.message.author
        requestor = ctx.message.author
        msg = ctx.message
        if isinstance(message, discord.Message):
            msg = message
            author = message.author
            message = message.clean_content
        try:
            detected_lang = await self.detect_language(message)
            await self.add_detect(ctx.guild)
        except GoogleTranslateAPIError as e:
            await ctx.send(str(e))
            return

        original_lang = detected_lang[0][0]["language"]
        embeds = None
        msg_trans = f"**{original_lang}:** {message}\n"
        # can only do up to 25 sections for embed
        for to_lang in to_language[:24]:
            if to_lang == original_lang:
                if len(to_language) == 1:
                    return await ctx.send(
                        _("I cannot translate `{from_lang}` to `{to}`").format(from_lang=original_lang, to=to_lang)
                    )
                else:
                    continue
            try:
                translated_text = await self.translate_text(original_lang, to_lang, message)
                await self.add_requests(ctx.guild, message)
            except GoogleTranslateAPIError as e:
                await ctx.send(str(e))
                return

            if ctx.channel.permissions_for(ctx.me).embed_links:
                translation = (translated_text, original_lang, to_lang)
                if embeds is None:
                    embeds = discord.Embed(colour=author.colour, description=f"**FROM:** {original_lang}")
                    embeds.set_author(name=author.display_name + _(" said:"), icon_url=str(author.avatar_url))
                    embeds.set_footer(text=f"Requested by {author}")
                    embeds.add_field(name=original_lang, value=message, inline=False)
                    # inline is false for horizontal spacing instead 3 at once in a line
                    embeds.add_field(name=to_lang, value=translated_text, inline=False)
                else:
                    embeds.add_field(name=to_lang, value=translated_text, inline=False)
            else:
                msg_trans += f"**{to_lang}**: {translated_text}\n"

        if embeds is not None:
            if version_info >= VersionInfo.from_str("3.4.6") and msg.channel.id == ctx.channel.id:
                await ctx.send(embed=embeds, reference=msg, mention_author=False)
            else:
                await ctx.send(embed=embeds)
        else:
            if version_info >= VersionInfo.from_str("3.4.6") and msg.channel.id == ctx.channel.id:
                await ctx.send(msg_trans, reference=msg, mention_author=False)
            else:
                await ctx.send(msg_trans)

    @commands.group()
    async def translateset(self, ctx: commands.Context) -> None:
        """
        Toggle the bot auto translating
        """
        pass

    @translateset.group(name="auto")
    async def translate_auto(self, ctx):
        """
        Set channels to auto translate messages from and to
        """
        pass

    @translate_auto.command(name="add")
    async def translate_auto_add(self, ctx: commands.Context, languages: str, *links: discord.TextChannel) -> None:
        """
        Set channels to auto translate messages from and to

        All channels will be linked together, that is every channel's messages will be translated to every other channel.

        Languages should be the **receive language** that every message sent to it should be translated to.

        **languages** should be a comma seperated list of languages with no spaces matching the links!
        """
        langs = [l.strip() for l in languages.strip().split(",")]
        if len(langs) != len(links):
            return await ctx.send(error("The number of lanuages and link channels don't match!"), delete_after=30)

        async with self.config.guild(ctx.guild).autosend() as autosend:
            autosend.append({l.id: lang for l, lang in zip(links, langs)})

        await ctx.tick()

    @translate_auto.command(name="del")
    async def translate_auto_del(self, ctx: commands.Context, *links: discord.TextChannel) -> None:
        """
        Delete linked channels
        """
        if not links:
            await ctx.send("Please specify the channel links.")
            return

        links = {r.id for r in links}
        async with self.config.guild(ctx.guild).autosend() as autosend:
            to_delete_i = -1
            for i, channels in enumerate(autosend):
                ch = {int(k) for k in channels.keys()}
                if ch == links:
                    to_delete_i = i
                    break

            del autosend[to_delete_i]

        await ctx.tick()

    @translateset.command(name="stats")
    async def translate_stats(self, ctx: commands.Context, guild_id: Optional[int]):
        """
        Shows translation usage
        """
        if guild_id and not await self.bot.is_owner(ctx.author):
            return await ctx.send(_("That is only available for the bot owner."))
        elif guild_id and await self.bot.is_owner(ctx.author):
            if not (guild := self.bot.get_guild(guild_id)):
                return await ctx.send(_("Guild `{guild_id}` not found.").format(guild_id=guild_id))
        else:
            guild = ctx.guild
        tr_keys = {
            "requests": _("API Requests:"),
            "detect": _("API Detect Language:"),
            "characters": _("Characters requested:"),
        }
        count = (
            self._guild_counter[guild.id] if guild.id in self._guild_counter else await self.config.guild(guild).count()
        )
        gl_count = self._global_counter if self._global_counter else await self.config.count()
        msg = _("__Global Usage__:\n")
        for key, value in gl_count.items():
            msg += tr_keys[key] + f" **{value}**\n"
        msg += _("__{guild} Usage__:\n").format(guild=guild.name)
        for key, value in count.items():
            msg += tr_keys[key] + f" **{value}**\n"
        await ctx.maybe_send_embed(msg)

    @translateset.group(aliases=["blocklist"])
    @checks.mod_or_permissions(manage_messages=True)
    @commands.guild_only()
    async def blacklist(self, ctx: commands.Context) -> None:
        """
        Set blacklist options for translations

        blacklisting supports channels, users, or roles
        """
        pass

    @translateset.group(aliases=["allowlist"])
    @checks.mod_or_permissions(manage_messages=True)
    @commands.guild_only()
    async def whitelist(self, ctx: commands.Context) -> None:
        """
        Set whitelist options for translations

        whitelisting supports channels, users, or roles
        """
        pass

    @whitelist.command(name="add")
    @checks.mod_or_permissions(manage_messages=True)
    @commands.guild_only()
    async def whitelist_add(self, ctx: commands.Context, *channel_user_role: ChannelUserRole) -> None:
        """
        Add a channel, user, or role to translation whitelist
        """
        if len(channel_user_role) < 1:
            return await ctx.send(_("You must supply 1 or more channels users or roles to be whitelisted."))
        for obj in channel_user_role:
            if obj.id not in await self.config.guild(ctx.guild).whitelist():
                async with self.config.guild(ctx.guild).whitelist() as whitelist:
                    whitelist.append(obj.id)
                await self._bw_list_cache_update(ctx.guild)
        msg = _("`{list_type}` added to translation whitelist.")
        list_type = humanize_list([c.name for c in channel_user_role])
        await ctx.send(msg.format(list_type=list_type))

    @whitelist.command(name="remove", aliases=["rem", "del"])
    @checks.mod_or_permissions(manage_messages=True)
    @commands.guild_only()
    async def whitelist_remove(self, ctx: commands.Context, *channel_user_role: ChannelUserRole) -> None:
        """
        Remove a channel, user, or role from translation whitelist
        """
        if len(channel_user_role) < 1:
            return await ctx.send(
                _("You must supply 1 or more channels, users, " "or roles to be removed from the whitelist")
            )
        for obj in channel_user_role:
            if obj.id in await self.config.guild(ctx.guild).whitelist():
                async with self.config.guild(ctx.guild).whitelist() as whitelist:
                    whitelist.remove(obj.id)
                await self._bw_list_cache_update(ctx.guild)
        msg = _("`{list_type}` removed from translation whitelist.")
        list_type = humanize_list([c.name for c in channel_user_role])
        await ctx.send(msg.format(list_type=list_type))

    @whitelist.command(name="list")
    @checks.mod_or_permissions(manage_messages=True)
    @commands.guild_only()
    async def whitelist_list(self, ctx: commands.Context) -> None:
        """
        List Channels, Users, and Roles in the servers translation whitelist.
        """
        whitelist = []
        for _id in await self.config.guild(ctx.guild).whitelist():
            try:
                whitelist.append(await ChannelUserRole().convert(ctx, str(_id)))
            except BadArgument:
                continue
        whitelist_s = ", ".join(x.name for x in whitelist)
        await ctx.send(_("`{whitelisted}` are currently whitelisted.").format(whitelisted=whitelist_s))

    @blacklist.command(name="add")
    @checks.mod_or_permissions(manage_messages=True)
    @commands.guild_only()
    async def blacklist_add(self, ctx: commands.Context, *channel_user_role: ChannelUserRole) -> None:
        """
        Add a channel, user, or role to translation blacklist
        """
        if len(channel_user_role) < 1:
            return await ctx.send(_("You must supply 1 or more channels users or roles to be blacklisted."))
        for obj in channel_user_role:
            if obj.id not in await self.config.guild(ctx.guild).blacklist():
                async with self.config.guild(ctx.guild).blacklist() as blacklist:
                    blacklist.append(obj.id)
                await self._bw_list_cache_update(ctx.guild)
        msg = _("`{list_type}` added to translation blacklist.")
        list_type = humanize_list([c.name for c in channel_user_role])
        await ctx.send(msg.format(list_type=list_type))

    @blacklist.command(name="remove", aliases=["rem", "del"])
    @checks.mod_or_permissions(manage_messages=True)
    @commands.guild_only()
    async def blacklist_remove(self, ctx: commands.Context, *channel_user_role: ChannelUserRole) -> None:
        """
        Remove a channel, user, or role from translation blacklist
        """
        if len(channel_user_role) < 1:
            return await ctx.send(
                _("You must supply 1 or more channels, users, " "or roles to be removed from the blacklist")
            )
        for obj in channel_user_role:
            if obj.id in await self.config.guild(ctx.guild).blacklist():
                async with self.config.guild(ctx.guild).blacklist() as blacklist:
                    blacklist.remove(obj.id)
                await self._bw_list_cache_update(ctx.guild)
        msg = _("`{list_type}` removed from translation blacklist.")
        list_type = humanize_list([c.name for c in channel_user_role])
        await ctx.send(msg.format(list_type=list_type))

    @blacklist.command(name="list")
    @checks.mod_or_permissions(manage_messages=True)
    @commands.guild_only()
    async def blacklist_list(self, ctx: commands.Context) -> None:
        """
        List Channels, Users, and Roles in the servers translation blacklist.
        """
        blacklist = []
        for _id in await self.config.guild(ctx.guild).blacklist():
            try:
                blacklist.append(await ChannelUserRole().convert(ctx, str(_id)))
            except BadArgument:
                continue
        blacklist_s = ", ".join(x.name for x in blacklist)
        await ctx.send(_("`{blacklisted}` are currently blacklisted.").format(blacklisted=blacklist_s))

    @translateset.command(aliases=["reaction", "reactions"])
    @checks.mod_or_permissions(manage_channels=True)
    @commands.guild_only()
    async def react(self, ctx: commands.Context) -> None:
        """
        Toggle translations to flag emoji reactions
        """
        guild = ctx.message.guild
        toggle = not await self.config.guild(guild).reaction()
        if toggle:
            verb = _("on")
        else:
            verb = _("off")
            if guild.id in self.cache["guild_reactions"]:
                self.cache["guild_reactions"].remove(guild.id)
        await self.config.guild(guild).reaction.set(toggle)
        msg = _("Reaction translations have been turned ")
        await ctx.send(msg + verb)

    @translateset.command(aliases=["multi"])
    @checks.is_owner()
    @commands.guild_only()
    async def multiple(self, ctx: commands.Context) -> None:
        """
        Toggle multiple translations for the same message

        This will also ignore the translated message from
        being translated into another language
        """
        toggle = not await self.config.cooldown.multiple()
        if toggle:
            verb = _("on")
        else:
            verb = _("off")
        await self.config.cooldown.multiple.set(toggle)
        self.cache["cooldown"] = await self.config.cooldown()
        msg = _("Multiple translations have been turned ")
        await ctx.send(msg + verb)

    @translateset.command(aliases=["cooldown"])
    @checks.is_owner()
    @commands.guild_only()
    async def timeout(self, ctx: commands.Context, time: int) -> None:
        """
        Set the cooldown before a message can be reacted to again
        for translation

        `<time>` Number of seconds until that message can be reacted to again
        Note: If multiple reactions are not allowed the timeout setting
        is ignored until the cache cleanup ~10 minutes.
        """
        await self.config.cooldown.timeout.set(time)
        self.cache["cooldown"] = await self.config.cooldown()
        msg = _("Translation timeout set to {time}s.").format(time=time)
        await ctx.send(msg)

    @translateset.command(aliases=["flags"])
    @checks.mod_or_permissions(manage_channels=True)
    @commands.guild_only()
    async def flag(self, ctx: commands.Context) -> None:
        """
        Toggle translations with flag emojis in text
        """
        guild = ctx.message.guild
        toggle = not await self.config.guild(guild).text()
        if toggle:
            verb = _("on")
        else:
            verb = _("off")
            if guild.id in self.cache["guild_messages"]:
                self.cache["guild_messages"].remove(guild.id)
        await self.config.guild(guild).text.set(toggle)
        msg = _("Flag emoji translations have been turned ")
        await ctx.send(msg + verb)

    @translateset.command()
    @checks.is_owner()
    async def creds(self, ctx: commands.Context) -> None:
        """
        You must get an API key from Google to set this up

        Note: Using this cog costs money, current rates are $20 per 1 million characters.
        """
        msg = _(
            "1. Go to Google Developers Console and log in with your Google account."
            "(https://console.developers.google.com/)\n"
            "2. You should be prompted to create a new project (name does not matter).\n"
            "3. Click on Enable APIs and Services at the top.\n"
            "4. In the list of APIs choose or search for Cloud Translate API and click on it."
            "Choose Enable.\n"
            "5. Click on Credentials on the left navigation bar.\n"
            "6. Click on Create Credential at the top.\n"
            '7. At the top click the link for "API key".\n'
            "8. No application restrictions are needed. Click Create at the bottom.\n"
            "9. You now have a key to add to \n"
            "`{prefix}set api google_translate api_key,YOUR_KEY_HERE`\n"
        ).format(prefix=ctx.prefix)
        await ctx.maybe_send_embed(msg)

    def cog_unload(self):
        self._clear_cache.cancel()
        self._save_loop.cancel()
        self.bot.loop.create_task(self._save_usage_stats())

    __unload = cog_unload
