# Red-Bot-Cogs

A collection of cogs for [Red-DiscordBot](https://github.com/Cog-Creators/Red-DiscordBot) v3.5
(discord.py 2.x). Each top-level directory is one cog. The cogs span several years and vary in
quality; `antibot/` and `serverwatch/` are the current reference implementations. Imitate them,
not the older cogs.

For the full patterns, checklists, and grounded API notes, use the **`redbot-cog-dev` skill**
(`.claude/skills/redbot-cog-dev/`). It triggers on cog work. This file is the short version.

## Environment

- Red runs under the `bots` conda env (Python 3.11). Red 3.5 supports Python 3.8-3.11, not 3.12+.
- Format with black before committing: `black .` (config is in `pyproject.toml`: line length 120).
  CI (`black-checker`) runs the same black 25.9.0 with `--check`, so a clean local run means green CI.
- Smoke-check syntax after edits: `python -m py_compile <files>`.
- The vendored library at `patreonroles/patreon-python/` is excluded from black; do not reformat it.

## Cog anatomy

`__init__.py` wires the cog. Setup is async in discord.py 2.x:

```python
from .mycog import MyCog

async def setup(bot):
    cog = MyCog(bot)
    await bot.add_cog(cog)
    await cog.initialize()  # only if you have async setup, e.g. modlog casetypes
```

Set `__red_end_user_data_statement__` in `__init__.py`. Prefer reading it from `info.json` with
`get_end_user_data_statement(__file__)` so the text lives in one place.

The cog class holds config and state:

```python
class MyCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=<random int>, force_registration=True)
        self.config.register_guild(**default_guild)
        self.task = asyncio.create_task(self.bg_loop())

    def cog_unload(self):
        self.task.cancel()
```

## Conventions to follow

- **Config for all persistence.** `register_guild` / `register_member` / `register_global`, and the
  `async with self.config.guild(g).some_dict() as d:` context manager for in-place mutation. For
  dict-shaped values, add a `_normalize_*` helper that fills missing keys so old saved data survives
  a schema change (see `serverwatch._normalize_server`).
- **Checks** come from `redbot.core.commands` (the `redbot.core.checks` shim still works):
  `@commands.guild_only()`, `@checks.admin_or_permissions(manage_guild=True)`,
  `@checks.bot_has_permissions(...)`. Gate every guild listener and loop with
  `await self.bot.cog_disabled_in_guild(self, guild)`.
- **One action pipeline.** When several code paths do the same moderation or notification work, funnel
  them through a single function that enforces immunity, dispatches, deletes messages, writes the
  modlog case, and sends the alert (see `antibot/actions.py`). Detectors never call Discord mod APIs
  directly.
- **AllowedMentions on every send that names a role.** Use
  `discord.AllowedMentions(roles=[role], everyone=False, users=False)` to ping one role, or
  `AllowedMentions.none()` to render a mention without pinging.
- **Clip to Discord's limits** before sending: embed title 256, field value 1024, description 4096,
  message 2000. `pagify` long lists. An oversized reason must never fail the send.
- **Timestamps and durations:** `discord.utils.format_dt(dt, "D")` for dates, `humanize_timedelta`
  for durations, `parse_timedelta` (raise `BadArgument` on junk) to read duration arguments.
- **Logging, not print:** `log = logging.getLogger("red.brandons209.<cog>")`. (The reference cogs
  still `print()` in their loops; do not copy that.)
- **Config UI:** for anything with more than a handful of settings, add an interactive panel with
  `discord.ui.View` / `Modal` / `Select` alongside the text commands, and route both through the same
  config-writer helpers so they stay in parity (see `serverwatch/views.py`).
- **Separate pure logic** (scoring, clustering, threshold decisions) into modules with no discord or
  redbot imports, driven by a caller-supplied `now`, so it is unit-testable without Red.

### Threshold pings need hysteresis

Any feature that pings when a metric crosses a threshold must not fire on a raw compare. A population
hovering at the threshold, or a brief dip like a TF2 map change, will re-ping every cooldown. Use the
armed/cooldown model from `serverwatch`: fire once on crossing, disarm, and re-arm only after the
value stays below a percentage floor of the threshold for a grace period, with a global cooldown on
top. `antibot`'s `CrossChannelDetector` reuses the same model. See the skill's
`references/notify-hysteresis.md`.

## Anti-patterns to avoid

Present in the older cogs; do not reproduce them.

- Bare `except:` that swallows every error. Catch specific exceptions (`discord.Forbidden`,
  `discord.HTTPException`).
- `print()` for diagnostics instead of a `red.*` logger.
- `aiohttp.ClientSession(loop=...)` (removed in aiohttp 4) and `asyncio.get_event_loop()` (use
  `get_running_loop()`).
- The `on_member_leave` event (it is `on_member_remove`).
- Blocking file I/O inside an async handler.
- Background tasks created but never tracked or cancelled in `cog_unload`, and
  `bot.loop.create_task(session.close())` in a sync `cog_unload` (make it `async` and `await`).
- Legacy `info.json`: ALL-CAPS keys or `bot_version` as an array. Use lowercase keys and
  `min_bot_version` as a string.
- **Do not** call `bot.process_commands` in a cog's `on_message` listener. Cog listeners are additive;
  Red's core still processes commands. Calling it yourself double-processes every command. To skip
  command invocations in a content listener, check `ctx = await self.bot.get_context(message)` and
  return on `ctx.valid`.

## Comments and writing

Write comments and user-facing text the way the reference cogs do: concise, explaining *why* a
non-obvious choice was made, not narrating *what* the code plainly does. No em dashes, no
over-explanation, no "this is important" filler. A comment should tell the next reader something the
code cannot.
