"""Store selection for the internal gate: shared when possible, else per-process.

Kept out of ``internal.py`` so the credential/HMAC surface and the replay-store
lifecycle are two separate concerns with two separate size budgets. This module
owns the ONE decision the gate has to make about its seen-signature set, and
answers it the way ``pry.core.ratelimit`` answers the same question: use the
shared backend when it is configured and healthy, degrade to per-process
otherwise, and never take the request path down over infrastructure.

The asymmetry that matters is that the shared store can only ever *widen*
acceptance. Replay is consulted after the HMAC is verified, so a signature in
this set has already proved possession of ``PRY_INTERNAL_TOKEN``; losing the
store means we forget a nonce, never that we admit an unauthenticated caller.
Failing closed here would instead reject our own first-party jobs.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import logging
import time
from typing import Any

from pry.payments.x402_middleware.internal_replay_store import RedisSeenSignatures

logger = logging.getLogger(__name__)

# Re-probe cadence after a failed/absent probe, so a Redis that comes back up
# is adopted without a restart and one that is down is not dialled per request.
PROBE_RETRY_SECONDS = 30.0

# Optional cross-process seen-set. None until a Redis URL is configured AND the
# server answered, so an unreachable Redis degrades to the in-process cache.
_STORE: RedisSeenSignatures | None = None
_PROBED_AT = 0.0


def configured_redis_url() -> str:
    """Redis URL from settings, or "" — a settings failure is not fatal."""
    try:
        from pry.core.settings import settings

        return (getattr(settings, "redis_url", "") or "").strip()
    except (
        OSError,
        TypeError,
        ValueError,
        AttributeError,
        KeyError,
    ) as exc:  # a settings import must never break the gate
        logger.warning(
            "payments_exception_swallowed",
            extra={"error": str(exc), "handler": "configured_redis_url"},
        )
        return ""


def get_store(ttl_seconds: int) -> RedisSeenSignatures | None:
    """The shared seen-set when Redis is usable, else None (use per-process)."""
    global _STORE, _PROBED_AT

    url = configured_redis_url()
    if not url:
        _STORE = None
        return None
    if _STORE is not None:
        return _STORE
    if time.time() - _PROBED_AT < PROBE_RETRY_SECONDS:
        return None
    _PROBED_AT = time.time()
    # Only adopt a store that actually answered, so _STORE is never a
    # known-broken handle. probe() never raises.
    store = RedisSeenSignatures(url, ttl_seconds)
    _STORE = store if store.probe() else None
    return _STORE


def install(store: RedisSeenSignatures | Any) -> None:
    """Adopt a ready-made store (tests / embedding). Pass None to clear."""
    global _STORE
    _STORE = store
