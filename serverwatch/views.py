import time
import discord

from .serverwatch import ServerWatchError


# --------------------------------------------------------------------------- #
# Modals
# --------------------------------------------------------------------------- #
class CreateServerModal(discord.ui.Modal, title="Add Server"):
    def __init__(self, panel):
        super().__init__()
        self.panel = panel
        self.name = discord.ui.TextInput(label="Name", required=True, max_length=50, placeholder="Dustbowl 24/7")
        self.host = discord.ui.TextInput(label="Host / IP", required=True, max_length=255, placeholder="1.2.3.4")
        self.port = discord.ui.TextInput(label="Query port", required=True, max_length=5, default="27015")
        self.add_item(self.name)
        self.add_item(self.host)
        self.add_item(self.port)

    async def on_submit(self, interaction):
        try:
            port = int(self.port.value.strip())
        except ValueError:
            await interaction.response.send_message("Port must be a whole number.", ephemeral=True)
            return
        try:
            await self.panel.cog._add_server(self.panel.guild, self.name.value.strip(), self.host.value.strip(), port)
            self.panel.server_name = self.name.value.strip().lower()
            self.panel.page = "main"
            self.panel._selected_rule = None
            self.panel._notice = f"✅ Added `{self.name.value.strip()}`."
        except ServerWatchError as e:
            self.panel._notice = f"⚠️ {e}"
        await self.panel._show(interaction)


class ConnectionModal(discord.ui.Modal, title="Edit Connection"):
    def __init__(self, panel, server):
        super().__init__()
        self.panel = panel
        self.host = discord.ui.TextInput(
            label="Host / IP", default=str(server.get("host", "")), required=True, max_length=255
        )
        self.port = discord.ui.TextInput(
            label="Query port", default=str(server.get("port", "")), required=True, max_length=5
        )
        self.connect = discord.ui.TextInput(
            label="Connect override (optional)",
            default=str(server.get("connect_url") or ""),
            required=False,
            max_length=200,
            placeholder="blank = default. e.g. [Join](steam://connect/{server_address})",
        )
        self.add_item(self.host)
        self.add_item(self.port)
        self.add_item(self.connect)

    async def on_submit(self, interaction):
        try:
            port = int(self.port.value.strip())
        except ValueError:
            await interaction.response.send_message("Port must be a whole number.", ephemeral=True)
            return
        try:
            await self.panel.cog._set_connection(
                self.panel.guild, self.panel.server_name, self.host.value.strip(), port
            )
            await self.panel.cog._set_connect_url(
                self.panel.guild, self.panel.server_name, self.connect.value
            )
            self.panel._notice = "✅ Connection updated."
        except ServerWatchError as e:
            self.panel._notice = f"⚠️ {e}"
        await self.panel._show(interaction)


class ThresholdModal(discord.ui.Modal, title="Add Threshold"):
    def __init__(self, panel):
        super().__init__()
        self.panel = panel
        self.count = discord.ui.TextInput(label="Player count to ping at", required=True, max_length=4, placeholder="8")
        self.msg = discord.ui.TextInput(
            label="Ping message (optional)",
            style=discord.TextStyle.long,
            required=False,
            max_length=1500,
            placeholder="Leave blank for default. Use {map}, {current_players}, {role}…",
        )
        self.add_item(self.count)
        self.add_item(self.msg)

    async def on_submit(self, interaction):
        try:
            count = int(self.count.value.strip())
            if count <= 0:
                raise ValueError
        except ValueError:
            await interaction.response.send_message(
                "Player count must be a positive whole number.", ephemeral=True
            )
            return
        self.panel._pending_threshold = {"count": count, "message": self.msg.value.strip() or None}
        self.panel.page = "pick_role"
        self.panel._notice = f"Pick the role to ping at **{count}+** players."
        await self.panel._show(interaction)


