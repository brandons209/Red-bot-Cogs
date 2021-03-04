from redbot.core import bank, commands, checks, Config
from redbot.core.utils.chat_formatting import *
from redbot.core.utils.predicates import MessagePredicate
from redbot.core.data_manager import cog_data_path

from aitextgen import aitextgen

from typing import Literal
import asyncio, os, time
from multiprocessing import Process, Manager, Queue


class ScriptGen(commands.Cog):
    """
    Generate text from an aitextgen model. Includes cooldowns and economy!
    """

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=414832582438, force_registration=True)

        default_guild = {"last_ran": 0, "cooldown": 0, "cost": 0, "temp": 0.7}
        default_global = {"use_lock": False, "use_gpu": False, "max_len": 250}

        self.config.register_guild(**default_guild)
        self.config.register_global(**default_global)

        self.model = None
        self.lock = None
        self.init_task = asyncio.create_task(self.init())
        os.environ["TOKENIZERS_PARALLELISM"] = "true"

    async def init(self):
        model_path = os.path.join(cog_data_path(cog_instance=self), "pytorch_model.bin")
        config_path = os.path.join(cog_data_path(cog_instance=self), "config.json")
        if os.path.isfile(model_path) and os.path.isfile(config_path):
            use_gpu = await self.config.use_gpu()
            self.model = aitextgen(model=model_path, config=config_path, use_gpu=use_gpu)

        if await self.config.use_lock():
            self.lock = False

    def generate(self, num_words: int, temp: float, prompt: str, queue: Queue):
        queue.put(
            "\n".join(
                self.model.generate(
                    n=1,
                    prompt=prompt,
                    min_length=num_words - 1,
                    max_length=num_words,
                    temperature=temp,
                    seed=int(time.time()),
                    return_as_list=True,
                )
            )
        )

    def cog_unload(self):
        if self.init_task:
            self.init_task.cancel()

    def lock_gen(self):
        if self.lock is not None:
            self.lock = True

    def unlock_gen(self):
        if self.lock is not None:
            self.lock = False

    @commands.group(name="scriptset")
    @checks.admin_or_permissions(administrator=True)
    async def scriptset(self, ctx):
        """
        Manage script gen settings
        """
        pass

    ### global commands ###
    @scriptset.command(name="gpu")
    @checks.is_owner()
    async def scriptset_gpu(self, ctx, on_off: bool):
        """
        Turn on GPU usage for model
        """
        await self.config.use_gpu.set(on_off)
        await ctx.send(warning("Please reload the cog for this to take effect!"))
        await ctx.tick()

    # could make this a queue instead?
    @scriptset.command(name="lock")
    @checks.is_owner()
    async def scriptset_lock(self, ctx, on_off: bool):
        """
        Turn on global command lock

        This means that when someone is generating a script with the bot, everyone else has to wait until it is finished.
        """
        await self.config.use_lock.set(on_off)
        await ctx.send(warning("Please reload the cog for this to take effect!"))
        await ctx.tick()

    @scriptset.command(name="length")
    @checks.is_owner()
    async def scriptset_length(self, ctx, max_len: int = None):
        """
        Set maximum length of generated text
        """
        if not max_len:
            curr = await self.config.max_len()
            await ctx.send(f"Current maximum length: `{curr}`")
            return

        await self.config.max_len.set(max_len)
        await ctx.tick()

    @scriptset.command(name="cooldown")
    @commands.guild_only()
    async def scriptset_cooldown(self, ctx, cooldown: int = None):
        """
        Set server wide cooldown for generation in seconds
        """
        if cooldown is None:
            curr = await self.config.guild(ctx.guild).cooldown()
            await ctx.send(f"Current cooldown length: `{curr}` seconds")
            return

        await self.config.guild(ctx.guild).cooldown.set(cooldown)
        await ctx.tick()

    @scriptset.command(name="cost")
    @commands.guild_only()
    async def scriptset_cost(self, ctx, cost: int = None):
        """
        Set server wide cost per word generated
        """
        if cost is None:
            curr = await self.config.guild(ctx.guild).cost()
            await ctx.send(f"Current cost per word: `{cost}`")
            return

        await self.config.guild(ctx.guild).cost.set(cost)
        await ctx.tick()

    @scriptset.command(name="temp")
    @commands.guild_only()
    async def scriptset_temp(self, ctx, temp: float = None):
        """
        Set temperature for sampling output

        Higher temperature means more varied output but makes less sense
        Lower temperature reduces output variance but increases repeats

        Recommend to keep it 0.7, the default
        """
        if not temp:
            curr = await self.config.guild(ctx.guild).temp()
            await ctx.send(f"Current temperature: `{temp}`")
            return

        await self.config.guild(ctx.guild).temp.set(temp)
        await ctx.tick()

    @commands.command(name="genscript")
    async def genscript(self, ctx, num_words: int, *, prompt: str = ""):
        """
        Generate some scripts!

        Num_words is how many words to generate
        prompt is a starting prompt for generation (optional)

        Some good starting prompts would be a characters name, like:
        Scootaloo::
        """
        ### make sure model is load
        if not self.model:
            await ctx.send(error("Model not loaded! Contact bot owner!"))
            return

        # make sure we are not on cooldown
        cooldown = await self.config.guild(ctx.guild).cooldown()
        last_ran = await self.config.guild(ctx.guild).last_ran()
        now = time.time()
        if now - last_ran < cooldown:
            await ctx.send(f"Sorry, this command is on cooldown for {int((last_ran + cooldown) - now)} seconds")
            return

        # make sure max length isnt exceeded
        max_len = await self.config.max_len()
        if num_words > max_len:
            await ctx.send(error(f"Maximum number of words that can be generated is: {max_len}"))
            return

        # check for current lock:
        if self.lock:
            await ctx.send(error("Sorry, I am currently busy generating for someone else! Please wait a few moments."))
            return

        ### lock if enabled
        self.lock_gen()
        cost = await self.config.guild(ctx.guild).cost() * num_words
        temp = await self.config.guild(ctx.guild).temp()
        currency = await bank.get_currency_name(ctx.guild)

        try:
            await bank.withdraw_credits(ctx.author, cost)
        except ValueError:
            await ctx.send(f"Insufficient funds! Cost for this generation is {cost} {currency}")
            self.unlock_gen()
            return

        await ctx.send(warning(f"Charged: {cost} {currency}"))

        # output = await self.generate(num_words, temp, prompt)
        queue = Manager().Queue()
        p = Process(
            target=self.generate,
            args=(
                num_words,
                temp,
                prompt,
                queue,
            ),
        )
        p.start()

        # in order to avoid the bot's main asyncio loop getting held up (which freezes the bot)
        # need to wait while the queue is empty. also cant just put pass, since this
        # will also hold up the bot's main loop
        # asyncio.sleep(0) forces a context switch which allows other coroutines to continue running and the bot to function normally while the process is ran in a seperate thread
        # see https://stackoverflow.com/questions/63322094/asyncio-aiohttp-create-task-blocks-event-loop-gather-results-in-this-event
        while queue.empty():
            await asyncio.sleep(0)

        # cleanup process
        p.join()
        p.close()

        # get output
        output = queue.get()

        # unlock and reset cooldown before sending
        await self.config.guild(ctx.guild).last_ran.set(time.time())
        self.unlock_gen()

        await ctx.send(box(output))

    async def red_delete_data_for_user(
        self,
        *,
        requester: Literal["discord_deleted_user", "owner", "user", "user_strict"],
        user_id: int,
    ):
        pass
