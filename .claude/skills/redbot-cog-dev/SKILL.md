---
name: redbot-cog-dev
description: >-
  Build, modify, or review Red-DiscordBot v3 cogs (discord.py 2.x) in this repo. Use this
  whenever the work touches a cog: adding or changing commands, listeners, Config schemas,
  background loops, moderation actions, embeds, or an interactive Views/Modals config panel,
  and when reviewing cog code for correctness or dated patterns. Trigger it even when the user
  says "add a command", "watch for X", "ping a role when Y", "store a setting", "make a setup
  panel", or "clean up this cog" without naming Red or discord.py. It carries the repo's house
  conventions (from the antibot and serverwatch reference cogs), grounded discord.py 2.x / Red
  3.5 API notes, and the anti-patterns to avoid.
---

# Red-DiscordBot cog development

This repo is a collection of Red v3.5 cogs (discord.py 2.x). `antibot/` and `serverwatch/` are
the reference implementations; match them. This skill is the checklist plus pointers to detailed
references. Read the reference file for whatever the task touches; do not load all of them.

## When building or changing a cog

Work through the parts the task touches. Each links to the reference with the full pattern.

1. **Wiring** (`references/redbot.md`): `async def setup(bot)` with `await bot.add_cog(...)`;
   `__red_end_user_data_statement__`; `red_delete_data_for_user`; `info.json` with
   `min_bot_version` as a string. Get these right once and they rarely change.
2. **Config** (`references/redbot.md`): `Config.get_conf(self, identifier=<random int>,
   force_registration=True)`, `register_guild/member/global`, the `async with` mutation context
   manager. For dict-shaped values, write a `_normalize_*` helper so old saved data survives a
   schema change. This is the single most common source of `KeyError` in older cogs.
3. **Commands** (`references/redbot.md`): `@commands.group` + subcommands, checks from
   `redbot.core.commands` (`admin_or_permissions`, `bot_has_permissions`, `guild_only`),
   `parse_timedelta` for durations, self-deleting confirmations.
4. **Listeners** (`references/redbot.md`, `references/discordpy.md`): gate every guild listener
   with `cog_disabled_in_guild`; know the 2.x event changes (on_member_update dropped presence,
   on_member_remove not on_member_leave); and never call `bot.process_commands` from a cog
   listener.
5. **Actions and sends** (`references/discordpy.md`): funnel moderation through one pipeline;
   set `AllowedMentions` on every send that names a role; clip text to Discord's embed/message
   limits; use `format_dt` and `humanize_timedelta` for times.
6. **Background loops** (`references/redbot.md`): `asyncio.create_task` in `__init__`, cancel in
   `cog_unload`, `wait_until_ready`, catch `CancelledError` to break and other exceptions to
   restart, and bound any in-memory cache.
7. **Threshold pings** (`references/notify-hysteresis.md`): if the cog pings when a metric
   crosses a threshold, it needs armed/cooldown hysteresis, not a raw compare. Read this before
   writing that logic; getting it wrong causes ping spam and is the bug both reference cogs
   burned the most time on.
8. **Config UI** (`references/config-ui.md`): for more than a handful of settings, add a
   `discord.ui` panel with command parity, routed through shared config-writer helpers.
9. **Pure logic and tests** (`references/testing.md`): split scoring, clustering, and threshold
   decisions into modules with no discord/redbot imports so they unit-test without Red.

## When reviewing a cog

Read `references/anti-patterns.md` and check the diff against it. It lists each dated pattern
found in the older cogs and the fix. Then confirm the build checklist above: config schema
migration, listener gating, `AllowedMentions`, limit clipping, and `cog_unload` cleanup are the
usual gaps.

## House style

- Comments explain *why* a non-obvious choice was made, not *what* the code does. Keep them
  concise. No em dashes, no over-explanation. If a comment restates the code, cut it.
- User-facing strings are short and specific. Show durations with `humanize_timedelta`, dates
  with `format_dt`.
- Logging uses `logging.getLogger("red.brandons209.<cog>")`, never `print()`.

## Reference index

- `references/redbot.md`: Red 3.5 framework (setup, Config, checks, modlog, info.json, loops).
- `references/discordpy.md`: discord.py 2.x (intents, moderation APIs, AllowedMentions, times,
  1.x removals to avoid).
- `references/config-ui.md`: Views/Modals/Selects config panel with command parity.
- `references/notify-hysteresis.md`: armed/cooldown/re-arm model for threshold pings.
- `references/testing.md`: separating pure logic for unit tests without Red.
- `references/anti-patterns.md`: the review checklist of dated patterns and their fixes.
