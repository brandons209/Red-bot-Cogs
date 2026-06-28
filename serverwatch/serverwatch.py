import discord
from redbot.core import commands, Config, checks
from redbot.core.utils.chat_formatting import error, info, warning, pagify

import a2s
import time
import asyncio
from typing import Optional, Union

IDENTIFIER = 290784512097430981
BASE_TICK = 30  # seconds the loop sleeps between ticks
QUERY_TIMEOUT = 3.0  # A2S query timeout (seconds)
MIN_POLL = 30  # minimum poll interval (seconds)
MIN_RENAME = 300  # minimum channel-rename interval (Discord rate limit)

DEFAULT_CHANNELNAME_TEMPLATE = "🟢 {current_players}/{max_players} | {map}"
DEFAULT_THRESHOLD_MESSAGE = (
    "{role} The server **{server_name}** just hit **{current_players}/{max_players}** "
    "players on `{map}`! Come join: `{server_address}`"
)


class ServerWatchError(Exception):
    """Raised by config helpers on validation failure; rendered by each front-end."""

    pass


class ServerWatch(commands.Cog):
    """
    Track TF2 / Source-engine game servers over the A2S protocol.

    Poll player count, map and status in real time; ping roles when player-count
    thresholds are crossed; and show live status via an auto-refreshed message or a
    renamed voice/text channel. Configure with commands or the interactive
    `[p]serverwatch panel`.
    """

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=IDENTIFIER, force_registration=True)

        default_guild = {
            "servers": {},  # name.lower() -> server dict
            "poll_interval": 60,
            "rearm_grace": 120,  # seconds below a threshold before its alert re-arms
            "cooldown": 1800,  # minimum seconds between pings of the same rule
            "rename_interval": 360,
        }
        self.config.register_guild(**default_guild)

        # runtime caches (not persisted)
        self._cache = {}  # (guild_id, name) -> {"info": SourceInfo|None, "online": bool, "ts": float}
        self._last_rename = {}  # (guild_id, name) -> float
        self._last_poll = {}  # guild_id -> float

        self.task = asyncio.create_task(self.watch_loop())

    def cog_unload(self):
        self.task.cancel()

    async def red_delete_data_for_user(self, *, requester, user_id):
        # This cog stores no per-user data.
        pass

    # ------------------------------------------------------------------ #
    # Config structure helpers
    # ------------------------------------------------------------------ #
    def _default_server(self, name, host, port):
        return {
            "name": name,
            "host": host,
            "port": port,
            "connect_url": None,
            "notify_channel_id": None,
            "thresholds": [],
            "next_threshold_id": 1,
            "ping_state": {},
            "status_message": {"enabled": False, "channel_id": None, "message_id": None, "embed": True},
            "channel_name": {"enabled": False, "channel_id": None, "template": DEFAULT_CHANNELNAME_TEMPLATE},
        }

    def _normalize_server(self, s):
        """Apply defaults to an in-memory server dict so older saved data gains new keys."""
        s.setdefault("name", "Unknown")
        s.setdefault("host", "")
        s.setdefault("port", 27015)
        s.setdefault("connect_url", None)
        s.setdefault("notify_channel_id", None)
        s.setdefault("thresholds", [])
        s.setdefault("next_threshold_id", max((r.get("id", 0) for r in s["thresholds"]), default=0) + 1)
        s.setdefault("ping_state", {})
        sm = s.setdefault("status_message", {})
        sm.setdefault("enabled", False)
        sm.setdefault("channel_id", None)
        sm.setdefault("message_id", None)
        sm.setdefault("embed", True)
        cn = s.setdefault("channel_name", {})
        cn.setdefault("enabled", False)
        cn.setdefault("channel_id", None)
        cn.setdefault("template", DEFAULT_CHANNELNAME_TEMPLATE)
        return s

    # ------------------------------------------------------------------ #
    # Shared config helpers (single source of truth for commands + UI)
    # ------------------------------------------------------------------ #
    async def _add_server(self, guild, name, host, port):
        key = name.lower()
        if not name:
            raise ServerWatchError("Server name cannot be empty.")
        if not (1 <= port <= 65535):
            raise ServerWatchError("Port must be between 1 and 65535.")
        async with self.config.guild(guild).servers() as servers:
            if key in servers:
                raise ServerWatchError(f"A server named `{name}` already exists.")
            servers[key] = self._default_server(name, host, port)

    async def _remove_server(self, guild, name):
        key = name.lower()
        async with self.config.guild(guild).servers() as servers:
            if key not in servers:
                raise ServerWatchError(f"No server named `{name}`.")
            del servers[key]
        self._cache.pop((guild.id, key), None)
        self._last_rename.pop((guild.id, key), None)

    async def _set_connection(self, guild, name, host, port):
        key = name.lower()
        if not (1 <= port <= 65535):
            raise ServerWatchError("Port must be between 1 and 65535.")
        async with self.config.guild(guild).servers() as servers:
            s = servers.get(key)
            if not s:
                raise ServerWatchError(f"No server named `{name}`.")
            s["host"] = host
            s["port"] = port
        self._cache.pop((guild.id, key), None)

    async def _set_connect_url(self, guild, name, url):
        key = name.lower()
        async with self.config.guild(guild).servers() as servers:
            s = servers.get(key)
            if not s:
                raise ServerWatchError(f"No server named `{name}`.")
            s["connect_url"] = url.strip() if url and url.strip() else None

    async def _set_notify_channel(self, guild, name, channel):
        key = name.lower()
        async with self.config.guild(guild).servers() as servers:
            s = servers.get(key)
            if not s:
                raise ServerWatchError(f"No server named `{name}`.")
            s["notify_channel_id"] = channel.id if channel else None

    async def _add_threshold(self, guild, name, count, role, message=None):
        key = name.lower()
        if count is None or count <= 0:
            raise ServerWatchError("Player-count threshold must be greater than 0.")
        async with self.config.guild(guild).servers() as servers:
            s = servers.get(key)
            if not s:
                raise ServerWatchError(f"No server named `{name}`.")
            self._normalize_server(s)
            rule_id = s["next_threshold_id"]
            s["next_threshold_id"] += 1
            s["thresholds"].append(
                {
                    "id": rule_id,
                    "count": count,
                    "role_id": role.id,
                    "message": message or DEFAULT_THRESHOLD_MESSAGE,
                }
            )
            # Disarm if already at/above the count, so an already-full server doesn't
            # ping until it drains and refills.
            cached = self._cache.get((guild.id, key))
            cur = cached["info"].player_count if cached and cached.get("info") is not None else None
            armed = not (cur is not None and cur >= count)
            s["ping_state"][str(rule_id)] = {"armed": armed, "below_since": None, "last_ping": 0.0}
        return rule_id

    async def _remove_threshold(self, guild, name, rule_id):
        key = name.lower()
        async with self.config.guild(guild).servers() as servers:
            s = servers.get(key)
            if not s:
                raise ServerWatchError(f"No server named `{name}`.")
            before = len(s.get("thresholds", []))
            s["thresholds"] = [r for r in s.get("thresholds", []) if r.get("id") != rule_id]
            if len(s["thresholds"]) == before:
                raise ServerWatchError(f"No threshold rule with id {rule_id} on `{s.get('name', name)}`.")
            s.get("ping_state", {}).pop(str(rule_id), None)

    async def _edit_threshold_message(self, guild, name, rule_id, message):
        key = name.lower()
        async with self.config.guild(guild).servers() as servers:
            s = servers.get(key)
            if not s:
                raise ServerWatchError(f"No server named `{name}`.")
            for rule in s.get("thresholds", []):
                if rule.get("id") == rule_id:
                    rule["message"] = message
                    return
            raise ServerWatchError(f"No threshold rule with id {rule_id}.")

    async def _set_status_display(self, guild, name, *, enabled=None, channel=None, embed=None):
        key = name.lower()
        to_delete = None
        async with self.config.guild(guild).servers() as servers:
            s = servers.get(key)
            if not s:
                raise ServerWatchError(f"No server named `{name}`.")
            self._normalize_server(s)
            sm = s["status_message"]
            if channel is not None:
                if sm["channel_id"] and sm["message_id"] and sm["channel_id"] != channel.id:
                    to_delete = (sm["channel_id"], sm["message_id"])
                sm["channel_id"] = channel.id
                sm["message_id"] = None
            if embed is not None:
                sm["embed"] = embed
            if enabled is not None:
                if not enabled and sm["channel_id"] and sm["message_id"]:
                    to_delete = (sm["channel_id"], sm["message_id"])
                sm["enabled"] = enabled
                if not enabled:
                    sm["message_id"] = None
        if to_delete:
            await self._safe_delete_message(guild, *to_delete)

    async def _set_channelname_display(self, guild, name, *, enabled=None, channel=None, template=None):
        key = name.lower()
        async with self.config.guild(guild).servers() as servers:
            s = servers.get(key)
            if not s:
                raise ServerWatchError(f"No server named `{name}`.")
            self._normalize_server(s)
            cn = s["channel_name"]
            if channel is not None:
                cn["channel_id"] = channel.id
            if template is not None:
                cn["template"] = template
            if enabled is not None:
                cn["enabled"] = enabled
        # reset the rename gate so the change is reflected on the next tick
        self._last_rename.pop((guild.id, key), None)

    async def _set_interval(self, guild, key, seconds):
        if key == "poll_interval":
            seconds = max(MIN_POLL, seconds)
        elif key == "rename_interval":
            seconds = max(MIN_RENAME, seconds)
        elif key in ("rearm_grace", "cooldown"):
            seconds = max(0, seconds)
        else:
            raise ServerWatchError("Unknown interval setting.")
        await self.config.guild(guild).set_raw(key, value=seconds)
        return seconds

    async def _safe_delete_message(self, guild, channel_id, message_id):
        channel = guild.get_channel(channel_id)
        if not channel:
            return
        try:
            msg = await channel.fetch_message(message_id)
            await msg.delete()
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            pass

    # ------------------------------------------------------------------ #
    # A2S query + templating + rendering
    # ------------------------------------------------------------------ #
    async def _query(self, server):
        host = server.get("host")
        port = server.get("port")
        if not host or not port:
            return None
        # Any failure (timeout, bad host, protocol error) means the server is offline.
        try:
            return await a2s.ainfo((host, int(port)), timeout=QUERY_TIMEOUT)
        except Exception:
            return None

    def _format_template(self, template, *, server, info, role=None, threshold=None):
        addr = f"{server.get('host')}:{server.get('port')}"
        values = {
            "server_display_name": server.get("name", "Unknown"),
            "server_address": addr,
            "threshold": threshold if threshold is not None else "",
            "role": role.mention if role else "",
        }
        if info is not None:
            values.update(
                current_players=info.player_count,
                human_players=max(0, info.player_count - info.bot_count),
                bot_count=info.bot_count,
                max_players=info.max_players,
                map=info.map_name,
                game=info.game,
                server_name=info.server_name,
                ping=round(info.ping * 1000),
                vac="VAC Secured" if info.vac_enabled else "Insecure",
                password="🔒" if info.password_protected else "",
            )
        else:
            values.update(
                current_players=0,
                human_players=0,
                bot_count=0,
                max_players=0,
                map="N/A",
                game="N/A",
                server_name=server.get("name", "Unknown"),
                ping=0,
                vac="N/A",
                password="",
            )
        try:
            return template.format(**values)
        except (KeyError, IndexError, ValueError):
            return template

    def _connect_value(self, s, info):
        """The 'Connect' field value: a custom override (placeholders allowed) or the default."""
        override = s.get("connect_url")
        if override:
            return self._format_template(override, server=s, info=info)
        return f"`connect {s.get('host')}:{s.get('port')}`"

    def _build_embed(self, s, info):
        online = info is not None
        name = info.server_name if online else s.get("name", "Unknown")
        colour = discord.Colour.green() if online else discord.Colour.red()
        embed = discord.Embed(
            title=str(name)[:256],
            colour=colour,
            description="🟢 Online" if online else "🔴 Offline",
            timestamp=discord.utils.utcnow(),
        )
        addr = f"{s.get('host')}:{s.get('port')}"
        if online:
            players = f"{info.player_count}/{info.max_players}"
            if info.bot_count:
                players += f" ({info.bot_count} bots)"
            embed.add_field(name="Players", value=players)
            embed.add_field(name="Map", value=info.map_name or "Unknown")
            embed.add_field(name="Game", value=info.game or "Unknown")
            embed.add_field(name="Connect", value=self._connect_value(s, info), inline=False)
            embed.add_field(name="Ping", value=f"{round(info.ping * 1000)} ms")
            sec = "VAC Secured" if info.vac_enabled else "Insecure"
            if info.password_protected:
                sec += " · 🔒"
            embed.add_field(name="Security", value=sec)
        else:
            embed.add_field(name="Address", value=f"`{addr}`")
        embed.set_footer(text="Last updated")
        return embed

    def _build_text_status(self, s, info):
        addr = f"{s.get('host')}:{s.get('port')}"
        if info is None:
            return f"🔴 **{s.get('name', 'Unknown')}** is **offline**. (`{addr}`)"
        bots = f" ({info.bot_count} bots)" if info.bot_count else ""
        return (
            f"🟢 **{info.server_name}**\n"
            f"Players: **{info.player_count}/{info.max_players}**{bots}  |  "
            f"Map: `{info.map_name}`  |  Ping: {round(info.ping * 1000)} ms\n"
            f"Connect: {self._connect_value(s, info)}  ·  Updated <t:{int(time.time())}:R>"
        )

    def _render_status(self, s, info, use_embed=True):
        if use_embed:
            return None, self._build_embed(s, info)
        return self._build_text_status(s, info), None

    # ------------------------------------------------------------------ #
    # Background loop
    # ------------------------------------------------------------------ #
    async def watch_loop(self):
        await self.bot.wait_until_ready()
        while True:
            try:
                await self.server_loop()
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[ServerWatch] Internal loop crashed, restarting in 10s... {e}")
                await asyncio.sleep(10)

    async def server_loop(self):
        while True:
            now = time.time()
            for guild in list(self.bot.guilds):
                try:
                    if await self.bot.cog_disabled_in_guild(self, guild):
                        continue
                except Exception:
                    continue

                gconf = self.config.guild(guild)
                poll_interval = max(MIN_POLL, await gconf.poll_interval())
                if (now - self._last_poll.get(guild.id, 0)) < poll_interval:
                    continue
                self._last_poll[guild.id] = now

                rename_interval = max(MIN_RENAME, await gconf.rename_interval())
                rearm_grace = await gconf.rearm_grace()
                cooldown = await gconf.cooldown()
                servers = await gconf.servers()

                for key in list(servers.keys()):
                    s = self._normalize_server(servers[key])
                    info = await self._query(s)
                    self._cache[(guild.id, key)] = {"info": info, "online": info is not None, "ts": now}

                    # Fast: refresh the live status message/embed
                    await self._update_status_message(guild, key, s, info)
                    # Fast: evaluate thresholds (reads/writes live config inside)
                    await self._evaluate_thresholds(guild, key, info, rearm_grace, cooldown)
                    # Slow: channel rename, gated by elapsed time per server
                    if (now - self._last_rename.get((guild.id, key), 0)) >= rename_interval:
                        await self._update_channel_name(guild, key, s, info)
                        # Record the attempt either way so a 429/no-op backs off a full interval.
                        self._last_rename[(guild.id, key)] = now

            await asyncio.sleep(BASE_TICK)

    async def _update_status_message(self, guild, key, s, info):
        cfg = s.get("status_message", {})
        if not cfg.get("enabled") or not cfg.get("channel_id"):
            return
        channel = guild.get_channel(cfg["channel_id"])
        if channel is None:
            return
        content, embed = self._render_status(s, info, use_embed=cfg.get("embed", True))

        msg = None
        mid = cfg.get("message_id")
        if mid:
            try:
                msg = await channel.fetch_message(mid)
            except discord.NotFound:
                msg = None
            except (discord.Forbidden, discord.HTTPException):
                return
        try:
            if msg:
                await msg.edit(content=content, embed=embed)
            else:
                new = await channel.send(content=content, embed=embed)
                async with self.config.guild(guild).servers() as servers:
                    if key in servers:
                        servers[key].setdefault("status_message", {})["message_id"] = new.id
        except discord.HTTPException:
            return

    async def _evaluate_thresholds(self, guild, key, info, rearm_grace, cooldown):
        async with self.config.guild(guild).servers() as servers:
            s = servers.get(key)
            if not s:
                return
            self._normalize_server(s)
            state = s["ping_state"]

            # prune orphaned state for deleted rules
            live_ids = {str(r["id"]) for r in s["thresholds"]}
            for stale in [k for k in list(state.keys()) if k not in live_ids]:
                del state[stale]

            # Offline: HOLD state — neither re-arm nor fire (avoids flap spam).
            if info is None:
                return

            current = info.player_count
            now = time.time()
            notify_channel = (
                guild.get_channel(s.get("notify_channel_id")) if s.get("notify_channel_id") else None
            )

            for rule in s["thresholds"]:
                rid = str(rule["id"])
                st = state.setdefault(rid, {"armed": True, "below_since": None, "last_ping": 0.0})
                threshold = rule["count"]

                if current < threshold:
                    # Re-arm only after a sustained drop (>= rearm_grace), so a brief dip
                    # like a map change doesn't reset the alert and cause a repeat ping.
                    if st.get("below_since") is None:
                        st["below_since"] = now
                    if not st.get("armed", True) and (now - st["below_since"]) >= rearm_grace:
                        st["armed"] = True
                    continue

                # back above the threshold — cancel any pending re-arm
                st["below_since"] = None

                # Fire once per crossing (gated by `armed`), and at most once per `cooldown`
                # so a population hovering around the threshold can't spam.
                if st.get("armed", True) and (now - st.get("last_ping", 0.0)) >= cooldown:
                    role = guild.get_role(rule["role_id"])
                    if notify_channel and role:
                        msg = self._format_template(
                            rule["message"], server=s, info=info, role=role, threshold=threshold
                        )
                        try:
                            await notify_channel.send(
                                msg,
                                allowed_mentions=discord.AllowedMentions(
                                    roles=[role], everyone=False, users=False
                                ),
                            )
                            st["armed"] = False
                            st["last_ping"] = now
                        except discord.HTTPException:
                            pass  # missing perms / deleted channel — retry next poll

    async def _update_channel_name(self, guild, key, s, info):
        cfg = s.get("channel_name", {})
        if not cfg.get("enabled") or not cfg.get("channel_id"):
            return False
        channel = guild.get_channel(cfg["channel_id"])
        if channel is None:
            return False
        new_name = self._format_template(
            cfg.get("template", DEFAULT_CHANNELNAME_TEMPLATE), server=s, info=info
        )[:100]
        if not new_name or channel.name == new_name:
            return False
        try:
            await channel.edit(name=new_name)
            return True
        except discord.HTTPException:
            return False

    # ------------------------------------------------------------------ #
    # Command tree
    # ------------------------------------------------------------------ #
    async def _require_server(self, ctx, name):
        servers = await self.config.guild(ctx.guild).servers()
        s = servers.get(name.lower())
        if not s:
            await ctx.reply(
                error(f"No server named `{name}`. See `{ctx.clean_prefix}serverwatch list`."),
                delete_after=30,
                mention_author=False,
            )
            return None
        return self._normalize_server(s)

    @commands.group(name="serverwatch", aliases=["swatch"])
    @commands.guild_only()
    @checks.admin_or_permissions(administrator=True)
    async def serverwatch(self, ctx):
        """Track TF2 / Source game servers and ping roles when they fill up."""
        pass

    @serverwatch.command(name="panel")
    @checks.bot_has_permissions(embed_links=True)
    async def sw_panel(self, ctx, *, name: Optional[str] = None):
        """Open the interactive configuration panel."""
        from .views import ServerWatchPanel

        servers = await self.config.guild(ctx.guild).servers()
        if name and name.lower() not in servers:
            await ctx.reply(error(f"No server named `{name}`."), delete_after=30, mention_author=False)
            return
        start = name.lower() if name else (next(iter(servers)) if servers else None)
        view = ServerWatchPanel(self, ctx.guild, ctx.author, start)
        await view.build()
        embed = await view.render_embed()
        view.message = await ctx.send(embed=embed, view=view)

    @serverwatch.command(name="add")
    async def sw_add(self, ctx, name: str, host: str, port: int):
        """
        Register a game server to track.

        Quote names containing spaces, e.g. `[p]serverwatch add "Dustbowl 24/7" 1.2.3.4 27015`.
        """
        try:
            await self._add_server(ctx.guild, name, host, port)
        except ServerWatchError as e:
            await ctx.reply(error(str(e)), delete_after=30, mention_author=False)
            return
        # Best-effort reachability test (non-blocking failure).
        info = await self._query({"host": host, "port": port})
        if info is None:
            await ctx.send(
                warning(
                    f"Added `{name}`, but I couldn't reach `{host}:{port}` right now. "
                    "Double-check the host and **query port** (often the game port for Source)."
                )
            )
        await ctx.tick()

    @serverwatch.command(name="remove", aliases=["del", "delete"])
    async def sw_remove(self, ctx, *, name: str):
        """Stop tracking a server and delete its settings."""
        try:
            await self._remove_server(ctx.guild, name)
        except ServerWatchError as e:
            await ctx.reply(error(str(e)), delete_after=30, mention_author=False)
            return
        await ctx.tick()

    @serverwatch.command(name="connection", aliases=["setaddress"])
    async def sw_connection(self, ctx, name: str, host: str, port: int):
        """Update a server's host and query port."""
        try:
            await self._set_connection(ctx.guild, name, host, port)
        except ServerWatchError as e:
            await ctx.reply(error(str(e)), delete_after=30, mention_author=False)
            return
        await ctx.tick()

    @serverwatch.command(name="connecturl", aliases=["connectlink", "joinurl"])
    async def sw_connecturl(self, ctx, name: str, *, url: Optional[str] = None):
        """
        Override the "Connect" line shown in the status embed/message.

        Leave blank to reset to the default `connect <ip:port>`. Placeholders like
        {server_address} are filled in. To make a one-click TF2 join link, use a masked
        link, e.g.:
        `.serverwatch connecturl ponezone [Click to join](steam://connect/{server_address})`
        """
        try:
            await self._set_connect_url(ctx.guild, name, url)
        except ServerWatchError as e:
            await ctx.reply(error(str(e)), delete_after=30, mention_author=False)
            return
        await ctx.send(
            info(f"Connect override {'cleared' if not url else 'set'} for `{name}`.")
        )
        await ctx.tick()

    @serverwatch.command(name="list")
    async def sw_list(self, ctx):
        """List all tracked servers and their current status."""
        servers = await self.config.guild(ctx.guild).servers()
        if not servers:
            await ctx.send(info(f"No servers tracked. Add one with `{ctx.clean_prefix}serverwatch add`."))
            return
        lines = []
        for key, s in servers.items():
            s = self._normalize_server(s)
            cache = self._cache.get((ctx.guild.id, key))
            info_obj = cache["info"] if cache else None
            if cache is None:
                info_obj = await self._query(s)
            if info_obj is not None:
                lines.append(
                    f"🟢 **{s['name']}** — {info_obj.player_count}/{info_obj.max_players} on "
                    f"`{info_obj.map_name}` (`{s['host']}:{s['port']}`)"
                )
            else:
                lines.append(f"🔴 **{s['name']}** — offline (`{s['host']}:{s['port']}`)")
        for page in pagify("\n".join(lines), page_length=1900):
            await ctx.send(page)

    @serverwatch.command(name="status")
    async def sw_status(self, ctx, *, name: str):
        """Show detailed live status and config summary for a server."""
        s = await self._require_server(ctx, name)
        if not s:
            return
        async with ctx.typing():
            info_obj = await self._query(s)
        embed = self._build_embed(s, info_obj)

        # config summary
        nc = s.get("notify_channel_id")
        sm = s.get("status_message", {})
        cn = s.get("channel_name", {})
        summary = [
            f"Notify channel: {f'<#{nc}>' if nc else '*not set*'}",
            f"Thresholds: {len(s.get('thresholds', []))}",
            f"Status message: {'on' if sm.get('enabled') else 'off'}"
            + (f" in <#{sm['channel_id']}>" if sm.get("channel_id") else "")
            + (f" ({'embed' if sm.get('embed') else 'text'})" if sm.get("enabled") else ""),
            f"Channel-name display: {'on' if cn.get('enabled') else 'off'}"
            + (f" in <#{cn['channel_id']}>" if cn.get("channel_id") else ""),
        ]
        embed.add_field(name="Configuration", value="\n".join(summary), inline=False)
        await ctx.send(embed=embed)

    @serverwatch.command(name="check")
    async def sw_check(self, ctx, *, name: str):
        """Query a server right now, including its player list."""
        s = await self._require_server(ctx, name)
        if not s:
            return
        async with ctx.typing():
            info_obj = await self._query(s)
            players = None
            if info_obj is not None:
                try:
                    players = await a2s.aplayers((s["host"], int(s["port"])), timeout=QUERY_TIMEOUT)
                except (asyncio.TimeoutError, a2s.BrokenMessageError, a2s.BufferExhaustedError, OSError):
                    players = None
        embed = self._build_embed(s, info_obj)
        if players:
            top = sorted(players, key=lambda p: p.score, reverse=True)[:15]
            plist = "\n".join(f"`{p.score:>4}` {p.name or '<connecting>'}" for p in top)
            embed.add_field(name=f"Players ({len(players)})", value=plist[:1024], inline=False)
        await ctx.send(embed=embed)

    @serverwatch.command(name="notifychannel")
    async def sw_notifychannel(self, ctx, name: str, channel: discord.TextChannel):
        """Set the channel where this server's threshold pings are sent."""
        if not channel.permissions_for(ctx.me).send_messages:
            await ctx.reply(
                warning(f"I can't send messages in {channel.mention}; pings there will fail."),
                mention_author=False,
            )
        try:
            await self._set_notify_channel(ctx.guild, name, channel)
        except ServerWatchError as e:
            await ctx.reply(error(str(e)), delete_after=30, mention_author=False)
            return
        await ctx.tick()

    # --- thresholds ---------------------------------------------------- #
    @serverwatch.group(name="threshold", aliases=["thresh"])
    async def sw_threshold(self, ctx):
        """Manage player-count threshold ping rules."""
        pass

    @sw_threshold.command(name="add")
    async def sw_threshold_add(self, ctx, name: str, count: int, role: discord.Role, *, message: Optional[str] = None):
        """
        Add a rule that pings a role when the server reaches a player count.

        Pings go to the server's notify channel. Leave the message blank for a default.

        Placeholders you can use in the message:
        {current_players} {human_players} {bot_count} {max_players} {map} {game}
        {server_name} {server_display_name} {server_address} {ping} {role} {threshold} {vac} {password}
        """
        try:
            rule_id = await self._add_threshold(ctx.guild, name, count, role, message)
        except ServerWatchError as e:
            await ctx.reply(error(str(e)), delete_after=30, mention_author=False)
            return
        # warn if the count exceeds the server's known max
        cache = self._cache.get((ctx.guild.id, name.lower()))
        if cache and cache.get("info") is not None and count > cache["info"].max_players:
            await ctx.send(
                warning(f"Heads up: {count} is above the server's max of {cache['info'].max_players} — it may never fire.")
            )
        await ctx.send(info(f"Added threshold rule **#{rule_id}**: {count}+ players → {role.mention}."))
        await ctx.tick()

    @sw_threshold.command(name="remove", aliases=["del", "delete"])
    async def sw_threshold_remove(self, ctx, name: str, rule_id: int):
        """Remove a threshold rule by its id (see `threshold list`)."""
        try:
            await self._remove_threshold(ctx.guild, name, rule_id)
        except ServerWatchError as e:
            await ctx.reply(error(str(e)), delete_after=30, mention_author=False)
            return
        await ctx.tick()

    @sw_threshold.command(name="message", aliases=["msg"])
    async def sw_threshold_message(self, ctx, name: str, rule_id: int, *, message: str):
        """Edit the ping message of an existing threshold rule."""
        try:
            await self._edit_threshold_message(ctx.guild, name, rule_id, message)
        except ServerWatchError as e:
            await ctx.reply(error(str(e)), delete_after=30, mention_author=False)
            return
        await ctx.tick()

    @sw_threshold.command(name="list")
    async def sw_threshold_list(self, ctx, *, name: str):
        """List a server's threshold rules and their current state."""
        s = await self._require_server(ctx, name)
        if not s:
            return
        rules = s.get("thresholds", [])
        if not rules:
            await ctx.send(info(f"`{s['name']}` has no threshold rules."))
            return
        state = s.get("ping_state", {})
        lines = []
        for rule in sorted(rules, key=lambda r: r["count"]):
            st = state.get(str(rule["id"]), {})
            role = ctx.guild.get_role(rule["role_id"])
            armed = "armed" if st.get("armed", True) else "fired (waiting to re-arm)"
            lines.append(
                f"**#{rule['id']}** — {rule['count']}+ players → {role.mention if role else '`deleted role`'} · {armed}\n"
                f"> {rule['message'][:150]}"
            )
        for page in pagify("\n".join(lines), page_length=1900):
            await ctx.send(page)

    # --- status message display --------------------------------------- #
    @serverwatch.group(name="display")
    async def sw_display(self, ctx):
        """Configure the auto-refreshed live status message."""
        pass

    @sw_display.command(name="enable")
    @checks.bot_has_permissions(send_messages=True, embed_links=True)
    async def sw_display_enable(self, ctx, name: str, channel: discord.TextChannel, embed: bool = True):
        """Post and auto-refresh a live status message in a channel."""
        try:
            await self._set_status_display(ctx.guild, name, enabled=True, channel=channel, embed=embed)
        except ServerWatchError as e:
            await ctx.reply(error(str(e)), delete_after=30, mention_author=False)
            return
        await ctx.send(info(f"Live status for `{name}` will update in {channel.mention} (refreshes on each poll)."))
        await ctx.tick()

    @sw_display.command(name="disable")
    async def sw_display_disable(self, ctx, *, name: str):
        """Stop and remove the live status message."""
        try:
            await self._set_status_display(ctx.guild, name, enabled=False)
        except ServerWatchError as e:
            await ctx.reply(error(str(e)), delete_after=30, mention_author=False)
            return
        await ctx.tick()

    @sw_display.command(name="format")
    async def sw_display_format(self, ctx, name: str, style: str):
        """Set the status message style: `embed` or `text`."""
        style = style.lower()
        if style not in ("embed", "text"):
            await ctx.reply(error("Style must be `embed` or `text`."), delete_after=30, mention_author=False)
            return
        try:
            await self._set_status_display(ctx.guild, name, embed=(style == "embed"))
        except ServerWatchError as e:
            await ctx.reply(error(str(e)), delete_after=30, mention_author=False)
            return
        await ctx.tick()

    # --- channel-name display ----------------------------------------- #
    @serverwatch.group(name="channelname", aliases=["chname"])
    async def sw_channelname(self, ctx):
        """Configure the channel-name live display (rate-limited; slow cadence)."""
        pass

    @sw_channelname.command(name="enable")
    @checks.bot_has_permissions(manage_channels=True)
    async def sw_channelname_enable(
        self, ctx, name: str, channel: Union[discord.VoiceChannel, discord.TextChannel]
    ):
        """Rename a voice/text channel to show live server info (updates ~every 5-6 min)."""
        try:
            await self._set_channelname_display(ctx.guild, name, enabled=True, channel=channel)
        except ServerWatchError as e:
            await ctx.reply(error(str(e)), delete_after=30, mention_author=False)
            return
        await ctx.send(
            info(
                f"Channel-name display for `{name}` enabled on {channel.mention}. "
                "Discord rate-limits renames, so it updates roughly every 5-6 minutes."
            )
        )
        await ctx.tick()

    @sw_channelname.command(name="disable")
    async def sw_channelname_disable(self, ctx, *, name: str):
        """Stop updating the channel name."""
        try:
            await self._set_channelname_display(ctx.guild, name, enabled=False)
        except ServerWatchError as e:
            await ctx.reply(error(str(e)), delete_after=30, mention_author=False)
            return
        await ctx.tick()

    @sw_channelname.command(name="template")
    async def sw_channelname_template(self, ctx, name: str, *, template: str):
        """
        Set the channel-name template, e.g. `{current_players}/{max_players} | {map}`.

        Placeholders: {current_players} {human_players} {bot_count} {max_players} {map}
        {game} {server_name} {server_display_name} {server_address} {ping} {vac} {password}
        """
        try:
            await self._set_channelname_display(ctx.guild, name, template=template)
        except ServerWatchError as e:
            await ctx.reply(error(str(e)), delete_after=30, mention_author=False)
            return
        await ctx.tick()

    # --- intervals ----------------------------------------------------- #
    @serverwatch.group(name="set")
    async def sw_set(self, ctx):
        """Configure guild-wide timing settings."""
        pass

    @sw_set.command(name="pollinterval")
    async def sw_set_pollinterval(self, ctx, seconds: int):
        """Set how often servers are polled (status + threshold checks). Min 30s."""
        value = await self._set_interval(ctx.guild, "poll_interval", seconds)
        await ctx.send(info(f"Poll interval set to **{value}s**."))

    @sw_set.command(name="rearmgrace", aliases=["rearm"])
    async def sw_set_rearmgrace(self, ctx, seconds: int):
        """
        Set how long a server must stay BELOW a threshold before that alert re-arms.

        A rule pings once when the player count crosses its threshold, then goes silent.
        It will only ping again after the count drops back under the threshold for this
        long — which stops brief dips (like TF2 map changes) from causing repeat pings.
        """
        value = await self._set_interval(ctx.guild, "rearm_grace", seconds)
        await ctx.send(info(f"Re-arm grace set to **{value}s** (a sustained drop below a threshold re-arms its alert)."))

    @sw_set.command(name="cooldown")
    async def sw_set_cooldown(self, ctx, seconds: int):
        """
        Set the minimum time between pings of the same threshold rule.

        Even after a rule re-arms, it won't ping again until this long has passed since its
        last ping. Stops a population hovering around a threshold from spamming.
        """
        value = await self._set_interval(ctx.guild, "cooldown", seconds)
        await ctx.send(info(f"Re-ping cooldown set to **{value}s** (minimum time between pings of the same rule)."))

    @sw_set.command(name="renameinterval")
    async def sw_set_renameinterval(self, ctx, seconds: int):
        """Set the channel-rename cadence. Min 300s (Discord rate limit)."""
        value = await self._set_interval(ctx.guild, "rename_interval", seconds)
        await ctx.send(info(f"Channel-rename interval set to **{value}s**."))
