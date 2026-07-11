# discord.py 2.x reference

Grounded against discord.py 2.7.1 docs (discordpy.readthedocs.io). Red 3.5 ships discord.py 2.x,
so the 1.x patterns in very old cogs are gone. This covers the APIs cogs actually touch.

- [Intents](#intents)
- [Timestamps and durations](#timestamps-and-durations)
- [AllowedMentions](#allowedmentions)
- [Moderation actions](#moderation-actions)
- [Message operations](#message-operations)
- [Listeners and events](#listeners-and-events)
- [1.x removals to avoid](#1x-removals-to-avoid)

## Intents

Intents are set at bot construction (Red handles this). Two are privileged and must be enabled both
in the Developer Portal and in code: `members` and `message_content`. Without `message_content`,
`Message.content`, `attachments`, `embeds`, and `components` come through empty, so any content
detector silently sees nothing. If a cog reads message text, say so in `install_msg`.

## Timestamps and durations

All datetimes in 2.x are timezone-aware. Use `discord.utils.utcnow()`, never
`datetime.utcnow()`. Render a time for users as a Discord timestamp so it localizes per viewer:

```python
discord.utils.format_dt(member.created_at, "D")  # date; "R" relative, "f" short date+time
```

Round-and-humanize a span with `humanize_timedelta`. To show whole days, round first so it reads
`3 days` instead of `2 days, 21 hours, 4 minutes`:

```python
days = round(seconds / 86400)
humanize_timedelta(seconds=days * 86400)
```

## AllowedMentions

Set `allowed_mentions` on every send that contains a mention. To ping exactly one role and nothing
else:

```python
await channel.send(content, allowed_mentions=discord.AllowedMentions(
    roles=[role], everyone=False, users=False))
```

To render a role mention so it shows as the colored role but does not ping (e.g. a "that ping was a
bot" notice), send the mention with `discord.AllowedMentions.none()`.

## Moderation actions

Timeout takes a `timedelta` (Discord caps it at 28 days; clamp before calling):

```python
await member.timeout(timedelta(seconds=min(secs, 28 * 86400)), reason=reason)
```

Ban uses `delete_message_seconds`, not the old `delete_message_days`:

```python
await guild.ban(member, reason=reason, delete_message_seconds=3600)
```

`guild.kick(member, reason=...)` is unchanged. Wrap every mod call and handle failure without
aborting the rest of the pipeline:

```python
try:
    await member.timeout(...)
except discord.Forbidden:
    failed = "forbidden"
except discord.HTTPException as e:
    failed = f"http {getattr(e, 'status', '?')}"
```

To add a role, prefer one atomic edit over `add_roles` when changing several:
`await member.edit(roles=[*member.roles, role], reason=reason)`. Check hierarchy first
(`role < guild.me.top_role` and `manage_roles`).

## Message operations

Bulk-delete caps at 100 messages and refuses messages older than 14 days. Group evidence per
channel and fall back to single deletes:

```python
partials = [channel.get_partial_message(i) for i in ids]
try:
    await channel.delete_messages(partials[:100], reason=reason)
except (discord.Forbidden, discord.HTTPException, discord.NotFound):
    for pm in partials:
        try:
            await pm.delete()
        except (discord.Forbidden, discord.HTTPException, discord.NotFound):
            pass
```

`get_partial_message(id)` acts on a message without fetching it, which avoids an API call when you
only need to delete.

## Listeners and events

Register with `@commands.Cog.listener()`. Cog listeners are additive: they run alongside Red's own
handlers, so a cog `on_message` must **not** call `bot.process_commands` (that is only for a
monolithic bot that overrides `on_message`; calling it in a cog double-processes every command). To
skip command invocations in a content listener, check `ctx = await self.bot.get_context(message)`
and return on `ctx.valid`.

Events cogs commonly use: `on_message`, `on_member_join`, `on_member_remove`, `on_member_update`,
`on_user_update`. Two 2.x changes matter:

- `on_member_update` no longer fires for presence (status/activity) changes; those moved to
  `on_presence_update`. Code that compared `before.status` there stopped working.
- Member and user objects expose `public_flags`. `PublicUserFlags.spammer` is real (added in 2.0),
  which is how antibot reads Discord's suspected-spammer badge.

## 1.x removals to avoid

If you see these in an old cog, they are broken or dated. Do not reproduce them.

- `pass_context=True`, `await ctx.bot.say(...)` / `bot.say`: 1.x command style, removed.
- `on_member_leave`: the event is `on_member_remove`.
- `aiohttp.ClientSession(loop=...)`: the `loop` argument was removed in aiohttp 4; drop it.
- `asyncio.get_event_loop()`: use `asyncio.get_running_loop()` inside a coroutine.
- `datetime.utcnow()`: use `discord.utils.utcnow()` (aware).
- In-place edits returning `None`: 2.x `.edit()` methods return the new object.
