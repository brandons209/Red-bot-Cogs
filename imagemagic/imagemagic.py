import aiohttp, discord
from redbot.core import Config, commands
from wand.image import Image
from io import BytesIO
from typing import Optional, Tuple, Literal
import asyncio, functools
from PIL import Image as PILImage
from PIL import ImageEnhance

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

    async def _get_image(self, ctx, link: Optional[str] = None) -> Image:
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
                        link = a.url
                        break

            if not link:
                async for msg in ctx.channel.history(limit=10):
                    for a in msg.attachments:
                        link = a.url
                        break
                    if link:
                        break
            if not link:
                raise ImageFindError("Please provide an attachment.")
        if link:  # linked image
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

    @staticmethod
    def _fry(img):
        e = ImageEnhance.Sharpness(img)
        img = e.enhance(100)
        e = ImageEnhance.Contrast(img)
        img = e.enhance(100)
        e = ImageEnhance.Brightness(img)
        img = e.enhance(0.27)
        r, b, g = img.split()
        e = ImageEnhance.Brightness(r)
        r = e.enhance(4)
        e = ImageEnhance.Brightness(g)
        g = e.enhance(1.75)
        e = ImageEnhance.Brightness(b)
        b = e.enhance(0.6)
        img = Image.merge("RGB", (r, g, b))
        e = ImageEnhance.Brightness(img)
        img = e.enhance(1.5)
        temp = BytesIO()
        temp.name = "deepfried.png"
        img.save(temp)
        temp.seek(0)
        return temp, temp.name

    @staticmethod
    def _videofry(img, duration):
        imgs = []
        frame = 0
        while img:
            i = img.copy()
            i = i.convert("RGB")
            e = ImageEnhance.Sharpness(i)
            i = e.enhance(100)
            e = ImageEnhance.Contrast(i)
            i = e.enhance(100)
            e = ImageEnhance.Brightness(i)
            i = e.enhance(0.27)
            r, g, b = i.split()
            e = ImageEnhance.Brightness(r)
            r = e.enhance(4)
            e = ImageEnhance.Brightness(g)
            g = e.enhance(1.75)
            e = ImageEnhance.Brightness(b)
            b = e.enhance(0.6)
            e = ImageEnhance.Contrast(b)
            i = Image.merge("RGB", (r, g, b))
            e = ImageEnhance.Brightness(i)
            i = e.enhance(1.5)
            imgs.append(i)
            frame += 1
            try:
                img.seek(frame)
            except EOFError:
                break
        temp = BytesIO()
        temp.name = "deepfried.gif"
        if duration:
            imgs[0].save(temp, format="GIF", save_all=True, append_images=imgs[1:], loop=0, duration=duration)
        else:
            imgs[0].save(temp, format="GIF", save_all=True, append_images=imgs[1:], loop=0)
        temp.seek(0)
        return temp, temp.name

    @staticmethod
    def _nuke(img):
        w, h = img.size[0], img.size[1]
        dx = ((w + 200) // 200) * 2
        dy = ((h + 200) // 200) * 2
        img = img.resize(((w + 1) // dx, (h + 1) // dy))
        e = ImageEnhance.Sharpness(img)
        img = e.enhance(100)
        e = ImageEnhance.Contrast(img)
        img = e.enhance(100)
        e = ImageEnhance.Brightness(img)
        img = e.enhance(0.27)
        r, b, g = img.split()
        e = ImageEnhance.Brightness(r)
        r = e.enhance(4)
        e = ImageEnhance.Brightness(g)
        g = e.enhance(1.75)
        e = ImageEnhance.Brightness(b)
        b = e.enhance(0.6)
        img = Image.merge("RGB", (r, g, b))
        e = ImageEnhance.Brightness(img)
        img = e.enhance(1.5)
        e = ImageEnhance.Sharpness(img)
        img = e.enhance(100)
        img = img.resize((w, h), Image.BILINEAR)
        temp = BytesIO()
        temp.name = "nuke.jpg"
        img.save(temp, quality=1)
        temp.seek(0)
        return temp, temp.name

    @staticmethod
    def _videonuke(img, duration):
        imgs = []
        frame = 0
        while img:
            i = img.copy()
            i = i.convert("RGB")
            w, h = i.size[0], i.size[1]
            dx = ((w + 200) // 200) * 2
            dy = ((h + 200) // 200) * 2
            i = i.resize(((w + 1) // dx, (h + 1) // dy))
            e = ImageEnhance.Sharpness(i)
            i = e.enhance(100)
            e = ImageEnhance.Contrast(i)
            i = e.enhance(100)
            e = ImageEnhance.Brightness(i)
            i = e.enhance(0.27)
            r, g, b = i.split()
            e = ImageEnhance.Brightness(r)
            r = e.enhance(4)
            e = ImageEnhance.Brightness(g)
            g = e.enhance(1.75)
            e = ImageEnhance.Brightness(b)
            b = e.enhance(0.6)
            i = Image.merge("RGB", (r, g, b))
            e = ImageEnhance.Brightness(i)
            i = e.enhance(1.5)
            e = ImageEnhance.Sharpness(i)
            i = e.enhance(100)
            i = i.resize((w, h), Image.BILINEAR)
            imgs.append(i)
            frame += 1
            try:
                img.seek(frame)
            except EOFError:
                break
        temp = BytesIO()
        temp.name = "nuke.gif"
        if duration:
            imgs[0].save(temp, save_all=True, append_images=imgs[1:], loop=0, duration=duration)
        else:
            imgs[0].save(temp, save_all=True, append_images=imgs[1:], loop=0)
        temp.seek(0)
        return temp, temp.name

    def _jpeg_compress(self, img: Image, quality: int) -> Image:
        # save image to temp variable to load it as a PIL image
        temp_file = BytesIO()
        img.save(file=temp_file, adjoin=True if img.animation else False)
        temp_file.seek(0)

        # load as PIL image
        img_file = PILImage.open(temp_file)

        # if its gif, compress each image
        temp_files = [BytesIO() for _ in range(getattr(img, "n_frames", 1))]
        duration = []
        for temp_file in temp_files:
            try:
                duration += [img_file.info["duration"]]
            except KeyError:
                pass
            # compress
            img_file.convert("RGB").save(temp_file, "JPEG", quality=(1 - quality))
            temp_file.seek(0)
            try:
                img_file.seek(img_file.tell() + 1)
            except:
                pass

        # combine pil images back into a single object and save as gif
        images = [PILImage.open(f) for f in temp_files]
        final_file = BytesIO()

        if len(images) > 1:
            images[0].save(
                final_file,
                "GIF",
                save_all=True,
                append_images=images[1:],
                optimize=False,
                loop=0,
                duration=duration,
            )
        else:
            images[0].save(final_file, "JPEG")
        final_file.seek(0)

        # return as wand image
        img = Image(file=final_file)

        return img, "jpeg.jpeg" if len(images) == 1 else "jpeg.gif"

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
            if isinstance(img, Image):
                await ctx.reply(file=discord.File(BytesIO(img.make_blob()), name), mention_author=False)
            else:
                await ctx.reply(file=discord.File(img, filename=name), mention_author=False)
        except discord.errors.HTTPException:
            await ctx.reply("That image is too large.", mention_author=False)
            return

    @commands.hybrid_command()
    @commands.bot_has_permissions(attach_files=True)
    async def distort(self, ctx):
        """
        Distorts an image from a direct link, attatchment, or from recent chat messages

        `[p]distort <distort type> <intensity (1-10) (optional)> <image link>`
        """
        pass

    @distort.command()
    async def jpeg(self, ctx, intensity: Optional[float] = 10, *, link: Optional[str] = None):
        """
        Applies JPEG compression to image
        """
        # we want to flip the quality range so it matches the intentsity of other commands.
        quality = int(self._intensity(intensity) * 100)
        async with ctx.typing():
            try:
                img = await self._get_image(ctx, link)
            except ImageFindError as e:
                return await ctx.reply(e, mention_author=False)

            await self._command_body(ctx, args=(self._jpeg_compress, img, quality))

    @distort.command()
    async def barrel(self, ctx, intensity: Optional[float] = 10, *, link: Optional[str] = None):
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
                    (
                        "barrel",
                        (amount * intensity, amount * intensity, amount * intensity, 0),
                    ),
                ),
            )

    @distort.command()
    async def implode(self, ctx, intensity: Optional[float] = 10, *, link: Optional[str] = None):
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
    async def swirl(self, ctx, intensity: Optional[float] = 10, *, link: Optional[str] = None):
        """
        Swirls the center of the image
        """

        switch = {
            0: 0,
            1: 18,
            2: 36,
            3: 54,
            4: 72,
            5: 90,
            6: 108,
            7: 126,
            8: 144,
            9: 162,
            10: 180,
        }
        intensity = float(switch.get(round(intensity), 180))

        async with ctx.typing():
            try:
                img = await self._get_image(ctx, link)
            except ImageFindError as e:
                return await ctx.reply(e, mention_author=False)

            await self._command_body(ctx, args=(self._distortion, img, "swirl", (intensity,)))

    @distort.command()
    async def charcoal(self, ctx, intensity: Optional[float], *, link: Optional[str] = None):
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
    async def sketch(self, ctx, intensity: Optional[float], *, link: Optional[str] = None):
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
    async def zoom(self, ctx, intensity: Optional[float], *, link: Optional[str] = None):
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

            await self._command_body(
                ctx,
                args=(
                    self._distortion,
                    img,
                    "transform",
                    (f"{w/1.5}x{h/1.5}+{w/2}+{h/2}",),
                ),
            )

    @distort.command(name="deepfry")
    async def deepfry(self, ctx: commands.Context, link: Optional[str] = None):
        """
        Deepfry image
        """
        async with ctx.typing():
            try:
                img = await self._get_image(ctx, link)
            except ImageFindError as e:
                return await ctx.reply(e, mention_author=False)

            # convert to PIL Image for this one
            pilimage = PILImage.open(BytesIO(img.make_blob("png")))
            if "duration" in pilimage.info:
                await self._command_body(ctx, args=(self._videofry, pilimage, pilimage.info["duration"]))
            else:
                await self._command_body(ctx, args=(self._fry, pilimage))

    @distort.command(name="nuke")
    async def nuke(self, ctx: commands.Context, link: Optional[str] = None):
        """
        Deepfry image
        """
        async with ctx.typing():
            try:
                img = await self._get_image(ctx, link)
            except ImageFindError as e:
                return await ctx.reply(e, mention_author=False)

            # convert to PIL Image for this one
            pilimage = PILImage.open(BytesIO(img.make_blob("png")))
            if "duration" in pilimage.info:
                await self._command_body(ctx, args=(self._videonuke, pilimage, pilimage.info["duration"]))
            else:
                await self._command_body(ctx, args=(self._nuke, pilimage))


async def red_delete_data_for_user(
    self,
    *,
    requester: Literal["discord_deleted_user", "owner", "user", "user_strict"],
    user_id: int,
):
    pass
