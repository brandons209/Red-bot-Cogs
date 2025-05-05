from typing import List, Dict, Optional, Any
from io import BytesIO
from datetime import datetime
import re
import html
import base64, mimetypes

import discord
from jinja2 import Template

# Inline Jinja2 template that mimics Discord’s message layout
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>{{ channel.name }} — {{ guild.name }}</title>
  <style>
    a, a:link, a:visited {
        color: #00B0F4;           /* brighter link color */
        text-decoration: underline;
    }
    a:hover {
        color: #0096cf;
    }
    body { background: #2F3136; color: #DCDDDE; font-family: "Helvetica Neue", Helvetica, Arial, sans-serif; padding: 20px; }
    .message { display: flex; margin-bottom: 15px; }
    .avatar { width: 40px; height: 40px; border-radius: 50%; margin-right: 10px; }
    .content { max-width: 800px; }
    .header { font-size: 0.9em; color: #8E9297; }
    .username { color: #FFFFFF; font-weight: 500; margin-right: 5px; }
    .timestamp { font-size: 0.8em; }
    .edited { font-size: 0.75em; color: #B9BBBE; margin-left: 8px; }
    .attachments img { max-width: 200px; border-radius: 5px; margin-top: 5px; }
    .attachments { 
        font-size: 0.73em;
        margin-top: 8px;
        padding-top: 4px;
        border-top: 1px solid #4F545C; /* thin, solid separator */ 
    }
    .reply { border-left: 2px solid #4F545C; padding-left: 8px; margin-bottom: 5px; color: #B9BBBE; font-style: italic; font-size: 0.8em; }
    .text {
      white-space: pre-wrap;
      word-wrap: break-word;
    }
    .channel-name {
        color: #aaa;
        font-size: 0.85em;
        margin-left: 6px;
    }
    .edited {
        font-size: 0.8em;
        color: #B9BBBE;
        margin-left: 4px;
    }
    .deleted-info {
        font-size: 0.85em;
        color: #B9BBBE;  /* Light gray color */
        margin-top: 5px;
    }
    .deleted-text {
        font-style: italic;
    }
    .message.highlight {
        animation: highlightFlash 2s ease-out;
        border-left: 4px solid #faa61a;
        background-color: rgba(255, 166, 26, 0.1);
    }

    @keyframes highlightFlash {
        0%   { background-color: rgba(255, 166, 26, 0.4); }
        100% { background-color: transparent; }
    }
  </style>
</head>
<body>
  <h2># {{ channel.name }}</h2>
  <div style="margin-bottom: 20px;">
        <label style="font-size: 14px; color: #ccc;">
            <input type="checkbox" id="toggleClockStyle" checked>
            Use 24-hour clock
        </label>
    </div>
  {% for msg in messages %}
    <div id="msg_{{ msg.id }}" class="message">
      <img class="avatar" src="{{ msg.avatar_url }}" alt="avatar">
      <div class="content">
        <div class="header">
          <span class="username">{{ msg.username }}</span>
          {% if msg.channel_name %}
            <span class="channel-name">in #{{ msg.channel_name }}</span>
        {% endif %}
          <time class="timestamp" data-isotime="{{ msg.timestamp_iso }}">
                {{ msg.timestamp }}
          </time>
          {% if msg.edited_timestamp %}
            <span class="edited">edited</span>
                <time class="edited" data-isotime="{{ msg.edited_timestamp_iso }}">
                {{ msg.edited_timestamp }}
            </time>
          {% endif %}
        </div>
        {% if msg.reply_to %}
            <div class="reply">
                <a href="#msg_{{ msg.reply_to.id }}">
                ↪ In reply to <strong>{{ msg.reply_to.username }}</strong>: {{ msg.reply_to.content }}
                </a>
            </div>
        {% endif %}
        {% if msg.deleted_by_username %}
            <div class="deleted-info">
                <span class="deleted-text">Message deleted by <strong>{{ msg.deleted_by_username }}</strong></span>
            </div>
        {% endif %}
        <div class="text">{{ msg.content }}</div>
        {% if msg.attachments %}
            <div class="attachments">
                    <strong>Attachments:</strong></br>
                    {% for a in msg.attachments %}
                        {% if a.type == "jump" %}
                            <a href="{{ a.jump }}">{{ a.label }}</a></br>
                        {% elif a.type == "embed" %}
                            <img src="data:{{ a.mime }};base64,{{ a.data }}" alt="attachment"/></br>
                        {% else %}
                            <span class="deleted-info">[deleted attachment]<a href="{{ a.url }}">{{ a.url }}</a></span></br>
                        {% endif %}
                    {% endfor %}
            </div>
         {% endif %}
      </div>
    </div>
  {% endfor %}
    <script>
        function formatTimestamp(dt, use24h) {
        return dt.toLocaleString(undefined, {
            year: "numeric",
            month: "short",
            day: "numeric",
            hour: "2-digit",
            minute: "2-digit",
            second: "2-digit",
            hour12: !use24h,
            timeZoneName: "short"
        });
        }

        function updateAllTimestamps(use24h) {
        document.querySelectorAll("time[data-isotime]").forEach(el => {
            let iso = el.getAttribute("data-isotime");
            // Force interpretation as UTC
            if (!iso.endsWith('Z')) iso += 'Z';
            const dt = new Date(iso);
            el.textContent = formatTimestamp(dt, use24h);
        });
        }

        document.addEventListener("DOMContentLoaded", () => {
            const checkbox = document.getElementById("toggleClockStyle");
            updateAllTimestamps(checkbox?.checked ?? true);

            checkbox?.addEventListener("change", () => {
                updateAllTimestamps(checkbox.checked);
            });
        });

        function applyHighlight() {
            // clear any existing
            document.querySelectorAll('.message.highlight').forEach(el => {
                el.classList.remove('highlight');
            });

            // get the current hash, e.g. "#msg_12345"
            const hash = window.location.hash;
            if (!hash) return;

            // find that element and highlight
            const target = document.querySelector(hash);
            if (target && target.classList.contains('message')) {
            target.classList.add('highlight');
            // scroll into view smoothly (optional)
            target.scrollIntoView({ behavior: 'smooth', block: 'center' });
            }
        }

        // run on initial load
        window.addEventListener('DOMContentLoaded', applyHighlight);

        // run whenever the hash changes (e.g. user clicks a reply link)
        window.addEventListener('hashchange', applyHighlight);
    </script>
</body>
</html>
"""
FORMAT_PATTERNS = [
    (r"```(.+?)```", r"<pre>\1</pre>"),
    (r"\*\*(.+?)\*\*", r"<strong>\1</strong>"),
    (r"__(.+?)__", r"<u>\1</u>"),
    (r"~~(.+?)~~", r"<del>\1</del>"),
    (r"\*(.+?)\*", r"<em>\1</em>"),
    (r"`(.+?)`", r"<code>\1</code>"),
]


class ChatHTMLExporter:
    _USER_MENTION_RE = re.compile(r"<@!?(?P<id>[0-9]+)>")
    _ROLE_MENTION_RE = re.compile(r"<@&(?P<id>[0-9]+)>")
    _CHANNEL_MENTION_RE = re.compile(r"<#(?P<id>[0-9]+)>")
    _EMOJI_RE = re.compile(r"<a?:(?P<name>[^:]+):(?P<id>[0-9]+)>")
    _TS_RE = re.compile(r"<t:(?P<ts>\d+)(?::[tTdDfR])?>")

    _LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
    _URL_RE = re.compile(r"(?P<url>https?://[^\s<]+)")
    _LIST_BLOCK_RE = re.compile(r"(?:^(?:[\-\+\*]\s+.+\n?)+)", flags=re.MULTILINE)
    _ATTACHMENT_CHANNEL_ID_RE = re.compile(r"^https?://cdn\.discordapp\.com/attachments/(?P<channel_id>\d+)/\d+/[^?]+")

    def __init__(self, bot: discord.Client, guild: discord.Guild):
        self.bot = bot
        self.guild = guild
        self._messages: List[Dict] = []
        self._attachments: Dict[int, List[Dict[Any, Any]]] = {}
        self._by_message: Dict[int, Dict] = {}

    # 2) Replace callbacks
    def _replace_user(self, match):
        uid = int(match.group("id"))
        member = self.guild.get_member(uid) or None
        name = member.display_name if member else f"Unknown User#{uid}"
        return f"@{name}"

    def _replace_role(self, match):
        rid = int(match.group("id"))
        role = self.guild.get_role(rid)
        return f"@{role.name}" if role else match.group(0)

    def _replace_channel(self, match):
        cid = int(match.group("id"))
        chan = self.bot.get_channel(cid) or self.guild.get_channel_or_thread(cid)
        return f"#{chan.name}" if chan and not isinstance(chan, discord.abc.PrivateChannel) else match.group(0)

    def _replace_emoji(self, m):
        eid = int(m.group("id"))
        name = m.group("name")
        # attempt to get a discord.Emoji object
        emoji = self.bot.get_emoji(eid)
        if emoji:
            # hyperlink :name: to its URL
            return f'<a href="{emoji.url}" target="_blank">:{name}:</a>'
        else:
            return f":{name}:"

    def _replace_ts(self, match):
        ts = int(match.group("ts"))
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S %Z")

    def _replace_links(self, text: str) -> str:
        return self._LINK_RE.sub(r'<a href="\2" target="_blank">\1</a>', text)

    def _replace_autolinks(self, text: str) -> str:
        # Convert bare URLs into clickable links
        return self._URL_RE.sub(r'<a href="\g<url>" target="_blank">\g<url></a>', text)

    def _replace_headers(self, text: str) -> str:
        # from H6 down to H1
        for level in range(6, 0, -1):
            pattern = re.compile(rf"^(?P<prefix>{'#' * level})\s*(?P<body>.+)$", flags=re.MULTILINE)
            text = pattern.sub(rf"<h{level}>\g<body></h{level}>", text)
        return text

    def _replace_lists(self, text: str) -> str:
        def _blk_repl(m):
            lines = m.group(0).strip().splitlines()
            items = "".join(f"<li>{html.escape(line[2:].strip())}</li>" for line in lines)
            return f"<ul>{items}</ul>\n"

        return self._LIST_BLOCK_RE.sub(_blk_repl, text)

    def _apply_markdown(self, text: str) -> str:
        for pattern, repl in FORMAT_PATTERNS:
            text = re.sub(pattern, repl, text, flags=re.DOTALL)
        return text

    def _preprocess_content(self, raw: str) -> str:
        if not raw:
            return ""

        # b) timestamps
        txt = self._TS_RE.sub(self._replace_ts, raw)
        # c) mentions
        txt = self._USER_MENTION_RE.sub(self._replace_user, txt)
        txt = self._ROLE_MENTION_RE.sub(self._replace_role, txt)
        txt = self._replace_headers(txt)
        txt = self._CHANNEL_MENTION_RE.sub(self._replace_channel, txt)
        txt = self._EMOJI_RE.sub(self._replace_emoji, txt)
        # d) markdown formatting
        txt = self._replace_links(txt)
        txt = self._replace_autolinks(txt)
        txt = self._replace_lists(txt)
        txt = self._apply_markdown(txt)
        return txt

    def ingest_messages(self, rows: List[Dict]):
        """rows: list of dicts with keys matching your messages table"""
        self._messages = sorted(rows, key=lambda r: r["datetime"])
        self._by_message = {r["message_id"]: r for r in self._messages}

    def ingest_attachments(self, rows: List[Dict]):
        """rows: list of dicts with 'message_id' and 'url'"""
        for a in rows:
            self._attachments.setdefault(a["message_id"], []).append(a)

    async def export_channel(self, channel_id: int) -> List[BytesIO]:
        """Fetches channel & members, renders HTML, and writes to output_file"""
        # 1) Resolve channel
        channel = self.bot.get_channel(channel_id) or self.guild.get_channel_or_thread(channel_id)
        # 2) Prepare per‑message rendering context
        rendered = []
        for row in self._messages:
            if row["channel_id"] != channel_id:
                continue
            # author
            member = self.guild.get_member(row["author_id"])
            if member is None:
                try:
                    member = await self.guild.fetch_member(row["author_id"])
                except discord.NotFound:
                    member = None

            username = member.display_name if member else f"Unknown#{row['author_id']}"
            avatar_url = (
                member.avatar.url if (member and member.avatar) else self.guild.icon.url if self.guild.icon else ""
            )

            # Determine if the message was deleted and get the deleted by username
            deleted_by_username = None
            if row.get("deleted_by_id"):
                deleted_member = self.guild.get_member(row["deleted_by_id"])
                if deleted_member is None:
                    try:
                        deleted_member = await self.guild.fetch_member(row["deleted_by_id"])
                    except discord.NotFound:
                        deleted_member = None
                deleted_by_username = (
                    deleted_member.display_name if deleted_member else f"Unknown#{row['deleted_by_id']}"
                )

            # content selection
            raw = row.get("edited_content") or row.get("content") or ""
            content = self._preprocess_content(raw)
            ts = row["datetime"].strftime("%Y-%m-%d %H:%M:%S %Z")
            edited_ts = row["edited_datetime"].strftime("%Y-%m-%d %H:%M:%S %Z") if row.get("edited_datetime") else None

            # reply context
            reply_to = None
            ref = row.get("reference_id")
            if ref and ref in self._by_message:
                parent = self._by_message[ref]
                reply_author = self.guild.get_member(parent["author_id"])
                reply_username = reply_author.display_name if reply_author else f"Unknown#{parent['author_id']}"
                reply_content = parent.get("edited_content") or parent.get("content") or ""
                reply_to = {"id": ref, "username": reply_username, "content": reply_content}

            # attachments
            attachments = []
            for i, a in enumerate(self._attachments.get(row["message_id"], [])):
                # If logged in a channel, deep-link that message
                if a["attachment_message_id"]:
                    new_channel_id = re.match(self._ATTACHMENT_CHANNEL_ID_RE, a["url"])
                    ch_id = new_channel_id.group("channel_id") if new_channel_id else channel.id
                    jump = f"https://discord.com/channels/{self.guild.id}/{ch_id}/{a['attachment_message_id']}"
                    attachments.append({"type": "jump", "jump": jump, "label": f"{i+1}. View in Discord"})
                # because of file size limit issues, we aren't supporting this for now. Need to figure out the best way to handle this (maybe upload to a temporary channel?)
                # elif a["filepath"]:
                #    try:
                #        data = base64.b64encode(open(a["filepath"], "rb").read()).decode("ascii")
                #        mime = mimetypes.guess_type(a["filepath"])[0] or "application/octet-stream"
                #        attachments.append({"type": "embed", "data": data, "mime": mime})
                #    except FileNotFoundError:  # fallback to attachment url
                #        if not row.get("deleted_by_id"):
                #            jump = f"https://discord.com/channels/{self.guild.id}/{channel_id}/{a['message_id']}"
                #            attachments.append({"type": "jump", "jump": jump, "label": f"{i+1}. View in Discord"})
                #        # 4) Deleted fallback
                #        else:
                #            attachments.append({"type": "deleted", "url": a["url"]})
                # 3) Else if original message exists, deep-link that
                elif not row.get("deleted_by_id"):
                    jump = f"https://discord.com/channels/{self.guild.id}/{channel_id}/{a['message_id']}"
                    attachments.append({"type": "jump", "jump": jump, "label": f"{i+1}. View in Discord"})
                # 4) Deleted fallback
                else:
                    attachments.append({"type": "deleted", "url": a["url"]})

            rendered.append(
                {
                    "id": row["message_id"],
                    "username": username,
                    "avatar_url": avatar_url,
                    "timestamp": ts,
                    "timestamp_iso": row["datetime"].isoformat(),
                    "edited_timestamp": edited_ts,
                    "edited_timestamp_iso": row["edited_datetime"].isoformat() if row.get("edited_datetime") else None,
                    "content": content,
                    "reply_to": reply_to,
                    "attachments": attachments,
                    "deleted_by_username": deleted_by_username,
                }
            )

        tpl = Template(HTML_TEMPLATE)

        # check file size, and if its too large split into smaller chunks
        limit = self.guild.filesize_limit  # in bytes

        def recursive_chunk(rendered_chunk) -> List[bytes]:
            chunk = tpl.render(guild=self.guild, channel=channel, messages=rendered_chunk).encode()
            if len(chunk) < limit or len(rendered_chunk) <= 1:
                return [chunk]
            mid = int(len(rendered_chunk) / 2)
            return recursive_chunk(rendered_chunk[:mid]) + recursive_chunk(rendered_chunk[mid:])

        chunks = recursive_chunk(rendered)
        return [BytesIO(c) for c in chunks]

    async def export_user(
        self,
        user_id: int,
        output_file: BytesIO,
        channels: Optional[List[int]] = None,
        include_dm_name: bool = False,
    ):
        """
        Export all messages from a specific user across one or more channels.

        Args:
            user_id (int): The user ID to filter messages by.
            output_file (Path): Output HTML file path.
            channels (Optional[List[int]]): Channel IDs to restrict search to.
            include_dm_name (bool): Show channel names next to messages.
        """
        target_messages = [
            m for m in self._messages if m["author_id"] == user_id and (channels is None or m["channel_id"] in channels)
        ]
        target_messages.sort(key=lambda m: m["datetime"])
        self._by_message = {m["message_id"]: m for m in target_messages}

        rendered = []

        member = self.guild.get_member(user_id)
        if not member:
            try:
                member = await self.guild.fetch_member(user_id)
            except discord.NotFound:
                member = None

        username = member.display_name if member else f"Unknown#{user_id}"
        avatar_url = member.avatar.url if member and member.avatar else (self.guild.icon.url if self.guild.icon else "")

        for row in target_messages:
            channel = (
                self.bot.get_channel(row["channel_id"])
                or self.guild.get_channel_or_thread(row["channel_id"])
                or await self.bot.fetch_channel(row["channel_id"])
            )

            # Determine if the message was deleted and get the deleted by username
            deleted_by_username = None
            if row.get("deleted_by_id"):
                deleted_member = self.guild.get_member(row["deleted_by_id"])
                if deleted_member is None:
                    try:
                        deleted_member = await self.guild.fetch_member(row["deleted_by_id"])
                    except discord.NotFound:
                        deleted_member = None
                deleted_by_username = (
                    deleted_member.display_name if deleted_member else f"Unknown#{row['deleted_by_id']}"
                )

            raw = row.get("edited_content") or row.get("content") or ""
            content = self._preprocess_content(raw)

            ts = row["datetime"].strftime("%Y-%m-%d %H:%M:%S")
            ts_iso = row["datetime"].isoformat()
            edited_ts = row["edited_datetime"].strftime("%Y-%m-%d %H:%M:%S") if row.get("edited_datetime") else None
            edited_ts_iso = row["edited_datetime"].isoformat() if row.get("edited_datetime") else None

            reply_to = None
            ref = row.get("reference_id")
            if ref and ref in self._by_message:
                parent = self._by_message[ref]
                reply_author = self.guild.get_member(parent["author_id"])
                reply_username = reply_author.display_name if reply_author else f"Unknown#{parent['author_id']}"
                reply_content = parent.get("edited_content") or parent.get("content") or ""
                reply_to = {"id": ref, "username": reply_username, "content": reply_content}

            attachments = []
            for i, a in enumerate(self._attachments.get(row["message_id"], [])):
                # If logged in a channel, deep-link that message
                if a["attachment_message_id"]:
                    new_channel_id = re.match(self._ATTACHMENT_CHANNEL_ID_RE, a["url"])
                    ch_id = new_channel_id.group("channel_id") if new_channel_id else channel.id
                    jump = f"https://discord.com/channels/{self.guild.id}/{ch_id}/{a['attachment_message_id']}"
                    attachments.append({"type": "jump", "jump": jump, "label": f"{i+1}. View in Discord"})
                # because of file size limit issues, we aren't supporting this for now. Need to figure out the best way to handle this (maybe upload to a temporary channel?)
                # elif a["filepath"]:
                #    try:
                #        data = base64.b64encode(open(a["filepath"], "rb").read()).decode("ascii")
                #        mime = mimetypes.guess_type(a["filepath"])[0] or "application/octet-stream"
                #        attachments.append({"type": "embed", "data": data, "mime": mime})
                #    except FileNotFoundError:
                #        if not row.get("deleted_by_id"):
                #            jump = f"https://discord.com/channels/{self.guild.id}/{channel.id}/{a['message_id']}"
                #            attachments.append({"type": "jump", "jump": jump, "label": f"{i+1}. View in Discord"})
                #        else:
                #            attachments.append({"type": "deleted", "url": a["url"]})
                # 3) Else if original message exists, deep-link that
                elif not row.get("deleted_by_id"):
                    jump = f"https://discord.com/channels/{self.guild.id}/{channel.id}/{a['message_id']}"
                    attachments.append({"type": "jump", "jump": jump, "label": f"{i+1}. View in Discord"})
                # 4) Deleted fallback
                else:
                    attachments.append({"type": "deleted", "url": a["url"]})

            rendered.append(
                {
                    "id": row["message_id"],
                    "username": username,
                    "avatar_url": avatar_url,
                    "timestamp": ts,
                    "timestamp_iso": ts_iso,
                    "edited_timestamp": edited_ts,
                    "edited_timestamp_iso": edited_ts_iso,
                    "content": content,
                    "reply_to": reply_to,
                    "attachments": attachments,
                    "channel_name": (
                        channel.name
                        if include_dm_name and not isinstance(channel, discord.abc.PrivateChannel)
                        else None
                    ),
                    "deleted_by_username": deleted_by_username,
                }
            )

        # Use the same Jinja template, but pass an artificial "channel"
        fake_channel = type("FakeChannel", (), {"name": f"Messages from {username}"})

        tpl = Template(HTML_TEMPLATE)

        # check file size, and if its too large split into smaller chunks
        limit = self.guild.filesize_limit  # in bytes

        def recursive_chunk(rendered_chunk) -> List[bytes]:
            chunk = tpl.render(guild=self.guild, channel=fake_channel, messages=rendered_chunk).encode()
            if len(chunk) < limit or len(rendered_chunk) <= 1:
                return [chunk]
            mid = int(len(rendered_chunk) / 2)
            return recursive_chunk(rendered_chunk[:mid]) + recursive_chunk(rendered_chunk[mid:])

        chunks = recursive_chunk(rendered)
        return [BytesIO(c) for c in chunks]
