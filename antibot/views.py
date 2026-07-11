"""
Interactive configuration panel for the antibot cog.

A single state-machine ``discord.ui.View`` (``AntiBotPanel``) whose ``page`` string
drives which buttons/selects are shown, plus a handful of Modals for numeric/text
input. Mirrors the serverwatch ``views.py`` pattern: all config writes route through
the cog's shared ``_set_*`` helpers, the embed is rebuilt on every interaction, and a
``_notice`` string gives inline feedback.

The CLI ``[p]antibot ...`` commands remain the way to fine-tune single values; the
panel is the point-and-click first-time setup surface.
"""

import discord
from redbot.core import commands
from redbot.core.utils.chat_formatting import humanize_timedelta

from .antibot import _ACTIONS, _dur, build_settings_embed

_BLURPLE = discord.Colour.blurple()

# Section buttons on the main page: (label, page-key).
_SECTIONS = [
    ("Global", "global"),
    ("Spam", "spam"),
    ("Join", "join"),
    ("Role-ping", "roleping"),
    ("Spammer", "spammer"),
    ("DM", "dmflag"),
    ("Honeypot", "honeypot"),
    ("Signatures", "signatures"),
]

# Short blurb shown on each detector sub-page.
_PAGE_HELP = {
    "global": "Notify channel/role, quarantine role, cog on/off, and whitelists.",
    "spam": "Same message across many channels quickly. Use **Thresholds…** for numbers.",
    "join": "Account-age gate on join. Use **Settings…** for the age windows.",
    "roleping": "Role-ping abuse + lockdown. **Detection…** for numbers, **Lockdown & notice…** for the rest.",
    "spammer": "Acts on Discord's suspected-spammer badge (join + post-join).",
    "dmflag": "A new/just-joined account DMing the bot. **Detection…** for the age windows.",
    "honeypot": "Trap channels; any post triggers the action. Established/role-exempt members are spared.",
    "signatures": "Learned bot fingerprints. Tiers, weights and the store are managed via `[p]antibot sig …`.",
}


def _opt(value, current):
    return discord.SelectOption(label=value, value=value, default=(value == current))


def _dur_str(seconds):
    """Human-readable, re-parseable duration default for a modal field ('0' if unset)."""
    seconds = int(seconds or 0)
    return humanize_timedelta(seconds=seconds) if seconds > 0 else "0"


