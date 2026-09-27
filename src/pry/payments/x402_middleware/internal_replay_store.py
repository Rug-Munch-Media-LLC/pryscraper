"""Shared (cross-process) seen-signature store for the x402 internal gate.

The per-process :data:`pry.payments.x402_middleware.internal._SEEN_SIGNATURES`
OrderedDict is exactly right at ``--workers 1`` and wrong at N: a captured
internal request replayed against a different worker is invisible, so the
skew window is enforced per-worker instead of globally.

This module supplies the same contract against Redis, with the repo's existing
fail-open shape (``pry.core.ratelimit.RateLimiter``): the shared path is used
ONLY when a Redis URL is configured AND the server answers a ping. Any missing,
misconfigured, or unreachable Redis degrades to the per-process cache rather
than rejecting traffic.

The availability rule is deliberately asymmetric, and this is the security
point of the module:

- A shared-store FAILURE must never fail CLOSED. Rejecting every internal
  request when Redis blips would take out first-party jobs — the very traffic
  this path exists to serve — so we fall back to the in-process cache, which
  is what the service already did before this change. Legitimate traffic keeps
  working; the residual exposure is one replay routed to a worker that has not
  seen it, which is the pre-existing behaviour, not a regression.
- The internal gate stays fail-closed where it counts. Replay is consulted only
  after the HMAC is verified (see ``internal._already_seen``), so nothing here
  decides authentication — a shared store can only ever *widen* acceptance, and
  only for a signature that already proved possession of ``PRY_INTERNAL_TOKEN``.

The TTL is ``REPLAY_TTL_SECONDS`` (2x the skew window), matching the in-process
cache exactly: a signature must stay remembered until it can no longer be
inside the window, and no longer.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import logging
import time
from typing import Any, Protocol

logger = logging.getLogger(__name__)


# The failure modes a Redis client actually raises, plus the plumbing errors
# any duck-typed client may surface. Narrow on purpose: a broad ``except
# Exception`` here would swallow programming errors, which is how a
# misconfigured client would look like "Redis is down" forever.
def _redis_errors() -> tuple[type[BaseException], ...]:
    """The redis client's own error base, when redis is importable.

    A real client raises ``redis.exceptions.RedisError`` (auth failures,
    connection drops, command errors). Including it here is what makes the
    narrow catch actually cover production; without it we would either miss
    the real failure or have to go back to ``except Exception``.
    """
    try:
        from redis.exceptions import RedisError
    except ImportError:  # pragma: no cover - redis is optional
        return ()
    return (RedisError,)


_BACKEND_ERRORS: tuple[type[BaseException], ...] = (
    OSError,
    ConnectionError,
    TimeoutError,
    TypeError,
    ValueError,
    AttributeError,
) + _redis_errors()

# Redis key namespace. Versioned so a shape change can never read old keys.
KEY_PREFIX = "pry:x402:internal:seen:"
# Cooldown before retrying a Redis connect that just failed, so a dead Redis is
# dialled at most once per interval instead of on every internal request.
REDIS_RETRY_SECONDS = 30.0
# Bounded connect/socket timeout. The gate is on the request path and MUST NOT
# add a multi-second stall to a scrape; a slow Redis is an unavailable Redis.
REDIS_TIMEOUT_SECONDS = 0.25


class SeenSignatureStore(Protocol):
    """The contract the gate needs from a seen-nonce set."""

    def already_seen(self, signature: str, now: float) -> bool:
        """True when ``signature`` was already used; records it otherwise."""
        ...


class RedisSeenSignatures:
    """Seen-signature set shared by every worker, via ``SET NX EX``.

    ``SET key 1 NX EX ttl`` is atomic, so two workers racing on the same
    captured request cannot both win — which an ``EXISTS``-then-``SET`` pair
    could not guarantee. The TTL is the whole eviction strategy: Redis drops
    the key once the signature can no longer be inside the skew window, so
    there is no unbounded growth and no sweeper.
    """

    def __init__(self, redis_url: str, ttl_seconds: int, client: Any = None) -> None:
        self._redis_url = redis_url
        self._ttl = int(ttl_seconds)
        # An injected client short-circuits the lazy connect; this is the seam
        # tests use to supply a fake, so no test has to stub the connect away.
        self._client = client
        self._failed_at = 0.0

    def probe(self) -> bool:
        """True when Redis is usable right now. Never raises."""
        return self._get_client() is not None

    def _get_client(self) -> Any:
        """Pinged Redis client, or None (with cooldown after a failure).

        An injected client is pinged too, so a store is never adopted on the
        strength of a client that cannot actually answer.
        """
        if self._client is not None:
            try:
                self._client.ping()
            except _BACKEND_ERRORS as exc:  # degrade, never raise
                self._client = None
                self._failed_at = time.time()
                logger.warning(
                    "internal_replay_redis_error_falling_back_to_process",
                    extra={"error": str(exc)[:160]},
                )
                return None
            return self._client
        if time.time() - self._failed_at < REDIS_RETRY_SECONDS:
            return None
        try:
            import redis as redis_py

            client = redis_py.Redis.from_url(
                self._redis_url,
                socket_connect_timeout=REDIS_TIMEOUT_SECONDS,
                socket_timeout=REDIS_TIMEOUT_SECONDS,
                decode_responses=True,
            )
            client.ping()
        except _BACKEND_ERRORS as exc:  # any backend error degrades
            self._failed_at = time.time()
            logger.warning(
                "internal_replay_redis_unavailable_falling_back_to_process",
                extra={"error": str(exc)[:160]},
            )
            return None
        self._client = client
        logger.info("internal_replay_redis_connected")
        return self._client

    def already_seen(self, signature: str, now: float) -> bool | None:
        """Atomically claim ``signature``; True = already used.

        ``None`` means "Redis could not answer" — the caller must fall back to
        the in-process cache. ``now`` is accepted for interface symmetry with
        the in-process store; Redis owns expiry via the TTL.
        """
        del now
        client = self._get_client()
        if client is None:
            return None
        key = KEY_PREFIX + signature
        try:
            stored = client.set(key, "1", nx=True, ex=self._ttl)
        except _BACKEND_ERRORS as exc:  # mid-flight failure degrades too
            self._client = None
            self._failed_at = time.time()
            logger.warning(
                "internal_replay_redis_error_falling_back_to_process",
                extra={"error": str(exc)[:160]},
            )
            return None
        return stored is None

    def reset(self) -> None:
        """Forget the cached client and any failure cooldown."""
        self._client = None
        self._failed_at = 0.0
