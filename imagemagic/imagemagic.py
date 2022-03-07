import aiohttp, discord
from redbot.core import Config, commands
from wand.image import Image
from io import BytesIO
from typing import Optional, Tuple, Literal
import asyncio, functools, urllib

MAX_SIZE = 8 * 1024 * 1024

# by Flame442
class ImageFindError(Exception):
    """Generic error for the __get_image function."""

    pass


class ImageMagic(commands.Cog):
    def __init__(self, bot):
        super().__init__()

        self.config = Config.get_conf(self, identifier=4928034571, force_registration=True)
        self.bot = bot

    async def _get_image(self, ctx, link: str = None) -> Image:
        if ctx.guild:
            max_filesize = ctx.guild.filesize_limit
        else:
            max_filesize = MAX_SIZE

        # original by Flame442, edited for Wand by ScriptPony
        if not ctx.message.attachments and not link:
            # first check for reply message
            if ctx.message.reference:
                msg = ctx.message.reference.resolved
                if msg is None:
                    msg = await ctx.channel.fetch_message(ctx.message.reference.message_id)
                if msg and msg.attachments:
                    for a in msg.attachments:
                        path = urllib.parse.urlparse(a.url).path
                        link = a.url
                        break

            if not link:
                async for msg in ctx.channel.history(limit=10):
                    for a in msg.attachments:
                        path = urllib.parse.urlparse(a.url).path
                        link = a.url
                        break
                    if link:
                        break
            if not link:
                raise ImageFindError("Please provide an attachment.")
        if link:  # linked image
            path = urllib.parse.urlparse(link).path
            async with aiohttp.ClientSession() as session:
                try:
                    async with session.get(link) as response:
                        r = await response.read()
                        try:
                            img = Image(file=BytesIO(r))
                        except:
                            raise ImageFindError("Invalid filetype")
                except (OSError, aiohttp.ClientError):
                    raise ImageFindError("An image could not be found. Make sure you provide a direct link.")
        else:  # attached image
            path = urllib.parse.urlparse(ctx.message.attachments[0].url).path
            if ctx.message.attachments[0].size > max_filesize:
                raise ImageFindError("That image is too large.")
            temp_orig = BytesIO()
            await ctx.message.attachments[0].save(temp_orig)
            temp_orig.seek(0)
            try:
                img = Image(file=temp_orig)
            except:
                raise ImageFindError("Invalid filetype")

        return img

    @staticmethod
    def _intensity(intensity: float) -> float:
        if intensity < 0:
            intensity = 0
        elif intensity > 10:
            intensity = 10
        intensity /= 10
        return intensity

    def _distortion(self, img: Image, func: str, args: Tuple) -> Tuple[Image, str]:
        # distort
        img.iterator_reset()
        function = getattr(img, func, None)
        if function is None:
            return

        function(*args)
        if img.animation:
            while img.iterator_next():
                function(*args)

        # image object and filename
        return img, (f"{func}." + img.mimetype[img.mimetype.find("/") + 1 :])

    async def _command_body(self, ctx, args: Tuple):
        task = functools.partial(*args)
        task = self.bot.loop.run_in_executor(None, task)
        try:
            img, name = await asyncio.wait_for(task, timeout=60)
        except asyncio.TimeoutError:
            await ctx.reply("The image took too long to process.", mention_author=False)
            return

        try:
            await ctx.reply(file=discord.File(BytesIO(img.make_blob()), name), mention_author=False)
        except discord.errors.HTTPException:
            await ctx.reply("That image is too large.", mention_author=False)
            return

    @commands.group()
    @commands.bot_has_permissions(attach_files=True)
    async def distort(self, ctx):
        """
        Distorts an image from a direct link, attatchment, or from recent chat messages

        `[p]distort <distort type> <intensity (1-10) (optional)> <image link>`
        """
        pass

    @distort.command()
    async def barrel(self, ctx, intensity: Optional[float] = 10, *, link: str = None):

        """
        Bulges the center of the image outward
        """
        intensity = self._intensity(intensity)
        amount = 0.3
        async with ctx.typing():
            try:
                img = await self._get_image(ctx, link)
            except ImageFindError as e:
                return await ctx.reply(e, mention_author=False)

            await self._command_body(
                ctx,
                args=(
                    self._distortion,
                    img,
                    "distort",
                    ("barrel", (amount * intensity, amount * intensity, amount * intensity, 0)),
                ),
            )

    @distort.command()
    async def implode(self, ctx, intensity: Optional[float] = 10, *, link: str = None):
        """
        Pinches in the center of the image
        """
        intensity = self._intensity(intensity)
        amount = 0.6
        async with ctx.typing():
            try:
                img = await self._get_image(ctx, link)
            except ImageFindError as e:
                return await ctx.reply(e, mention_author=False)

            await self._command_body(ctx, args=(self._distortion, img, "implode", (amount * intensity,)))

    @distort.command()
    async def swirl(self, ctx, intensity: Optional[float] = 10, *, link: str = None):
        """
        Swirls the center of the image
        """

        switch = {0: 0, 1: 18, 2: 36, 3: 54, 4: 72, 5: 90, 6: 108, 7: 126, 8: 144, 9: 162, 10: 180}
        intensity = float(switch.get(round(intensity), 180))

        async with ctx.typing():
            try:
                img = await self._get_image(ctx, link)
            except ImageFindError as e:
                return await ctx.reply(e, mention_author=False)

            await self._command_body(ctx, args=(self._distortion, img, "swirl", (intensity,)))

    @distort.command()
    async def charcoal(self, ctx, intensity: Optional[float], *, link: str = None):
        """
        Makes the image look somewhat like it was drawn with charcoal
        """

        async with ctx.typing():
            try:
                img = await self._get_image(ctx, link)
            except ImageFindError as e:
                return await ctx.reply(e, mention_author=False)

            await self._command_body(ctx, args=(self._distortion, img, "charcoal", (1.5, 0.5)))

    @distort.command()
    async def sketch(self, ctx, intensity: Optional[float], *, link: str = None):
        """
        Makes the image look like it is a sketch
        """

        async with ctx.typing():
            try:
                img = await self._get_image(ctx, link)
            except ImageFindError as e:
                return await ctx.reply(e, mention_author=False)

            await self._command_body(ctx, args=(self._distortion, img, "sketch", (0.5, 0.0, 98.0)))

    @distort.command()
    async def zoom(self, ctx, intensity: Optional[float], *, link: str = None):
        """
        Zooms in on the center of an image
        """

        async with ctx.typing():
            try:
                img = await self._get_image(ctx, link)
            except ImageFindError as e:
                return await ctx.reply(e, mention_author=False)

            h = img.height
            w = img.width
            img = self._distortion(img, "transform", (f"{w}x{h}", "150%"))[0]

            await self._command_body(ctx, args=(self._distortion, img, "transform", (f"{w/1.5}x{h/1.5}+{w/2}+{h/2}",)))


async def red_delete_data_for_user(
    self,
    *,
    requester: Literal["discord_deleted_user", "owner", "user", "user_strict"],
    user_id: int,
):
    pass