class AntiBotPanel(discord.ui.View):
    """Point-and-click config panel. `page` selects which controls are rendered."""

    def __init__(self, cog, guild, author, *, timeout=300):
        super().__init__(timeout=timeout)
        self.cog = cog
        self.guild = guild
        self.author = author
        self.page = "main"
        self.message = None
        self._notice = None

    # --- framework hooks -------------------------------------------------- #
    async def interaction_check(self, interaction):
        if interaction.user.id != self.author.id:
            await interaction.response.send_message("This isn't your configuration panel.", ephemeral=True)
            return False
        return True

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass

    async def _conf(self):
        return await self.cog.config.guild(self.guild).all()

    async def _show(self, interaction):
        await self.build()
        await interaction.response.edit_message(embed=await self.render_embed(), view=self)

    # --- shared item builders --------------------------------------------- #
    def _nav(self, page):
        async def cb(interaction):
            self.page = page
            self._notice = None
            await self._show(interaction)

        return cb

    def _add_back(self, row=4):
        btn = discord.ui.Button(label="Back", emoji="◀️", style=discord.ButtonStyle.secondary, row=row)
        btn.callback = self._nav("main")
        self.add_item(btn)

    def _add_action_select(self, detector, conf, row=0):
        current = conf[detector]["action"]["action"]
        sel = discord.ui.Select(
            placeholder=f"Action: {current}",
            row=row,
            options=[_opt(a, current) for a in _ACTIONS],
        )

        async def cb(interaction):
            await self.cog._set_action_field(self.guild, detector, "action", sel.values[0])
            self._notice = f"✅ {detector} action → **{sel.values[0]}**"
            await self._show(interaction)

        sel.callback = cb
        self.add_item(sel)

    def _add_toggle(self, label, current, on_toggle, row):
        """on_toggle(new_value) -> coroutine that persists the change."""
        btn = discord.ui.Button(
            label=f"{label}: {'on' if current else 'off'}",
            style=discord.ButtonStyle.success if current else discord.ButtonStyle.secondary,
            row=row,
        )

        async def cb(interaction):
            await on_toggle(not current)
            self._notice = f"✅ {label} → **{'on' if not current else 'off'}**"
            await self._show(interaction)

        btn.callback = cb
        self.add_item(btn)

    def _add_modal_button(self, label, modal_factory, row):
        btn = discord.ui.Button(label=label, style=discord.ButtonStyle.primary, row=row)

        async def cb(interaction):
            await interaction.response.send_modal(modal_factory())

        btn.callback = cb
        self.add_item(btn)

    def _add_list_select(self, select, path, row):
        """Wire a Role/Channel select so its selection REPLACES the whole id-list."""
        select.row = row

        async def cb(interaction):
            await self.cog._set_list(self.guild, path, [v.id for v in select.values])
            self._notice = f"✅ Updated ({len(select.values)} selected)."
            await self._show(interaction)

        select.callback = cb
        self.add_item(select)

    # --- toggle helper factories (return coroutine-producing callables) --- #
    def _flag(self, detector, field):
        return lambda v: self.cog._set_action_field(self.guild, detector, field, v)

    def _sect(self, section, key):
        return lambda v: self.cog._set_section_fields(self.guild, section, **{key: v})

    # --- select default_values, resolved so a stale id can't break the panel #
    def _role_defaults(self, ids):
        return [r for r in (self.guild.get_role(int(i)) for i in (ids or []) if i) if r]

    def _chan_defaults(self, ids):
        return [c for c in (self.guild.get_channel_or_thread(int(i)) for i in (ids or []) if i) if c]

    # --- page dispatch ---------------------------------------------------- #
    async def build(self):
        self.clear_items()
        conf = await self._conf()
        getattr(self, f"_build_{self.page}")(conf)

    def _build_main(self, conf):
        for i, (label, page) in enumerate(_SECTIONS):
            btn = discord.ui.Button(label=label, style=discord.ButtonStyle.primary, row=0 if i < 4 else 1)
            btn.callback = self._nav(page)
            self.add_item(btn)
        close = discord.ui.Button(label="Close", emoji="✖️", style=discord.ButtonStyle.danger, row=2)

        async def close_cb(interaction):
            for item in self.children:
                item.disabled = True
            self.stop()
            await interaction.response.edit_message(content="Configuration panel closed.", embed=None, view=self)

        close.callback = close_cb
        self.add_item(close)

    def _build_global(self, conf):
        notify = discord.ui.ChannelSelect(
            placeholder="Notify channel…",
            min_values=0,
            max_values=1,
            channel_types=[discord.ChannelType.text, discord.ChannelType.news],
            default_values=self._chan_defaults([conf["notify_channel"]]),
        )

        async def notify_cb(interaction):
            await self.cog._set_top(self.guild, "notify_channel", notify.values[0].id if notify.values else None)
            self._notice = "✅ Notify channel updated."
            await self._show(interaction)

        notify.row = 0
        notify.callback = notify_cb
        self.add_item(notify)

        nrole = discord.ui.RoleSelect(
            placeholder="Notify role (ping on alerts)…",
            min_values=0,
            max_values=1,
            default_values=self._role_defaults([conf["notify_role"]]),
            row=1,
        )

        async def nrole_cb(interaction):
            await self.cog._set_top(self.guild, "notify_role", nrole.values[0].id if nrole.values else None)
            self._notice = "✅ Notify role updated."
            await self._show(interaction)

        nrole.callback = nrole_cb
        self.add_item(nrole)

        qrole = discord.ui.RoleSelect(
            placeholder="Quarantine role (for `role` action)…",
            min_values=0,
            max_values=1,
            default_values=self._role_defaults([conf["quarantine_role"]]),
            row=2,
        )

        async def qrole_cb(interaction):
            if qrole.values and qrole.values[0] >= self.guild.me.top_role:
                self._notice = "⚠️ That role is above my top role, so I couldn't assign it."
            else:
                await self.cog._set_top(self.guild, "quarantine_role", qrole.values[0].id if qrole.values else None)
                self._notice = "✅ Quarantine role updated."
            await self._show(interaction)

        qrole.callback = qrole_cb
        self.add_item(qrole)

        self._add_toggle("Cog enabled", conf["enabled"], lambda v: self.cog._set_top(self.guild, "enabled", v), row=3)
        wlr = discord.ui.Button(label="Whitelist roles…", style=discord.ButtonStyle.secondary, row=3)
        wlr.callback = self._nav("global_wl_roles")
        self.add_item(wlr)
        wlc = discord.ui.Button(label="Whitelist channels…", style=discord.ButtonStyle.secondary, row=3)
        wlc.callback = self._nav("global_wl_channels")
        self.add_item(wlc)
        self._add_modal_button("Ban DM…", lambda: BanDmModal(self, conf.get("ban_dm_message")), row=3)
        self._add_back()

    def _build_global_wl_roles(self, conf):
        sel = discord.ui.RoleSelect(
            placeholder="Immune roles (replaces the list)…",
            min_values=0,
            max_values=25,
            default_values=self._role_defaults(conf["whitelist_roles"]),
        )
        self._add_list_select(sel, "whitelist_roles", row=0)
        self._add_back()

    def _build_global_wl_channels(self, conf):
        sel = discord.ui.ChannelSelect(
            placeholder="Ignored channels (replaces the list)…",
            min_values=0,
            max_values=25,
            channel_types=_CONTENT_CHANNEL_TYPES,
            default_values=self._chan_defaults(conf["whitelist_channels"]),
        )
        self._add_list_select(sel, "whitelist_channels", row=0)
        self._add_back()

    def _build_spam(self, conf):
        self._add_action_select("spam", conf, row=0)
        self._detector_flag_row("spam", conf, row=1, delete=True)
        self._add_modal_button("Thresholds…", lambda: SpamModal(self, conf["spam"]), row=2)
        self._add_back()

    def _build_join(self, conf):
        self._add_action_select("join", conf, row=0)
        self._detector_flag_row("join", conf, row=1, delete=False)
        self._add_modal_button("Settings…", lambda: JoinModal(self, conf["join"]), row=2)
        self._add_back()

    def _build_roleping(self, conf):
        rp = conf["roleping"]
        self._add_action_select("roleping", conf, row=0)
        self._add_toggle("Enabled", rp["enabled"], self._sect("roleping", "enabled"), row=1)
        self._add_toggle("DM", rp["action"].get("dm", True), self._flag("roleping", "dm"), row=1)
        self._add_toggle("Modlog", rp["action"].get("modlog", True), self._flag("roleping", "modlog"), row=1)
        self._add_toggle(
            "Delete", rp["action"].get("delete_messages", True), self._flag("roleping", "delete_messages"), row=1
        )
        self._add_toggle("Lockdown", rp.get("lockdown", True), self._sect("roleping", "lockdown"), row=1)
        watched = discord.ui.RoleSelect(
            placeholder="Watched roles (empty = all mentionable)…",
            min_values=0,
            max_values=25,
            default_values=self._role_defaults(rp["watched_roles"]),
        )
        self._add_list_select(watched, ("roleping", "watched_roles"), row=2)
        self._add_modal_button("Detection…", lambda: RolePingDetectModal(self, rp), row=3)
        self._add_modal_button("Lockdown & notice…", lambda: RolePingLockModal(self, rp), row=3)
        self._add_back()

    def _build_spammer(self, conf):
        sm = conf["spammer"]
        self._add_action_select("spammer", conf, row=0)
        self._add_toggle("Enabled", sm["enabled"], self._sect("spammer", "enabled"), row=1)
        self._add_toggle(
            "On-message", sm.get("check_on_message", True), self._sect("spammer", "check_on_message"), row=1
        )
        self._add_toggle("DM", sm["action"].get("dm", True), self._flag("spammer", "dm"), row=1)
        self._add_toggle("Modlog", sm["action"].get("modlog", True), self._flag("spammer", "modlog"), row=1)
        self._add_modal_button("Timeout length…", lambda: TimeoutModal(self, "spammer", sm), row=2)
        self._add_back()

    def _build_dmflag(self, conf):
        dm = conf["dmflag"]
        self._add_action_select("dmflag", conf, row=0)
        self._detector_flag_row("dmflag", conf, row=1, delete=False)
        self._add_toggle(
            "Ignore commands", dm.get("ignore_commands", True), self._sect("dmflag", "ignore_commands"), row=1
        )
        self._add_modal_button("Detection…", lambda: DmModal(self, dm), row=2)
        self._add_back()

    def _build_honeypot(self, conf):
        hp = conf["honeypot"]
        self._add_action_select("honeypot", conf, row=0)
        self._add_toggle("Enabled", hp["enabled"], self._sect("honeypot", "enabled"), row=1)
        self._add_toggle("Report-exempt", hp.get("report_exempt", True), self._sect("honeypot", "report_exempt"), row=1)
        self._add_toggle("DM", hp["action"].get("dm", True), self._flag("honeypot", "dm"), row=1)
        self._add_toggle("Modlog", hp["action"].get("modlog", True), self._flag("honeypot", "modlog"), row=1)
        self._add_toggle(
            "Delete", hp["action"].get("delete_messages", True), self._flag("honeypot", "delete_messages"), row=1
        )
        chans = discord.ui.ChannelSelect(
            placeholder="Honeypot channels (replaces the list)…",
            min_values=0,
            max_values=25,
            channel_types=_CONTENT_CHANNEL_TYPES,
            default_values=self._chan_defaults(hp["channels"]),
        )
        self._add_list_select(chans, ("honeypot", "channels"), row=2)
        exempt = discord.ui.RoleSelect(
            placeholder="Exempt roles…",
            min_values=0,
            max_values=25,
            default_values=self._role_defaults(hp["exempt_roles"]),
        )
        self._add_list_select(exempt, ("honeypot", "exempt_roles"), row=3)
        self._add_toggle(
            "Report-immune", hp.get("report_immune", False), self._sect("honeypot", "report_immune"), row=4
        )
        self._add_modal_button("Settings…", lambda: HoneypotModal(self, hp), row=4)
        self._add_back(row=4)

    def _build_signatures(self, conf):
        sg = conf["signatures"]
        self._add_toggle("Enabled", sg["enabled"], self._sect("signatures", "enabled"), row=0)
        self._add_modal_button("Match distance…", lambda: SigModal(self, sg), row=0)
        self._add_back()

    def _detector_flag_row(self, detector, conf, row, *, delete):
        d = conf[detector]
        self._add_toggle("Enabled", d["enabled"], self._sect(detector, "enabled"), row=row)
        self._add_toggle("DM", d["action"].get("dm", True), self._flag(detector, "dm"), row=row)
        self._add_toggle("Modlog", d["action"].get("modlog", True), self._flag(detector, "modlog"), row=row)
        if delete:
            self._add_toggle(
                "Delete", d["action"].get("delete_messages", True), self._flag(detector, "delete_messages"), row=row
            )

    # --- embed ------------------------------------------------------------ #
    async def render_embed(self):
        conf = await self._conf()
        if self.page == "main":
            embed = build_settings_embed(self.guild, conf, _BLURPLE)
            if self._notice:
                embed.description = f"{self._notice}\n\n{embed.description}"
            embed.set_footer(text="Pick a section to configure · panel times out after 5 min")
            return embed
        title = dict(_SECTIONS).get(self.page) or self.page.replace("_", " ").title()
        embed = discord.Embed(title=f"⚙️ AntiBot · {title}", colour=_BLURPLE)
        lines = []
        if self._notice:
            lines.append(self._notice)
        base = self.page.split("_")[0] if self.page.startswith("global") else self.page
        if base in _PAGE_HELP:
            lines.append(_PAGE_HELP[base])
        embed.description = "\n\n".join(lines) if lines else None
        return embed


