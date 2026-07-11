# Interactive config panel

A cog with more than a handful of settings is painful to configure through text commands alone. Both
reference cogs add an interactive panel built from `discord.ui`, opened with a `panel` command,
alongside the text commands. The rule that keeps them from drifting apart: commands and the panel
both call the *same* config-writer helpers, so there is one source of truth for validation and
writes.

Put the panel in a `views.py` and lazy-import it from the command, so loading the cog does not pay
for the UI:

```python
@mycog.command(name="panel", aliases=["setup", "ui"])
@checks.bot_has_permissions(embed_links=True)
async def mc_panel(self, ctx):
    from .views import MyCogPanel
    view = MyCogPanel(self, ctx.guild, ctx.author)
    await view.build()
    view.message = await ctx.send(embed=await view.render_embed(), view=view)
```

## The View

Subclass `discord.ui.View`. Gate it to the invoking user with `interaction_check`, set a `timeout`,
and disable the components on timeout. Rebuild the component set per page in a `build()` method
rather than hardcoding a fixed layout:

```python
class MyCogPanel(discord.ui.View):
    def __init__(self, cog, guild, author, *, timeout=300):
        super().__init__(timeout=timeout)
        self.cog, self.guild, self.author = cog, guild, author

    async def interaction_check(self, interaction):
        return interaction.user.id == self.author.id

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        if self.message:
            await self.message.edit(view=self)
```

Add components dynamically with a closure callback when the set depends on config (a select whose
options come from the guild's roles, a button per detector). Bind loop variables explicitly so each
callback captures its own value:

```python
def _add_toggle(self, label, current, on_toggle, row):
    btn = discord.ui.Button(label=label, style=..., row=row)
    async def cb(interaction):
        await on_toggle(not current)
        await self._show(interaction)  # re-render
    btn.callback = cb
    self.add_item(btn)
```

## Modals and selects

Use a `Modal` with `TextInput`s for free-text or numeric settings, submitting through `on_submit`.
Use the typed selects for entities: `RoleSelect`, `ChannelSelect`, `UserSelect`, `MentionableSelect`
resolve to real objects without parsing.

Discord's component limits are hard; design pages around them:

- 5 action rows per message, 5 components per row.
- 25 options per select menu.
- 5 `TextInput`s per modal.

When a list can exceed a select's 25 options, paginate the panel or fall back to the text command.

## Command parity through shared writers

Every setting the panel changes must go through the same helper the text command uses. Two shapes
work:

- Writer methods on the cog (`antibot`): `_set_section_fields(guild, section, **fields)`,
  `_set_list(guild, path, ids)`. Commands and the panel both call these.
- Validating helpers that raise a cog-specific error (`serverwatch`): `_add_threshold(...)` raises
  `ServerWatchError` on bad input; the command renders it with `error(...)` and the panel shows it
  in the interaction response. One validation path, two front-ends.

Render the current settings from a single embed builder shared by the `settings` command and the
panel's overview page, so the two never disagree about what is configured.
