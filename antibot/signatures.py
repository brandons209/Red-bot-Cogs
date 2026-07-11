"""
Bot "signature" model for the antibot cog.

A signature is a small, matchable fingerprint of a confirmed bot: strong signals
(shared avatar, identical message, role set) plus a weak corroborating one
(account-age band). ``compare`` scores a live candidate against one signature;
``compare_store`` finds the best match across the guild's saved signatures.

Matching is **weighted scoring with a strong-signal override**: an exact avatar
or exact normalized-message hash floors confidence high on its own, while weak
signals can only corroborate and never trip alone.

``compare``/``compare_store``/``age_band`` are pure (dict in, tuple out) so they
unit-test without discord. The ``extract_*``/``build_signature`` helpers read
attributes off a member via duck typing and never import discord either.
"""

import time
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

try:  # package import (inside the cog)
    from .simhash import hamming, norm_hash, normalize, simhash64, tokenize
except ImportError:  # standalone import (unit tests with antibot/ on sys.path)
    from simhash import hamming, norm_hash, normalize, simhash64, tokenize

__all__ = [
    "DEFAULT_WEIGHTS",
    "age_band",
    "extract_member_features",
    "extract_message_features",
    "extract_text_features",
    "build_signature",
    "build_manual",
    "fingerprint_text",
    "compare",
    "compare_store",
]

# Username fuzzy ratios below this are treated as no-signal (a weak partial name
# overlap should not, on its own, push confidence into an action tier).
_USERNAME_FUZZY_FLOOR = 0.6

# Default per-signal weights; the cog overrides these from guild config.
DEFAULT_WEIGHTS: Dict[str, float] = {
    "msg_simhash": 3.0,
    "role_jaccard": 2.0,
    "username_fuzzy": 1.5,
    "age_band": 0.5,
}

_STRONG_SUBS = ("msg_simhash", "role_jaccard", "username_fuzzy")


def age_band(seconds: Optional[float]) -> Optional[str]:
    """Bucket an account age (seconds) into a coarse band, or None if unknown."""
    if seconds is None:
        return None
    if seconds < 3600:
        return "<1h"
    if seconds < 86400:
        return "<1d"
    if seconds < 604800:
        return "<7d"
    if seconds < 2592000:
        return "<30d"
    return ">=30d"


def _account_age_seconds(member) -> Optional[float]:
    created = getattr(member, "created_at", None)
    if created is None:
        return None
    return (datetime.now(timezone.utc) - created).total_seconds()


def _member_role_ids(member, recent_roles=None) -> List[int]:
    ids = set(recent_roles or [])
    for role in getattr(member, "roles", []) or []:
        # Skip @everyone (is_default) - it carries no signal.
        if getattr(role, "is_default", None) and role.is_default():
            continue
        ids.add(role.id)
    return sorted(ids)


def _avatar_key(member) -> Optional[str]:
    """Custom-avatar hash only; never the default fallback (which all
    avatarless users share and would false-match)."""
    avatar = getattr(member, "avatar", None)
    return avatar.key if avatar is not None else None


def extract_member_features(member, *, recent_roles=None) -> Dict:
    """Live features for a joining/acting member (no message component)."""
    return {
        "avatar_hash": _avatar_key(member),
        "role_ids": _member_role_ids(member, recent_roles),
        "age_band": age_band(_account_age_seconds(member)),
        "username": getattr(member, "name", None),
        "nhash": None,
        "simhash": None,
    }


def extract_message_features(member, text: str, *, recent_roles=None) -> Dict:
    """Member features plus this single message's exact/near-dup fingerprints."""
    feats = extract_member_features(member, recent_roles=recent_roles)
    norm = normalize(text)
    feats["nhash"] = norm_hash(text)
    feats["simhash"] = simhash64(tokenize(norm))
    return feats


def extract_text_features(text: str) -> Dict:
    """A message's exact/near-dup fingerprints only, no member features.

    Used by `sig simulate` so scoring reflects the text alone, not whoever ran
    the command (avoids spurious age/username matches against the invoker)."""
    norm = normalize(text)
    return {"nhash": norm_hash(text), "simhash": simhash64(tokenize(norm))}


def fingerprint_text(text: str) -> Tuple[str, int]:
    """(normalized-hash, simhash) fingerprints for a single message."""
    norm = normalize(text)
    return norm_hash(text), simhash64(tokenize(norm))


def _fingerprint_many(texts) -> Tuple[List[str], List[int]]:
    nhashes: List[str] = []
    simhashes: List[int] = []
    for text in texts or []:
        if not text:
            continue
        nh, sh = fingerprint_text(text)
        nhashes.append(nh)
        simhashes.append(sh)
    return list(dict.fromkeys(nhashes)), simhashes  # dedupe nhashes, keep order