# --- channel-type sets ---------------------------------------------------- #
_CONTENT_CHANNEL_TYPES = [
    discord.ChannelType.text,
    discord.ChannelType.news,
    discord.ChannelType.voice,
    discord.ChannelType.stage_voice,
    discord.ChannelType.public_thread,
    discord.ChannelType.private_thread,
]


# --- modals --------------------------------------------------------------- #
def _pos_int(value, floor=0):
    n = int(str(value).strip())
    return max(floor, n)


class SpamModal(discord.ui.Modal, title="Cross-channel spam"):
    def __init__(self, panel, sect):
        super().__init__()
        self.panel = panel
        self.channels = discord.ui.TextInput(label="Channels to trip", default=str(sect["channels"]))
        self.window = discord.ui.TextInput(label="Window (seconds)", default=str(sect["window"]))
        self.distance = discord.ui.TextInput(
            label="SimHash distance (near-dup tolerance)", default=str(sect["simhash_distance"])
        )
        self.cooldown = discord.ui.TextInput(label="Cooldown (seconds)", default=str(sect["cooldown"]))
        self.timeout_len = discord.ui.TextInput(
            label="Timeout length (e.g. 1h)", default=_dur_str(sect["action"].get("timeout_seconds", 3600))
        )
        for f in (self.channels, self.window, self.distance, self.cooldown, self.timeout_len):
            self.add_item(f)

    async def on_submit(self, interaction):
        try:
            channels = _pos_int(self.channels.value, 2)
            window = _pos_int(self.window.value, 1)
            distance = _pos_int(self.distance.value, 0)
            cooldown = _pos_int(self.cooldown.value, 1)
            timeout = max(1, _dur(self.timeout_len.value))
        except (ValueError, commands.BadArgument):
            return await interaction.response.send_message("Give whole numbers and a valid duration.", ephemeral=True)
        await self.panel.cog._set_section_fields(
            self.panel.guild, "spam", channels=channels, window=window, simhash_distance=distance, cooldown=cooldown
        )
        await self.panel.cog._set_action_field(self.panel.guild, "spam", "timeout_seconds", timeout)
        self.panel._notice = "✅ Spam thresholds updated."
        await self.panel._show(interaction)