class EditRuleMessageModal(discord.ui.Modal, title="Edit Ping Message"):
    def __init__(self, panel, rule_id, current):
        super().__init__()
        self.panel = panel
        self.rule_id = rule_id
        self.msg = discord.ui.TextInput(
            label="Ping message",
            style=discord.TextStyle.long,
            default=(current or "")[:1500],
            required=True,
            max_length=1500,
        )
        self.add_item(self.msg)

    async def on_submit(self, interaction):
        try:
            await self.panel.cog._edit_threshold_message(
                self.panel.guild, self.panel.server_name, self.rule_id, self.msg.value
            )
            self.panel._notice = "✅ Message updated."
        except ServerWatchError as e:
            self.panel._notice = f"⚠️ {e}"
        await self.panel._show(interaction)


class TemplateModal(discord.ui.Modal, title="Channel-name Template"):
    def __init__(self, panel, current):
        super().__init__()
        self.panel = panel
        self.template = discord.ui.TextInput(
            label="Template",
            default=(current or "")[:100],
            required=True,
            max_length=100,
            placeholder="{current_players}/{max_players} | {map}",
        )
        self.add_item(self.template)

    async def on_submit(self, interaction):
        try:
            await self.panel.cog._set_channelname_display(
                self.panel.guild, self.panel.server_name, template=self.template.value
            )
            self.panel._notice = "✅ Template updated."
        except ServerWatchError as e:
            self.panel._notice = f"⚠️ {e}"
        await self.panel._show(interaction)


class IntervalsModal(discord.ui.Modal, title="Timing Settings"):
    def __init__(self, panel, poll, rearm_grace, rename):
        super().__init__()
        self.panel = panel
        self.poll = discord.ui.TextInput(label="Poll interval (s, min 30)", default=str(poll), required=True, max_length=6)
        self.rearm = discord.ui.TextInput(
            label="Re-arm grace (s below threshold)", default=str(rearm_grace), required=True, max_length=7
        )
        self.rename = discord.ui.TextInput(
            label="Channel rename interval (s, min 300)", default=str(rename), required=True, max_length=6
        )
        self.add_item(self.poll)
        self.add_item(self.rearm)
        self.add_item(self.rename)

    async def on_submit(self, interaction):
        try:
            poll = int(self.poll.value.strip())
            rg = int(self.rearm.value.strip())
            rn = int(self.rename.value.strip())
        except ValueError:
            await interaction.response.send_message("All values must be whole numbers (seconds).", ephemeral=True)
            return
        await self.panel.cog._set_interval(self.panel.guild, "poll_interval", poll)
        await self.panel.cog._set_interval(self.panel.guild, "rearm_grace", rg)
        await self.panel.cog._set_interval(self.panel.guild, "rename_interval", rn)
        self.panel._notice = "✅ Timing settings updated."
        await self.panel._show(interaction)