def _assemble(*, label, created_by, trust, avatar_hash, role_ids, age_band_, username_sample, message_texts) -> Dict:
    nhashes, simhashes = _fingerprint_many(message_texts)
    return {
        "id": uuid.uuid4().hex[:8],
        "label": label,
        "created_by": created_by,
        "created_at": time.time(),
        "trust": trust,  # "confirmed" | "auto"
        "avatar_hash": avatar_hash,
        "role_ids": sorted(role_ids or []),
        "age_band": age_band_,
        "username_sample": username_sample,
        "msg_nhashes": nhashes,
        "msg_simhashes": simhashes,
    }


def build_signature(
    member,
    *,
    label: str = "",
    created_by: int = 0,
    trust: str = "confirmed",
    message_texts: Optional[List[str]] = None,
    recent_roles=None,
) -> Dict:
    """Capture a live member (+ optional sample messages) into a signature dict."""
    return _assemble(
        label=label,
        created_by=created_by,
        trust=trust,
        avatar_hash=_avatar_key(member),
        role_ids=_member_role_ids(member, recent_roles),
        age_band_=age_band(_account_age_seconds(member)),
        username_sample=getattr(member, "name", None),
        message_texts=message_texts,
    )


def build_manual(
    *,
    label: str = "",
    created_by: int = 0,
    message_texts: Optional[List[str]] = None,
    avatar_hash: Optional[str] = None,
    username: Optional[str] = None,
    age_band_: Optional[str] = None,
    role_ids=None,
) -> Dict:
    """Assemble a confirmed signature from raw data, for already-banned/deleted
    accounts where no live member object exists (manual seeding from logs)."""
    return _assemble(
        label=label,
        created_by=created_by,
        trust="confirmed",
        avatar_hash=avatar_hash,
        role_ids=role_ids,
        age_band_=age_band_,
        username_sample=username,
        message_texts=message_texts,
    )


def _fuzzy_ratio(a: str, b: str) -> float:
    """rapidfuzz token-sort ratio 0-100; degrades to 0 if dep missing."""
    try:
        from rapidfuzz import fuzz
    except Exception:
        return 0.0
    return float(fuzz.token_sort_ratio(a, b))


def compare(
    feats: Dict, signature: Dict, weights: Optional[Dict] = None, *, simhash_dist: int = 6
) -> Tuple[float, List[str]]:
    """
    Score a candidate's ``feats`` against one ``signature``.

    Returns ``(confidence 0.0-1.0, why[])``. Strong exact matches short-circuit
    to a high floor; otherwise a weighted mean of the per-signal sub-scores,
    suppressed to 0 when only weak signals fire.
    """
    weights = weights or DEFAULT_WEIGHTS

    # --- strong-signal overrides ---
    av = feats.get("avatar_hash")
    if av and av == signature.get("avatar_hash"):
        return 0.97, ["exact avatar hash"]
    nh = feats.get("nhash")
    if nh and nh in set(signature.get("msg_nhashes") or []):
        return 0.95, ["exact normalized message hash"]

    subs: Dict[str, float] = {}

    # msg near-duplicate (SimHash), gated so only genuine near-dups score
    fsh = feats.get("simhash")
    sig_shs = signature.get("msg_simhashes") or []
    if fsh and sig_shs:
        dist = min(hamming(fsh, s) for s in sig_shs)
        subs["msg_simhash"] = (1.0 - dist / 64.0) if dist <= simhash_dist else 0.0

    # role-set Jaccard overlap
    froles = set(feats.get("role_ids") or [])
    sroles = set(signature.get("role_ids") or [])
    if froles and sroles:
        union = froles | sroles
        subs["role_jaccard"] = len(froles & sroles) / len(union) if union else 0.0

    # username fuzzy ratio (low ratios are dropped, not counted as 0, so a weak
    # partial name overlap neither inflates nor bypasses the weak guard)
    fname = feats.get("username")
    if fname and signature.get("username_sample"):
        ratio = _fuzzy_ratio(fname, signature["username_sample"]) / 100.0
        if ratio >= _USERNAME_FUZZY_FLOOR:
            subs["username_fuzzy"] = ratio

    # weak / corroborating signal
    fab = feats.get("age_band")
    if fab is not None and signature.get("age_band") is not None:
        subs["age_band"] = 1.0 if fab == signature.get("age_band") else 0.0

    # weak-alone guard: never act on age corroboration by itself
    if not any(subs.get(k, 0.0) > 0.0 for k in _STRONG_SUBS):
        return 0.0, ["only weak signals - suppressed"]

    num = sum(weights.get(k, 0.0) * v for k, v in subs.items())
    den = sum(weights.get(k, 0.0) for k in subs)
    conf = (num / den) if den else 0.0
    why = [f"{k}={subs[k]:.2f}" for k in sorted(subs)]
    return conf, why


def compare_store(
    feats: Dict, store: List[Dict], weights: Optional[Dict] = None, *, simhash_dist: int = 6
) -> Tuple[float, Optional[Dict], List[str]]:
    """Best (confidence, signature, why) across every saved signature."""
    best: Tuple[float, Optional[Dict], List[str]] = (0.0, None, [])
    for sig in store or []:
        conf, why = compare(feats, sig, weights, simhash_dist=simhash_dist)
        if conf > best[0]:
            best = (conf, sig, why)
    return best