class DmModal(discord.ui.Modal, title="Unusual DM activity"):
    def __init__(self, panel, sect):
        super().__init__()
        self.panel = panel
        self.new_account = discord.ui.TextInput(
            label="New-account window (e.g. 7d, 0=off)", default=_dur_str(sect.get("new_account_seconds", 0))
        )
        self.new_member = discord.ui.TextInput(
            label="New-member window (e.g. 1d, 0=off)", default=_dur_str(sect.get("new_member_seconds", 0))
        )
        self.min_messages = discord.ui.TextInput(
            label="DMs before firing (min 1)", default=str(sect.get("min_messages", 1))
        )
        self.timeout_len = discord.ui.TextInput(
            label="Timeout length (e.g. 1h)", default=_dur_str(sect["action"].get("timeout_seconds", 3600))
        )
        for f in (self.new_account, self.new_member, self.min_messages, self.timeout_len):
            self.add_item(f)

    async def on_submit(self, interaction):
        try:
            new_account = _dur(self.new_account.value)
            new_member = _dur(self.new_member.value)
            min_messages = _pos_int(self.min_messages.value, 1)
            timeout = max(1, _dur(self.timeout_len.value))
        except (ValueError, commands.BadArgument):
            return await interaction.response.send_message("Give whole numbers and valid durations.", ephemeral=True)
        await self.panel.cog._set_section_fields(
            self.panel.guild,
            "dmflag",
            new_account_seconds=new_account,
            new_member_seconds=new_member,
            min_messages=min_messages,
        )
        await self.panel.cog._set_action_field(self.panel.guild, "dmflag", "timeout_seconds", timeout)
        self.panel._notice = "✅ Unusual-DM settings updated."
        await self.panel._show(interaction)


