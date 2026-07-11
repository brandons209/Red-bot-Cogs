# Red 3.5 framework reference

Grounded against Red-DiscordBot v3.5 docs (docs.discord.red). Red 3.5 runs on Python 3.8-3.11.

- [Package wiring](#package-wiring)
- [Config](#config)
- [Commands and checks](#commands-and-checks)
- [modlog](#modlog)
- [Background loops](#background-loops)
- [info.json](#infojson)
- [Chat formatting](#chat-formatting)

## Package wiring

`__init__.py` imports the cog and defines the async `setup`. Cog loading is async in discord.py
2.x, so `add_cog` is awaited:

```python
from .mycog import MyCog

__red_end_user_data_statement__ = "This cog stores ..."

async def setup(bot):
    cog = MyCog(bot)
    await bot.add_cog(cog)
    await cog.initialize()  # only if async setup is needed (e.g. modlog casetypes)
```

Every cog must implement `red_delete_data_for_user`, even when it stores nothing. The `requester`
is one of `"discord_deleted_user"`, `"owner"`, `"user"`, `"user_strict"`; handle any value safely:

```python
async def red_delete_data_for_user(self, *, requester, user_id):
    # no per-user data
    pass
```

The data statement can be declared inline (above) or read from `info.json` to keep the text in one
place: `__red_end_user_data_statement__ = get_end_user_data_statement(__file__)` (import from
`redbot.core.utils`). The reference cogs currently duplicate it in both files; single-source it in
new cogs.

Show the cog version in help by defining `__version__` and `format_help_for_context` (serverwatch
does this; antibot does not, so add it to new cogs):

```python
__version__ = "1.1.0"

def format_help_for_context(self, ctx):
    return f"{super().format_help_for_context(ctx)}\n\nCog Version: {self.__version__}"
```

## Config

`Config` is the persistence layer for every cog. Register defaults in `__init__`:

```python
self.config = Config.get_conf(self, identifier=0xA471B07, force_registration=True)
self.config.register_guild(**default_guild)
self.config.register_member(last_action_ts=0.0)
```

Use a random, cog-unique `identifier`. Keep `force_registration=True` so a typo raises instead of
silently returning the wrong default.

Read the whole scope at once when a listener needs several keys: `conf = await
self.config.guild(guild).all()`. Mutate mutable values in place through the context manager, which
saves on exit:

```python
async with self.config.guild(guild).some_list() as lst:
    lst.append(item)
```

`get_attr(name)` reaches a key by string (useful when the section name is a variable), and
`set_raw(*path, value=...)` writes a nested path.

### Schema migration for dict-shaped Config

A dict stored in Config keeps whatever shape it had when written. Add a key later and every old
record is missing it, which is the most common `KeyError` in the older cogs. Normalize on read with
a helper that fills defaults, so old data gains new keys transparently:

```python
def _normalize_server(self, s):
    s.setdefault("connect_url", None)
    sm = s.setdefault("status_message", {})
    sm.setdefault("embed", True)
    return s
```

Call it wherever you load the dict, before touching new keys. This lets the schema grow without a
migration step.

## Commands and checks

Check decorators live in `redbot.core.commands` in current docs; the `redbot.core.checks` shim
still works and both reference cogs import `from redbot.core import checks`. Either is fine; be
consistent within a cog.

```python
@commands.guild_only()
@checks.admin_or_permissions(manage_guild=True)
@commands.group(name="mycog", aliases=["mc"])
async def mycog(self, ctx):
    """Configuration."""
    pass

@mycog.command(name="channel")
async def mc_channel(self, ctx, channel: discord.TextChannel = None):
    ...
```

Check alias collisions before shipping a short alias; serverwatch had to rename `sw` because
another cog owned it. Use `@checks.bot_has_permissions(...)` on commands that need the bot to hold
a permission (e.g. `embed_links` for a panel).

Read durations with `parse_timedelta` and raise `BadArgument` on junk so Red renders the error
instead of crashing:

```python
from redbot.core.commands.converter import parse_timedelta

def _dur(s):
    if str(s).strip().lower() in ("0", "off", "none"):
        return 0
    td = parse_timedelta(s)
    if td is None:
        raise commands.BadArgument(f"Couldn't read a duration from `{s}`; try `30s`, `5m`, `1h`.")
    return max(0, int(td.total_seconds()))
```

Confirm config writes with a light touch: `await ctx.tick()` plus a self-deleting note
(`await ctx.send(msg, delete_after=60)`) keeps config channels clean.

## modlog

Register casetypes once, in `initialize` (called from `setup`), and ignore the re-register error:

```python
async def initialize(self):
    try:
        await modlog.register_casetypes([
            {"name": "mycog_action", "default_setting": True,
             "image": "\N{FIRE}", "case_str": "MyCog: action"},
        ])
    except RuntimeError:
        pass
```

Create a case with `modlog.create_case(bot, guild, discord.utils.utcnow(), case_type, member,
moderator=guild.me, reason=...)`. It returns `None` if the casetype is disabled for the guild;
that is fine, not an error.

## Background loops

Create the task in `__init__` and cancel it in `cog_unload`. Wait for the bot, break on cancel,
restart on other errors, and bound any in-memory cache so a long-running loop cannot leak:

```python
def __init__(self, bot):
    ...
    self.task = asyncio.create_task(self.bg_loop())

def cog_unload(self):
    self.task.cancel()

async def bg_loop(self):
    await self.bot.wait_until_ready()
    while not self.bot.is_closed():
        try:
            if len(self._cache) > 10000:
                self._cache.clear()
            ...
        except asyncio.CancelledError:
            break
        except Exception:
            log.exception("bg loop error")
            await asyncio.sleep(10)
        await asyncio.sleep(15)
```

Gate work inside the loop with `await self.bot.cog_disabled_in_guild(self, guild)` per guild.
For a precise one-shot (e.g. unlock a role in N seconds), schedule a separate task and keep the
loop as a restart backstop; track those tasks in a set and cancel them in `cog_unload` too
(antibot's role-lock restore does this).

## info.json

Use lowercase keys and `min_bot_version` as a string. The array `bot_version` form is deprecated,
and ALL-CAPS keys are the legacy format; do not copy either from the older cogs.

```json
{
  "author": ["brandons209"],
  "description": "...",
  "short": "...",
  "min_bot_version": "3.5.0",
  "requirements": ["rapidfuzz"],
  "tags": ["moderation"],
  "hidden": false,
  "install_msg": "Thanks for installing! Set up with `[p]mycog`.",
  "end_user_data_statement": "..."
}
```

Note privileged intents in `install_msg` if the cog needs them (e.g. Members, Message Content).

## Chat formatting

From `redbot.core.utils.chat_formatting`: `pagify` to split long output under the 2000-char limit,
`box` for code blocks, `humanize_timedelta` for durations, `humanize_list` for lists, and
`error`/`info`/`warning` for prefixed status lines. `humanize_timedelta` takes either a `timedelta`
or `seconds=`.

## Logging

`log = logging.getLogger("red.brandons209.<cog>")` at module level. Use `log.exception(...)` inside
`except` blocks. The reference cogs still `print()` in their loops; that is the one habit from them
not to copy.
