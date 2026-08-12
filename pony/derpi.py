"""
Derpibooru API access: challenge solving and backoff.

Derpibooru answers 501 with an html interstitial while it is shedding load, and 500
with an empty body once an IP is blocked. The interstitial is its own, not
Cloudflare's: a form with two hidden fields and a submit button, no javascript. The
clearance it grants is keyed to our IP and sets no cookie, so every guild shares it.

Requests sent during a block restart its 15 minute timer, so a fetch spends at most
three requests (GET, POST /challenge, GET) and solves at most once. A retry that is
challenged again gives up rather than solving in a loop.

No discord or redbot imports here; the gate and the parser are tested standalone.
"""

import asyncio
import html
import random
import re
import ssl
import time
from collections import deque
from typing import Dict, Optional, Tuple

import aiohttp

__all__ = [
    "CHALLENGE_URL",
    "ChallengeGate",
    "DerpiBusy",
    "DerpiCold",
    "DerpiError",
    "fetch_json",
    "make_ssl_context",
    "parse_challenge",
]

CHALLENGE_URL = "https://derpibooru.org/challenge"

# Derpibooru wants 5s after a 501 before the endpoint is hit again. Submitting
# /challenge is the interstitial's own form and doesn't count; the retry does.
SOLVE_RETRY_WAIT = 5.0

# Don't come back the instant a block expires.
_BLOCK_JITTER = 60.0

_INPUT_RE = re.compile(r"<input\b[^>]*>", re.I)
_ATTR_RE = re.compile(r'([\w-]+)\s*=\s*"([^"]*)"')


def make_ssl_context() -> ssl.SSLContext:
    """TLS settings that get past the Cloudflare layer in front of Derpibooru.

    Cloudflare fingerprints the ClientHello (JA3/JA4). aiohttp's default omits the
    ALPN and post_handshake_auth extensions and draws a 403 whatever the User-Agent;
    python's own http.client sends both and passes.
    """
    ctx = ssl.create_default_context()
    ctx.set_alpn_protocols(["http/1.1"])
    ctx.post_handshake_auth = True
    return ctx


class DerpiError(Exception):
    """Derpibooru could not be reached or answered with something unusable."""


class DerpiBusy(DerpiError):
    """Challenged or briefly unavailable. Retrying shortly is reasonable."""


class DerpiCold(DerpiError):
    """Backing off; no request may be sent."""

    def __init__(self, remaining: float):
        super().__init__("backing off for {:.0f}s".format(remaining))
        self.remaining = remaining


def parse_challenge(body: str) -> Optional[Dict[str, str]]:
    """Pull the hidden fields out of the interstitial form.

    Returns None when the page is not the form we know, so the caller backs off
    instead of POSTing a guess at /challenge.
    """
    fields: Dict[str, str] = {}
    for tag in _INPUT_RE.findall(body):
        # Attribute names are case insensitive in html; values are not.
        attrs = {k.lower(): v for k, v in _ATTR_RE.findall(tag)}
        name = attrs.get("name")
        if name in ("_key", "referer"):
            fields[name] = html.unescape(attrs.get("value", ""))

    if not fields.get("_key"):
        return None
    # Only steers the 302, which we don't follow, so a missing one is harmless.
    fields.setdefault("referer", "/")
    return fields