class JoinModal(discord.ui.Modal, title="Suspicious join"):
    def __init__(self, panel, sect):
        super().__init__()
        self.panel = panel
        self.age_new = discord.ui.TextInput(
            label="'New account' boundary (e.g. 7d)", default=_dur_str(sect["age_new_seconds"])
        )
        self.age_kick = discord.ui.TextInput(
            label="Act if younger than (e.g. 1d, 0=off)", default=_dur_str(sect["age_kick_seconds"])
        )
        self.timeout_len = discord.ui.TextInput(
            label="Timeout length (e.g. 1h)", default=_dur_str(sect["action"].get("timeout_seconds", 3600))
        )
        for f in (self.age_new, self.age_kick, self.timeout_len):
            self.add_item(f)

    async def on_submit(self, interaction):
        try:
            age_new = _dur(self.age_new.value)
            age_kick = _dur(self.age_kick.value)
            timeout = max(1, _dur(self.timeout_len.value))
        except (ValueError, commands.BadArgument):
            return await interaction.response.send_message(
                "Give valid durations (e.g. `7d`, `1h`, `0`).", ephemeral=True
            )
        await self.panel.cog._set_section_fields(
            self.panel.guild, "join", age_new_seconds=age_new, age_kick_seconds=age_kick
        )
        await self.panel.cog._set_action_field(self.panel.guild, "join", "timeout_seconds", timeout)
        self.panel._notice = "✅ Join settings updated."
        await self.panel._show(interaction)


