"""
In-memory burst detectors for the antibot cog.

Everything here is keyed by plain integer ids and driven by a caller-supplied
``now`` timestamp, so no discord/redbot import is needed and the trip logic is
unit-testable in isolation. State lives only in RAM (rebuilt on load); nothing
is persisted on the hot path.

The cross-channel detector uses the serverwatch "armed / cooldown" hysteresis so a
burst yields one action (re-arming only once the user goes quiet). The role-ping
detector uses a simpler fixed cooldown so ongoing abuse keeps getting actioned.
"""

from collections import Counter, deque
from typing import Dict, List, Optional, Tuple

try:  # package import (inside the cog)
    from .simhash import hamming
except ImportError:  # standalone import (unit tests with antibot/ on sys.path)
    from simhash import hamming

__all__ = [
    "CrossChannelDetector",
    "RolePingDetector",
    "honeypot_decision",
    "dm_new_actionable",
]


class CrossChannelDetector:
    """Detect one account posting the same/similar message across channels."""

    def __init__(self, maxlen: int = 64):
        # (guild_id, user_id) -> deque[(chan_id, message_id, nhash, simhash, ts)]
        self._events: Dict[Tuple[int, int], deque] = {}
        # (guild_id, user_id) -> {"armed": bool, "last_fire": float}
        self._state: Dict[Tuple[int, int], Dict] = {}
        self._maxlen = maxlen

    def record(
        self,
        guild_id: int,
        user_id: int,
        chan_id: int,
        message_id: int,
        nhash: str,
        simhash: int,
        now: float,
        *,
        channels: int,
        window: float,
        simhash_distance: int,
        cooldown: float,
    ) -> Tuple[bool, Optional[Dict]]:
        key = (guild_id, user_id)
        dq = self._events.setdefault(key, deque(maxlen=self._maxlen))
        dq.append((chan_id, message_id, nhash, simhash, now))
        recent = [e for e in dq if now - e[4] <= window]

        cluster = self._trip_cluster(recent, channels, simhash_distance)
        if cluster is None:
            self._maybe_rearm(key, now, cooldown)
            return False, None

        st = self._state.setdefault(key, {"armed": True, "last_fire": float("-inf")})
        if st["armed"] and (now - st["last_fire"]) >= cooldown:
            st["armed"] = False
            st["last_fire"] = now
            return True, {"messages": [(e[0], e[1]) for e in cluster]}
        return False, None

    def _trip_cluster(self, events: List, channels: int, dist: int) -> Optional[List]:
        for cluster in self._cluster(events, dist):
            if len({e[0] for e in cluster}) >= channels:
                return cluster
        return None

    @staticmethod
    def _cluster(events: List, dist: int) -> List[List]:
        """Greedy grouping of "same message" events (exact nhash or near sh)."""
        clusters: List[List] = []
        for e in events:
            for c in clusters:
                rep = c[0]
                # Exact normalized hash, or near-dup SimHash when both fingerprints
                # are non-zero. A 0 simhash is the caller's "no fuzzy" sentinel (short
                # messages), so unrelated short posts don't cluster on hamming(0,0)==0.
                if e[2] == rep[2] or (e[3] and rep[3] and hamming(e[3], rep[3]) <= dist):
                    c.append(e)
                    break
            else:
                clusters.append([e])
        return clusters

    def _maybe_rearm(self, key: Tuple[int, int], now: float, cooldown: float) -> None:
        st = self._state.get(key)
        if st and not st["armed"] and (now - st["last_fire"]) >= cooldown:
            st["armed"] = True

    def sweep(self, now: float, max_idle: float) -> None:
        """Drop idle per-user state to bound memory (call from a slow loop)."""
        for key in list(self._events):
            dq = self._events[key]
            if not dq or now - dq[-1][4] > max_idle:
                self._events.pop(key, None)
                self._state.pop(key, None)


class RolePingDetector:
    """Detect one account pinging a watched role repeatedly across channels."""

    def __init__(self, maxlen: int = 128):
        # (guild_id, user_id) -> deque[(role_id, chan_id, message_id, ts)]
        self._events: Dict[Tuple[int, int], deque] = {}
        # (guild_id, user_id, role_id) -> {"last_fire": float}  (pure cooldown gate)
        self._state: Dict[Tuple[int, int, int], Dict] = {}
        self._maxlen = maxlen

    def record(
        self,
        guild_id: int,
        user_id: int,
        role_hits: List[Tuple[int, int, int]],
        now: float,
        *,
        threshold: int,
        window: float,
        cooldown: float,
    ) -> Tuple[bool, Optional[int], Optional[Dict]]:
        """``role_hits``: (role_id, chan_id, message_id) per raw ping occurrence."""
        key = (guild_id, user_id)
        dq = self._events.setdefault(key, deque(maxlen=self._maxlen))
        for rid, cid, mid in role_hits:
            dq.append((rid, cid, mid, now))
        recent = [e for e in dq if now - e[3] <= window]

        counts = Counter(e[0] for e in recent)
        for rid, cnt in counts.items():
            if cnt >= threshold:
                skey = (guild_id, user_id, rid)
                st = self._state.setdefault(skey, {"last_fire": float("-inf")})
                # Pure cooldown gate (no armed/hysteresis): fire, then again every
                # `cooldown`. If the user can still ping (lockdown failed / has mention
                # perms) they keep getting actioned instead of going silent.
                if (now - st["last_fire"]) >= cooldown:
                    st["last_fire"] = now
                    msgs = [(e[1], e[2]) for e in recent if e[0] == rid]
                    return True, rid, {"messages": msgs}
        return False, None, None

    def sweep(self, now: float, max_idle: float) -> None:
        for key in list(self._events):
            dq = self._events[key]
            if not dq or now - dq[-1][3] > max_idle:
                self._events.pop(key, None)
                for skey in [k for k in self._state if k[:2] == key]:
                    self._state.pop(skey, None)


def honeypot_decision(*, has_exempt_role: bool, joined_seconds: Optional[float], exempt_after: float) -> str:
    """
    Resolve what to do when a non-immune member posts in a honeypot channel.
    Immune members are handled by the caller before this is reached.

    Returns:
      * "report": exempt but noteworthy (exempt role, established by time in server,
        or missing join data). Notify mods if report_exempt is on, never punish.
        Missing ``joined_seconds`` downgrades here so we never act on no data.
      * "action": a non-exempt (typically new) member, run the configured action.
    """
    if has_exempt_role:
        return "report"
    if joined_seconds is None:
        return "report"
    if joined_seconds >= exempt_after:
        return "report"
    return "action"


def dm_new_actionable(
    account_age: float,
    member_age: Optional[float],
    acc_window: float,
    mem_window: float,
) -> bool:
    """Should a member who DM'd the bot be actioned by the unusual-DM detector?

    "Either window" gate: actionable if the account is younger than ``acc_window``
    OR they joined the server more recently than ``mem_window``. Unlike the roleping
    gate, both windows being 0 means the detector never fires (a DM to the bot is not
    on its own grounds to act on every member). Missing ``member_age`` (no join data)
    only disables the member-age half.
    """
    if acc_window <= 0 and mem_window <= 0:
        return False
    if acc_window > 0 and account_age < acc_window:
        return True
    if mem_window > 0 and member_age is not None and member_age < mem_window:
        return True
    return False
