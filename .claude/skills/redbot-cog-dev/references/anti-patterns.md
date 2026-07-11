# Cog review checklist

Dated and fragile patterns that recur in the older cogs, each with the fix. When reviewing or
touching a cog, scan for these. Each is a rule plus the corrected form, so it stays valid as the
repo is cleaned up.

## Error handling

- **Bare `except:`** swallows every error, including `KeyboardInterrupt` and real bugs, and hides
  the failure. Catch what you actually expect: `except (discord.Forbidden, discord.HTTPException)`
  for a send that may fail, a specific `ValueError`/`KeyError` for parsing. If you truly must catch
  broadly, use `except Exception` and log it with `log.exception(...)`.
- **Silent failure with no log.** An `except` that only `pass`es on a real error leaves nothing to
  diagnose. Either handle it or log it.

## Logging

- **`print()` for diagnostics.** Use `log = logging.getLogger("red.brandons209.<cog>")`. Print goes
  nowhere useful in a running bot and cannot be filtered by level.

## Async correctness

- **Blocking I/O in an async handler.** Synchronous `open()`, `os.makedirs`, `requests`, or PIL
  work inside a coroutine stalls the whole bot. Move it off the loop (`run_in_executor`) or use an
  async client.
- **`asyncio.get_event_loop()`** is deprecated inside a coroutine. Use
  `asyncio.get_running_loop()`, or just `asyncio.create_task(...)`.
- **`aiohttp.ClientSession(loop=...)`**: the `loop` argument was removed in aiohttp 4. Drop it.

## Tasks and cleanup

- **Untracked fire-and-forget tasks.** `asyncio.create_task(...)` whose handle is discarded cannot
  be cancelled and can outlive the cog. Hold references (a set, or `self.task`) and cancel them in
  `cog_unload`.
- **Missing `cog_unload`.** A cog that starts a loop or opens a session must clean up on unload, or
  it leaks across reloads.
- **`bot.loop.create_task(session.close())` in a sync `cog_unload`.** This fires a coroutine onto a
  loop that may be shutting down, so the close can silently not happen. Make `cog_unload` `async`
  and `await self.session.close()`.

## discord.py 2.x

- **`on_member_leave`** is not an event; use `on_member_remove`.
- **Calling `bot.process_commands` in a cog `on_message` listener.** Cog listeners are additive;
  Red already processes commands, so this double-processes every command. Gate content listeners on
  `ctx = await self.bot.get_context(message)` / `ctx.valid` instead.
- **1.x command style** (`pass_context`, `bot.say`) is removed; rewrite as modern commands.
- **`datetime.utcnow()`** is naive; use `discord.utils.utcnow()`.

## Config and metadata

- **Reading new dict keys off old saved data** raises `KeyError`. Normalize on read with a helper
  that `setdefault`s the new keys (see `references/redbot.md`).
- **Omitting `force_registration=True`** lets a typo'd Config key return a wrong default silently.
  Keep it on.
- **Legacy `info.json`:** ALL-CAPS keys or `bot_version` as an array. Use lowercase keys and
  `min_bot_version` as a string.
- **Duplicated helpers across cogs** (e.g. two copies of a `parse_seconds`). If a helper is shared,
  move it to one module and import it; do not fork it.

## Sends and limits

- **Sends that name a role without `allowed_mentions`** can ping unintentionally. Set
  `AllowedMentions` explicitly (see `references/discordpy.md`).
- **Unclipped text in embeds/messages.** A long reason or a big whitelist can exceed Discord's
  limits and fail the send. Clip to the field (1024), description (4096), or message (2000) cap, and
  `pagify` long lists.
