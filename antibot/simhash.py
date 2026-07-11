"""
Pure-stdlib text fingerprinting helpers for the antibot cog.

Nothing here imports discord or redbot so the functions stay unit-testable in
isolation. Two independent notions of "same message" are provided:

* ``norm_hash`` - an exact hash of the normalized text (fast set-membership).
* ``simhash64`` + ``hamming`` - a 64-bit locality-sensitive fingerprint whose
  Hamming distance grows with how different two messages are (near-duplicate
  detection, e.g. one swapped word still lands within a small distance).
"""

import hashlib
import re
from typing import Iterable, List

__all__ = ["normalize", "norm_hash", "tokenize", "simhash64", "hamming", "similarity"]

# --- normalization -------------------------------------------------------- #
# Collapse volatile per-message bits (URLs, mention/emoji IDs, markdown) so that
# two spam posts that differ only by a pinged user id or a link still match.
_URL_RE = re.compile(r"https?://\S+|www\.\S+")
_EMOJI_RE = re.compile(r"<a?:\w+:\d+>")
_MENTION_RE = re.compile(r"<@[!&]?\d+>")
_CHANNEL_RE = re.compile(r"<#\d+>")
_MD_RE = re.compile(r"[*_~`>|]+")
_WS_RE = re.compile(r"\s+")
_WORD_RE = re.compile(r"[a-z0-9]+")


def normalize(text: str) -> str:
    """Lowercase and strip the volatile/markdown bits of a message."""
    if not text:
        return ""
    t = text.lower()
    t = _URL_RE.sub(" url ", t)
    t = _EMOJI_RE.sub(" emoji ", t)
    t = _MENTION_RE.sub(" mention ", t)
    t = _CHANNEL_RE.sub(" channel ", t)
    t = _MD_RE.sub(" ", t)
    t = _WS_RE.sub(" ", t)
    return t.strip()


def norm_hash(text: str) -> str:
    """Stable SHA1 hex of the normalized text (exact-duplicate key)."""
    return hashlib.sha1(normalize(text).encode("utf-8")).hexdigest()


def tokenize(norm: str) -> List[str]:
    """
    Tokens for the SimHash: whole words plus character 3-gram shingles.

    Shingles let very short messages (few words) still produce a meaningful
    fingerprint and make the distance degrade smoothly as characters change.
    """
    tokens: List[str] = _WORD_RE.findall(norm)
    compact = "".join(norm.split())
    for i in range(len(compact) - 2):
        tokens.append(compact[i : i + 3])
    return tokens


def _token_hash(token: str) -> int:
    """Deterministic 64-bit hash of a token (blake2b is unsalted here)."""
    return int.from_bytes(hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest(), "big")


def simhash64(tokens: Iterable[str]) -> int:
    """
    64-bit SimHash: per-bit majority vote across every token's hash.

    Returns 0 for an empty token set (callers treat 0 as "no fingerprint").
    """
    tokens = list(tokens)
    if not tokens:
        return 0
    vec = [0] * 64
    for tok in tokens:
        h = _token_hash(tok)
        for i in range(64):
            if (h >> i) & 1:
                vec[i] += 1
            else:
                vec[i] -= 1
    out = 0
    for i in range(64):
        if vec[i] > 0:
            out |= 1 << i
    return out


def hamming(a: int, b: int) -> int:
    """Number of differing bits between two 64-bit fingerprints."""
    return bin(a ^ b).count("1")


def similarity(a: int, b: int) -> float:
    """Map Hamming distance to a 0.0-1.0 similarity (1.0 == identical)."""
    return 1.0 - (hamming(a, b) / 64.0)