# --------------------------------------------------------------------------- #
# Panel View
# --------------------------------------------------------------------------- #
class ServerWatchPanel(discord.ui.View):
    """Author-locked, sectioned configuration panel for a guild's tracked servers."""

    def __init__(self, cog, guild, author, server_name, *, timeout=300):
        super().__init__(timeout=timeout)
        self.cog = cog
        self.guild = guild
        self.author = author
        self.server_name = server_name  # lowercase key or None
        self.page = "main"
        self.message = None
        self._pending_threshold = None
        self._selected_rule = None
        self._notice = None

    # ---- access control -------------------------------------------------- #
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

    # ---- data access ----------------------------------------------------- #
    async def _server(self):
        servers = await self.cog.config.guild(self.guild).servers()
        if self.server_name and self.server_name in servers:
            return self.cog._normalize_server(servers[self.server_name])
        return None

    async def _all_servers(self):
        return await self.cog.config.guild(self.guild).servers()

    # ---- rendering ------------------------------------------------------- #
    async def _show(self, interaction):
        await self.build()
        await interaction.response.edit_message(embed=await self.render_embed(), view=self)

    def _add_back(self, row=4):
        back = discord.ui.Button(label="Back", emoji="◀️", style=discord.ButtonStyle.secondary, row=row)

        async def cb(interaction):
            self.page = "main"
            self._notice = None
            await self._show(interaction)

        back.callback = cb
        self.add_item(back)

    async def build(self):
        self.clear_items()
        s = await self._server()
        servers = await self._all_servers()
        page = self.page
        if page not in ("main", "intervals") and s is None:
            page = self.page = "main"

        if page == "main":
            self._build_main(s, servers)
        elif page == "connection":
            self._build_connection(s)
        elif page == "notify":
            self._build_notify(s)
        elif page == "status":
            self._build_status(s)
        elif page == "channelname":
            self._build_channelname(s)
        elif page == "intervals":
            self._build_intervals(s)
        elif page == "pick_role":
            self._build_pick_role(s)

    # ---- page builders --------------------------------------------------- #
    def _build_main(self, s, servers):
        if servers:
            options = []
            for key, sd in list(servers.items())[:24]:
                options.append(
                    discord.SelectOption(
                        label=str(sd.get("name", key))[:100], value=key, default=(key == self.server_name)
                    )
                )
            options.append(discord.SelectOption(label="Create new server", value="__create__", emoji="➕"))
            picker = discord.ui.Select(placeholder="Select a server…", options=options, row=0)

            async def picker_cb(interaction, picker=picker):
                value = picker.values[0]
                if value == "__create__":
                    await interaction.response.send_modal(CreateServerModal(self))
                    return
                self.server_name = value
                self.page = "main"
                self._selected_rule = None
                self._notice = None
                await self._show(interaction)

            picker.callback = picker_cb
            self.add_item(picker)
        else:
            create = discord.ui.Button(label="Create server", emoji="➕", style=discord.ButtonStyle.success, row=0)

            async def create_cb(interaction):
                await interaction.response.send_modal(CreateServerModal(self))

            create.callback = create_cb
            self.add_item(create)

        has_server = s is not None
        sections = [
            ("Connection", "connection"),
            ("Notify + Thresholds", "notify"),
            ("Status Embed", "status"),
            ("Channel Name", "channelname"),
            ("Intervals", "intervals"),
        ]
        for label, page in sections:
            disabled = (not has_server) and page != "intervals"
            btn = discord.ui.Button(label=label, style=discord.ButtonStyle.primary, row=1, disabled=disabled)
            btn.callback = self._make_nav(page)
            self.add_item(btn)

        refresh = discord.ui.Button(
            label="Refresh", emoji="🔄", style=discord.ButtonStyle.secondary, row=2, disabled=not has_server
        )
        refresh.callback = self._refresh_cb
        self.add_item(refresh)

        delete = discord.ui.Button(
            label="Delete", emoji="🗑️", style=discord.ButtonStyle.danger, row=2, disabled=not has_server
        )

        async def delete_cb(interaction):
            if not self.server_name:
                await self._show(interaction)
                return
            try:
                await self.cog._remove_server(self.guild, self.server_name)
                self._notice = "🗑️ Server deleted."
            except ServerWatchError as e:
                self._notice = f"⚠️ {e}"
            remaining = await self._all_servers()
            self.server_name = next(iter(remaining)) if remaining else None
            self._selected_rule = None
            self.page = "main"
            await self._show(interaction)

        delete.callback = delete_cb
        self.add_item(delete)

        close = discord.ui.Button(label="Close", style=discord.ButtonStyle.secondary, row=2)

        async def close_cb(interaction):
            for item in self.children:
                item.disabled = True
            self.stop()
            await interaction.response.edit_message(content="Configuration panel closed.", embed=None, view=self)

        close.callback = close_cb
        self.add_item(close)

    def _make_nav(self, page):
        async def cb(interaction):
            self.page = page
            self._notice = None
            await self._show(interaction)

        return cb

    async def _refresh_cb(self, interaction):
        s = await self._server()
        if not s:
            await self._show(interaction)
            return
        await interaction.response.defer()
        info = await self.cog._query(s)
        self.cog._cache[(self.guild.id, self.server_name)] = {
            "info": info,
            "online": info is not None,
            "ts": time.time(),
        }
        self._notice = "🔄 Refreshed."
        await self.build()
        await interaction.edit_original_response(embed=await self.render_embed(), view=self)

    def _build_connection(self, s):
        edit = discord.ui.Button(label="Edit Host / Port", emoji="✏️", style=discord.ButtonStyle.primary, row=0)

        async def cb(interaction):
            server = await self._server()
            if not server:
                await self._show(interaction)
                return
            await interaction.response.send_modal(ConnectionModal(self, server))

        edit.callback = cb
        self.add_item(edit)
        self._add_back()

    def _build_notify(self, s):
        cs = discord.ui.ChannelSelect(
            channel_types=[discord.ChannelType.text], placeholder="Set the notify channel…", row=0
        )

        async def cs_cb(interaction, cs=cs):
            try:
                await self.cog._set_notify_channel(self.guild, self.server_name, cs.values[0])
                self._notice = f"✅ Notify channel set to {cs.values[0].mention}."
            except ServerWatchError as e:
                self._notice = f"⚠️ {e}"
            await self._show(interaction)

        cs.callback = cs_cb
        self.add_item(cs)

        addb = discord.ui.Button(label="Add Threshold", emoji="➕", style=discord.ButtonStyle.success, row=1)

        async def add_cb(interaction):
            await interaction.response.send_modal(ThresholdModal(self))

        addb.callback = add_cb
        self.add_item(addb)

        rules = sorted(s.get("thresholds", []), key=lambda r: r["count"]) if s else []
        if rules:
            options = []
            for rule in rules[:25]:
                role = self.guild.get_role(rule["role_id"])
                options.append(
                    discord.SelectOption(
                        label=f"#{rule['id']}: {rule['count']}+ players"[:100],
                        description=(f"→ @{role.name}" if role else "→ (deleted role)")[:100],
                        value=str(rule["id"]),
                        default=(self._selected_rule == rule["id"]),
                    )
                )
            rsel = discord.ui.Select(placeholder="Select a rule to edit/remove…", options=options, row=2)

            async def rsel_cb(interaction, rsel=rsel):
                self._selected_rule = int(rsel.values[0])
                await self._show(interaction)

            rsel.callback = rsel_cb
            self.add_item(rsel)

            rm = discord.ui.Button(
                label="Remove Rule",
                emoji="🗑️",
                style=discord.ButtonStyle.danger,
                row=3,
                disabled=self._selected_rule is None,
            )

            async def rm_cb(interaction):
                try:
                    await self.cog._remove_threshold(self.guild, self.server_name, self._selected_rule)
                    self._notice = f"🗑️ Removed rule #{self._selected_rule}."
                    self._selected_rule = None
                except ServerWatchError as e:
                    self._notice = f"⚠️ {e}"
                await self._show(interaction)

            rm.callback = rm_cb
            self.add_item(rm)

            em = discord.ui.Button(
                label="Edit Message",
                emoji="✏️",
                style=discord.ButtonStyle.secondary,
                row=3,
                disabled=self._selected_rule is None,
            )

            async def em_cb(interaction):
                server = await self._server()
                current = ""
                for r in server.get("thresholds", []) if server else []:
                    if r["id"] == self._selected_rule:
                        current = r["message"]
                        break
                await interaction.response.send_modal(EditRuleMessageModal(self, self._selected_rule, current))

            em.callback = em_cb
            self.add_item(em)

        self._add_back()

    def _build_pick_role(self, s):
        rs = discord.ui.RoleSelect(placeholder="Pick the role to ping…", min_values=1, max_values=1, row=0)

        async def rs_cb(interaction, rs=rs):
            role = rs.values[0]
            pend = self._pending_threshold or {}
            try:
                rid = await self.cog._add_threshold(
                    self.guild, self.server_name, pend.get("count"), role, pend.get("message")
                )
                self._notice = f"✅ Added rule #{rid}: {pend.get('count')}+ players → {role.mention}"
            except ServerWatchError as e:
                self._notice = f"⚠️ {e}"
            self._pending_threshold = None
            self.page = "notify"
            await self._show(interaction)

        rs.callback = rs_cb
        self.add_item(rs)

        cancel = discord.ui.Button(label="Cancel", style=discord.ButtonStyle.secondary, row=1)

        async def cancel_cb(interaction):
            self._pending_threshold = None
            self.page = "notify"
            self._notice = "Cancelled."
            await self._show(interaction)

        cancel.callback = cancel_cb
        self.add_item(cancel)

    def _build_status(self, s):
        sm = s.get("status_message", {})
        enabled = sm.get("enabled")
        toggle = discord.ui.Button(
            label=("Disable" if enabled else "Enable"),
            style=(discord.ButtonStyle.danger if enabled else discord.ButtonStyle.success),
            row=0,
        )

        async def toggle_cb(interaction):
            try:
                await self.cog._set_status_display(self.guild, self.server_name, enabled=not enabled)
                self._notice = f"✅ Status message {'disabled' if enabled else 'enabled'}."
            except ServerWatchError as e:
                self._notice = f"⚠️ {e}"
            await self._show(interaction)

        toggle.callback = toggle_cb
        self.add_item(toggle)

        cs = discord.ui.ChannelSelect(
            channel_types=[discord.ChannelType.text], placeholder="Set the status-message channel…", row=1
        )

        async def cs_cb(interaction, cs=cs):
            try:
                await self.cog._set_status_display(self.guild, self.server_name, enabled=True, channel=cs.values[0])
                self._notice = f"✅ Status channel set to {cs.values[0].mention} (enabled)."
            except ServerWatchError as e:
                self._notice = f"⚠️ {e}"
            await self._show(interaction)

        cs.callback = cs_cb
        self.add_item(cs)

        is_embed = sm.get("embed", True)
        fmt = discord.ui.Button(
            label=f"Format: {'Embed' if is_embed else 'Text'}", style=discord.ButtonStyle.secondary, row=2
        )

        async def fmt_cb(interaction):
            try:
                await self.cog._set_status_display(self.guild, self.server_name, embed=not is_embed)
                self._notice = f"✅ Format set to {'text' if is_embed else 'embed'}."
            except ServerWatchError as e:
                self._notice = f"⚠️ {e}"
            await self._show(interaction)

        fmt.callback = fmt_cb
        self.add_item(fmt)
        self._add_back()

    def _build_channelname(self, s):
        cn = s.get("channel_name", {})
        enabled = cn.get("enabled")
        toggle = discord.ui.Button(
            label=("Disable" if enabled else "Enable"),
            style=(discord.ButtonStyle.danger if enabled else discord.ButtonStyle.success),
            row=0,
        )

        async def toggle_cb(interaction):
            try:
                await self.cog._set_channelname_display(self.guild, self.server_name, enabled=not enabled)
                self._notice = f"✅ Channel-name display {'disabled' if enabled else 'enabled'}."
            except ServerWatchError as e:
                self._notice = f"⚠️ {e}"
            await self._show(interaction)

        toggle.callback = toggle_cb
        self.add_item(toggle)

        cs = discord.ui.ChannelSelect(
            channel_types=[discord.ChannelType.text, discord.ChannelType.voice],
            placeholder="Set the channel to rename…",
            row=1,
        )

        async def cs_cb(interaction, cs=cs):
            try:
                await self.cog._set_channelname_display(
                    self.guild, self.server_name, enabled=True, channel=cs.values[0]
                )
                self._notice = f"✅ Channel set to {cs.values[0].mention} (enabled)."
            except ServerWatchError as e:
                self._notice = f"⚠️ {e}"
            await self._show(interaction)

        cs.callback = cs_cb
        self.add_item(cs)

        tmpl = discord.ui.Button(label="Edit Template", emoji="✏️", style=discord.ButtonStyle.secondary, row=2)

        async def tmpl_cb(interaction):
            server = await self._server()
            current = server.get("channel_name", {}).get("template", "") if server else ""
            await interaction.response.send_modal(TemplateModal(self, current))

        tmpl.callback = tmpl_cb
        self.add_item(tmpl)
        self._add_back()

    def _build_intervals(self, s):
        edit = discord.ui.Button(label="Edit Timing Settings", emoji="✏️", style=discord.ButtonStyle.primary, row=0)

        async def cb(interaction):
            gconf = self.cog.config.guild(self.guild)
            poll = await gconf.poll_interval()
            rg = await gconf.rearm_grace()
            rn = await gconf.rename_interval()
            await interaction.response.send_modal(IntervalsModal(self, poll, rg, rn))

        edit.callback = cb
        self.add_item(edit)
        self._add_back()

    # ---- embed ----------------------------------------------------------- #
    async def render_embed(self):
        s = await self._server()
        servers = await self._all_servers()
        embed = discord.Embed(title="⚙️ ServerWatch Configuration", colour=discord.Colour.blurple())
        if self._notice:
            embed.description = self._notice

        if not s:
            if servers:
                embed.add_field(
                    name="Select a server", value="Choose a server below, or create a new one.", inline=False
                )
            else:
                embed.add_field(name="No servers yet", value="Create your first server to begin.", inline=False)
            if self.page == "intervals":
                await self._add_intervals_field(embed)
            return embed

        cache = self.cog._cache.get((self.guild.id, self.server_name))
        info = cache["info"] if cache else None
        if info is not None:
            live = f"🟢 **{info.player_count}/{info.max_players}** on `{info.map_name}`"
        elif cache is not None:
            live = "🔴 Offline"
        else:
            live = "⏳ Not polled yet"
        embed.add_field(name=f"📡 {s['name']}", value=f"`{s['host']}:{s['port']}`\n{live}", inline=False)

        page = self.page
        if page == "notify":
            nc = s.get("notify_channel_id")
            embed.add_field(name="Notify channel", value=(f"<#{nc}>" if nc else "*not set*"), inline=False)
            rules = sorted(s.get("thresholds", []), key=lambda r: r["count"])
            if rules:
                state = s.get("ping_state", {})
                lines = []
                for rule in rules:
                    role = self.guild.get_role(rule["role_id"])
                    st = state.get(str(rule["id"]), {})
                    armed = "🟢 armed" if st.get("armed", True) else "⚪ fired"
                    lines.append(
                        f"**#{rule['id']}** {rule['count']}+ → "
                        f"{role.mention if role else '`deleted role`'} · {armed}"
                    )
                embed.add_field(name="Threshold rules", value="\n".join(lines)[:1024], inline=False)
            else:
                embed.add_field(name="Threshold rules", value="*none — add one below*", inline=False)
        elif page == "status":
            sm = s.get("status_message", {})
            ch = f"<#{sm['channel_id']}>" if sm.get("channel_id") else "*not set*"
            embed.add_field(
                name="Status message",
                value=(
                    f"State: {'🟢 enabled' if sm.get('enabled') else '⚪ disabled'}\n"
                    f"Channel: {ch}\n"
                    f"Format: {'embed' if sm.get('embed', True) else 'text'}"
                ),
                inline=False,
            )
        elif page == "channelname":
            cn = s.get("channel_name", {})
            ch = f"<#{cn['channel_id']}>" if cn.get("channel_id") else "*not set*"
            embed.add_field(
                name="Channel-name display",
                value=(
                    f"State: {'🟢 enabled' if cn.get('enabled') else '⚪ disabled'}\n"
                    f"Channel: {ch}\n"
                    f"Template: `{cn.get('template', '')}`\n"
                    "*Updates roughly every 5-6 min (Discord rate limit).*"
                ),
                inline=False,
            )
        elif page == "connection":
            co = s.get("connect_url")
            embed.add_field(
                name="Connection",
                value=(
                    f"Host: `{s['host']}`\nQuery port: `{s['port']}`\n"
                    f"Connect override: {f'`{co}`' if co else '*default*'}"
                ),
                inline=False,
            )
        elif page == "intervals":
            await self._add_intervals_field(embed)
        elif page == "pick_role":
            pend = self._pending_threshold or {}
            embed.add_field(
                name="New threshold",
                value=f"Pinging at **{pend.get('count')}+** players. Pick the role below.",
                inline=False,
            )

        return embed

    async def _add_intervals_field(self, embed):
        gconf = self.cog.config.guild(self.guild)
        poll = await gconf.poll_interval()
        rg = await gconf.rearm_grace()
        rn = await gconf.rename_interval()
        embed.add_field(
            name="Timing (guild-wide)",
            value=(
                f"Poll interval: **{poll}s**\n"
                f"Re-arm grace: **{rg}s** (sustained drop below a threshold before it re-arms)\n"
                f"Channel-rename interval: **{rn}s**"
            ),
            inline=False,
        )