class ChallengeGate:
    """Backoff state for Derpibooru, shared by the whole cog.

    A 501 is routine, since the site challenges on its own load rather than on
    anything we did, so it is solved and counted and only a run of them trips the
    breaker. A 500 means we are already blocked and goes cold at once.

    Tuning is passed per call rather than stored, so a [p]ponyset change lands on
    the next request.
    """

    def __init__(self, maxlen: int = 64):
        self._challenges: deque = deque(maxlen=maxlen)
        self._blocked_until: float = 0.0

    @property
    def blocked_until(self) -> float:
        return self._blocked_until

    def restore(self, blocked_until: float) -> None:
        """Reload a cold period that outlived a cog reload."""
        self._blocked_until = max(self._blocked_until, blocked_until)

    def cold_remaining(self, now: float) -> float:
        return max(0.0, self._blocked_until - now)

    def challenges_in_window(self, now: float, window: float) -> int:
        self._prune(now, window)
        return len(self._challenges)

    def record_challenge(self, now: float, *, threshold: int, window: float, cooldown: float) -> bool:
        """Count one challenged invocation. True if that tripped the breaker.

        Call at most once per invocation; counting the initial 501 and the one after
        a failed solve would halve the effective threshold.
        """
        self._challenges.append(now)
        self._prune(now, window)
        if len(self._challenges) > threshold:
            self._blocked_until = max(self._blocked_until, now + cooldown)
            return True
        return False

    def record_block(self, now: float, *, cooldown: float) -> None:
        """A 500: we are hard-blocked. Only ever lengthens the cold period."""
        self._blocked_until = max(self._blocked_until, now + cooldown + random.uniform(0, _BLOCK_JITTER))

    def clear(self) -> None:
        self._challenges.clear()
        self._blocked_until = 0.0

    def _prune(self, now: float, window: float) -> None:
        while self._challenges and now - self._challenges[0] > window:
            self._challenges.popleft()


def _breaker(settings: Dict) -> Dict:
    return {
        "threshold": settings["threshold"],
        "window": settings["window"],
        "cooldown": settings["cooldown"],
    }


async def _get(session: aiohttp.ClientSession, url: str, gate: ChallengeGate, settings: Dict) -> Tuple[int, object]:
    """One GET. Returns (200, decoded json) or (501, challenge html)."""
    try:
        async with session.get(url) as r:
            if r.status == 200:
                try:
                    return 200, await r.json()
                except (aiohttp.ContentTypeError, ValueError) as e:
                    raise DerpiBusy("derpibooru answered 200 with a non-json body") from e
            if r.status == 500:
                gate.record_block(time.time(), cooldown=settings["block_cooldown"])
                raise DerpiCold(gate.cold_remaining(time.time()))
            if r.status == 501:
                return 501, await r.text()
            raise DerpiError("derpibooru returned HTTP {}".format(r.status))
    except aiohttp.ClientError as e:
        raise DerpiError("request failed: {}".format(e)) from e
    except asyncio.TimeoutError as e:
        raise DerpiError("request timed out") from e


async def fetch_json(session: aiohttp.ClientSession, url: str, gate: ChallengeGate, settings: Dict) -> Dict:
    """Fetch a Derpibooru API url, solving the interstitial once if we hit it.

    Callers hold the cog lock, which is what makes the three-request ceiling global
    rather than per invocation.
    """
    remaining = gate.cold_remaining(time.time())
    if remaining > 0:
        raise DerpiCold(remaining)

    status, payload = await _get(session, url, gate, settings)
    if status == 200:
        return payload

    tripped = gate.record_challenge(time.time(), **_breaker(settings))
    if not settings.get("autosolve", True):
        raise DerpiBusy("challenged, and autosolve is off")
    if tripped:
        raise DerpiCold(gate.cold_remaining(time.time()))

    fields = parse_challenge(payload)
    if fields is None:
        raise DerpiBusy("derpibooru served a challenge page we don't recognise")

    try:
        # The 302 Location comes back with a literal "&amp;", so following it would
        # request a parameter named "amp;per_page".
        async with session.post(CHALLENGE_URL, data=fields, allow_redirects=False) as r:
            if r.status != 302:
                raise DerpiBusy("challenge submission returned HTTP {}".format(r.status))
    except aiohttp.ClientError as e:
        raise DerpiError("challenge submission failed: {}".format(e)) from e
    except asyncio.TimeoutError as e:
        raise DerpiError("challenge submission timed out") from e

    await asyncio.sleep(SOLVE_RETRY_WAIT)

    status, payload = await _get(session, url, gate, settings)
    if status == 200:
        return payload
    raise DerpiBusy("derpibooru is still challenging after a solve")