class RolePingDetectModal(discord.ui.Modal, title="Role-ping detection"):
    def __init__(self, panel, sect):
        super().__init__()
        self.panel = panel
        self.threshold = discord.ui.TextInput(label="Pings to trip", default=str(sect["threshold"]))
        self.window = discord.ui.TextInput(label="Window (seconds)", default=str(sect["window"]))
        self.min_members = discord.ui.TextInput(
            label="Min role size (0 = any)", default=str(sect.get("min_role_members", 0))
        )
        self.new_account = discord.ui.TextInput(
            label="New-account window (e.g. 7d, 0=off)", default=_dur_str(sect.get("new_account_seconds", 0))
        )
        self.new_member = discord.ui.TextInput(
            label="New-member window (e.g. 1h, 0=off)", default=_dur_str(sect.get("new_member_seconds", 0))
        )
        for f in (self.threshold, self.window, self.min_members, self.new_account, self.new_member):
            self.add_item(f)

    async def on_submit(self, interaction):
        try:
            threshold = _pos_int(self.threshold.value, 1)
            window = _pos_int(self.window.value, 1)
            min_members = _pos_int(self.min_members.value, 0)
            new_account = _dur(self.new_account.value)
            new_member = _dur(self.new_member.value)
        except (ValueError, commands.BadArgument):
            return await interaction.response.send_message("Give whole numbers and valid durations.", ephemeral=True)
        await self.panel.cog._set_section_fields(
            self.panel.guild,
            "roleping",
            threshold=threshold,
            window=window,
            min_role_members=min_members,
            new_account_seconds=new_account,
            new_member_seconds=new_member,
        )
        self.panel._notice = "✅ Role-ping detection updated."
        await self.panel._show(interaction)


class RolePingLockModal(discord.ui.Modal, title="Lockdown & notice"):
    def __init__(self, panel, sect):
        super().__init__()
        self.panel = panel
        self.duration = discord.ui.TextInput(
            label="Lockdown duration (e.g. 5m)", default=_dur_str(sect.get("lockdown_seconds", 300))
        )
        self.notice = discord.ui.TextInput(
            label="Public notice ('{role}' = role; blank = off)",
            required=False,
            style=discord.TextStyle.long,
            default=sect.get("notice_message", ""),
        )
        self.add_item(self.duration)
        self.add_item(self.notice)

    async def on_submit(self, interaction):
        try:
            seconds = max(30, _dur(self.duration.value))
        except (ValueError, commands.BadArgument):
            return await interaction.response.send_message("Give a valid duration (e.g. `5m`).", ephemeral=True)
        await self.panel.cog._set_section_fields(
            self.panel.guild, "roleping", lockdown_seconds=seconds, notice_message=self.notice.value.strip()
        )
        self.panel._notice = "✅ Lockdown & notice updated."
        await self.panel._show(interaction)


