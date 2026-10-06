"""First-party (internal) service access for the x402 gate.

Product policy (2026-09-26): external customers stay x402-paid; our own
first-party jobs must not pay ourselves. So a caller presenting
``X-Internal-Token`` with a valid HMAC over the request fingerprint is served
without a payment challenge.

Security posture:
- FAIL CLOSED when ``PRY_INTERNAL_TOKEN`` is unset — an unset token must never
  degrade into "everyone is internal", which would silently zero the revenue
  path for every external agent.
- Constant-time comparison (``hmac.compare_digest``) so a wrong token leaks no
  length/prefix information through timing.
- The HMAC binds method + path + caller identity + unix timestamp, checked
  against ``PRY_INTERNAL_MAX_SKEW_SECONDS`` (default 300). A captured signature
  is usable only inside the window, and a seen signature is refused on a second
  use. A missing / non-numeric timestamp, or a junk skew setting, rejects.
- SHARED REPLAY CACHE (2026-09-27): the seen-signature set is per-process, which
  is correct only at ``--workers 1``. With a Redis URL configured and answering,
  the set is shared across every worker, so a captured request cannot be
  replayed by hopping workers. Redis trouble degrades to the per-process cache
  and never rejects traffic — see ``internal_replay_selection`` for why failing
  open is the right availability trade here.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
import hashlib
import hmac
import logging
import os
import time
from collections import OrderedDict
from typing import Any

from pry.payments.x402_middleware import internal_replay_selection as _selection

logger = logging.getLogger(__name__)

INTERNAL_TOKEN_HEADER = b"x-internal-token"
INTERNAL_SIG_HEADER = b"x-internal-signature"
INTERNAL_TIMESTAMP_HEADER = b"x-internal-timestamp"
INTERNAL_SCOPE_KEY = "x402_verified"

DEFAULT_MAX_SKEW_SECONDS = 300
MAX_SKEW_ENV = "PRY_INTERNAL_MAX_SKEW_SECONDS"
# Evict a seen signature once it can no longer be inside the skew window, so
# the cache cannot grow without bound while still covering every replay.
REPLAY_TTL_SECONDS = 2 * DEFAULT_MAX_SKEW_SECONDS
MAX_REPLAY_ENTRIES = 8192
# Bounded LRU: when the cap is hit the oldest entry is dropped, which only
# ever widens a window that has already expired past the skew bound.
_SEEN_SIGNATURES: OrderedDict[str, float] = OrderedDict()


def _already_seen_local(signature: str, now: float) -> bool:
    """Record a signature in-process; True when it was already used."""
    for seen, seen_expiry in list(_SEEN_SIGNATURES.items()):
        if seen_expiry <= now:
            del _SEEN_SIGNATURES[seen]
    if signature in _SEEN_SIGNATURES:
        return True
    _SEEN_SIGNATURES[signature] = now + REPLAY_TTL_SECONDS
    while len(_SEEN_SIGNATURES) > MAX_REPLAY_ENTRIES:
        _SEEN_SIGNATURES.popitem(last=False)
    return False


def _already_seen(signature: str, now: float) -> bool:
    """Record a signature as seen; True when it was already used.

    Called only AFTER signature verification, so an unauthenticated attacker
    cannot poison the cache. The shared store is authoritative when it
    answers; otherwise we fall back in-process, failing OPEN — 402-ing our
    own first-party jobs when Redis blinks is worse than the per-process
    window this service already had.
    """
    store = _selection.get_store(REPLAY_TTL_SECONDS)
    if store is not None:
        shared = store.already_seen(signature, now)
        if shared is not None:
            return shared
    return _already_seen_local(signature, now)


def internal_max_skew() -> int:
    """Configured max clock skew in seconds; fail-closed when unusable.

    Only an ABSENT setting falls back to ``DEFAULT_MAX_SKEW_SECONDS``. A present
    but non-numeric, blank, or non-positive value rejects every internal request
    rather than silently widening (or disabling) the freshness window.
    """
    raw = os.environ.get(MAX_SKEW_ENV)
    if raw is None:
        return DEFAULT_MAX_SKEW_SECONDS
    try:
        skew = int(raw.strip())
    except ValueError as exc:
        logger.warning(
            "payments_exception_swallowed",
            extra={"error": str(exc), "handler": "internal_max_skew"},
        )
        return 0
    return skew if skew > 0 else 0


def internal_token() -> str:
    """Return the configured internal service token (empty when unset)."""
    return (os.environ.get("PRY_INTERNAL_TOKEN") or "").strip()


def internal_enabled() -> bool:
    """True when the internal free path is configured. Fail-closed when unset."""
    return bool(internal_token())


def _fingerprint(method: str, path: str, caller: str, timestamp: str) -> str:
    """Canonicalise the signed fields (shared by signer and verifier)."""
    return f"{method.upper()}\n{path}\n{caller}\n{timestamp}"


def internal_signature(
    token: str, method: str, path: str, caller: str, timestamp: str | int | None = None
) -> str:
    """Build the HMAC an internal caller must present.

    Deliberately dependency-free: callers need no SDK to compute it, and the
    message is stable so a retry can recompute it without server state.

    ``timestamp`` is the unix second the caller stamps in
    ``X-Internal-Timestamp``; it is signed so it cannot be widened in flight.
    It defaults to "now" for convenience in first-party code, but a caller
    should send the value it actually transmitted.
    """
    stamp = str(int(timestamp)) if timestamp is not None else str(int(time.time()))
    return hmac.new(
        token.encode(), _fingerprint(method, path, caller, stamp).encode(), hashlib.sha256
    ).hexdigest()


def _fresh_timestamp(headers: dict[bytes, bytes], now: float) -> str | None:
    """Return the signed timestamp when it is inside the skew window.

    None means reject: missing, non-numeric, or outside the window.
    """
    skew = internal_max_skew()
    if skew <= 0:
        return None
    raw = headers.get(INTERNAL_TIMESTAMP_HEADER, b"").decode().strip()
    if not raw or not raw.isdigit():
        return None
    try:
        stamp = int(raw)
    except ValueError as exc:  # pragma: no cover - isdigit() already guards
        logger.warning(
            "payments_exception_swallowed",
            extra={"error": str(exc), "handler": "_fresh_timestamp"},
        )
        return None
    if abs(now - stamp) > skew:
        return None
    return raw


def internal_request(scope: dict[str, Any], headers: dict[bytes, bytes]) -> bool:
    """True when the request carries a valid, fresh, first-party internal credential."""
    token = internal_token()
    if not token:
        return False
    presented = headers.get(INTERNAL_TOKEN_HEADER, b"").decode().strip()
    if not presented or not hmac.compare_digest(presented, token):
        return False
    now = time.time()
    timestamp = _fresh_timestamp(headers, now)
    if timestamp is None:
        return False
    signature = headers.get(INTERNAL_SIG_HEADER, b"").decode().strip()
    if not signature:
        return False
    expected = internal_signature(
        token,
        str(scope.get("method", "")),
        str(scope.get("path", "")),
        _caller_from_scope(scope),
        timestamp,
    )
    if not hmac.compare_digest(signature, expected):
        return False
    return not _already_seen(signature, now)


def _caller_from_scope(scope: dict[str, Any]) -> str:
    """Derive the caller identity bound into the signature (socket peer)."""
    try:
        from pry.payments.x402_middleware.classification import _caller_key_from_scope

        return _caller_key_from_scope(scope)
    except ImportError as exc:  # pragma: no cover - partial import during startup
        logger.warning(
            "payments_exception_swallowed",
            extra={"error": str(exc), "handler": "_caller_from_scope"},
        )
        client = scope.get("client") or ()
        return str(client[0]) if client and client[0] else ""


def mark_internal_verified(scope: dict[str, Any]) -> None:
    """Mark the ASGI scope so the inner auth layer accepts the call.

    Same payment-shaped dict the owner path uses: the auth layer reads
    ``payment_id``/``batch_id`` off it, so a bool would crash it.
    """
    scope[INTERNAL_SCOPE_KEY] = {"payment_id": "internal", "batch_id": "", "internal": True}