class HoneypotModal(discord.ui.Modal, title="Honeypot settings"):
    def __init__(self, panel, sect):
        super().__init__()
        self.panel = panel
        self.exempt_after = discord.ui.TextInput(
            label="Exempt members here longer than (e.g. 7d)", default=_dur_str(sect["exempt_after_seconds"])
        )
        self.timeout_len = discord.ui.TextInput(
            label="Timeout length (e.g. 1h)", default=_dur_str(sect["action"].get("timeout_seconds", 3600))
        )
        self.add_item(self.exempt_after)
        self.add_item(self.timeout_len)

    async def on_submit(self, interaction):
        try:
            exempt_after = _dur(self.exempt_after.value)
            timeout = max(1, _dur(self.timeout_len.value))
        except (ValueError, commands.BadArgument):
            return await interaction.response.send_message("Give valid durations (e.g. `7d`, `1h`).", ephemeral=True)
        await self.panel.cog._set_section_fields(self.panel.guild, "honeypot", exempt_after_seconds=exempt_after)
        await self.panel.cog._set_action_field(self.panel.guild, "honeypot", "timeout_seconds", timeout)
        self.panel._notice = "✅ Honeypot settings updated."
        await self.panel._show(interaction)


class TimeoutModal(discord.ui.Modal, title="Timeout length"):
    def __init__(self, panel, detector, sect):
        super().__init__()
        self.panel = panel
        self.detector = detector
        self.timeout_len = discord.ui.TextInput(
            label="Timeout length (e.g. 1h)", default=_dur_str(sect["action"].get("timeout_seconds", 3600))
        )
        self.add_item(self.timeout_len)

    async def on_submit(self, interaction):
        try:
            timeout = max(1, _dur(self.timeout_len.value))
        except (ValueError, commands.BadArgument):
            return await interaction.response.send_message("Give a valid duration (e.g. `1h`).", ephemeral=True)
        await self.panel.cog._set_action_field(self.panel.guild, self.detector, "timeout_seconds", timeout)
        self.panel._notice = "✅ Timeout length updated."
        await self.panel._show(interaction)


class SigModal(discord.ui.Modal, title="Signature matching"):
    def __init__(self, panel, sect):
        super().__init__()
        self.panel = panel
        self.distance = discord.ui.TextInput(
            label="Match SimHash distance", default=str(sect.get("simhash_distance", 8))
        )
        self.add_item(self.distance)

    async def on_submit(self, interaction):
        try:
            distance = _pos_int(self.distance.value, 0)
        except ValueError:
            return await interaction.response.send_message("Give a whole number.", ephemeral=True)
        await self.panel.cog._set_section_fields(self.panel.guild, "signatures", simhash_distance=distance)
        self.panel._notice = "✅ Signature match distance updated."
        await self.panel._show(interaction)


class BanDmModal(discord.ui.Modal, title="Ban DM message"):
    def __init__(self, panel, current):
        super().__init__()
        self.panel = panel
        self.message = discord.ui.TextInput(
            label="DM before ban ({guild}/{member}/{reason})",
            required=False,
            style=discord.TextStyle.long,
            default=current or "",
            placeholder="Leave blank to send no DM before a ban.",
        )
        self.add_item(self.message)

    async def on_submit(self, interaction):
        value = self.message.value.strip() or None
        await self.panel.cog._set_top(self.panel.guild, "ban_dm_message", value)
        self.panel._notice = "✅ Ban DM " + ("updated." if value else "disabled.")
        await self.panel._show(interaction)
