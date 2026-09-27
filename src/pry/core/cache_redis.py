"""Redis backend plumbing for the response cache.

Split out of ``cache`` so the cache's own policy — keys, TTLs, eviction, byte
budget — is readable without the connection lifecycle mixed in. Mixed in as
:class:`RedisBackendMixin`, so ``ResponseCache`` still exposes every one of
these as a method and no call site changes.

Redis is optional by design: absent, unreachable or broken and the cache
degrades to its in-process L1. The one thing it must never do is fail
*silently into a plausible story*. A settings error that resolved to an empty
URL would look exactly like "Redis is not configured" and would pin the
process to memory-only for its whole lifetime.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import contextlib
import logging
import time
from typing import Any

_REDIS_KEY_PREFIX = "pry:cache:"
_REDIS_RETRY_SECONDS = 30.0
logger = logging.getLogger(__name__)


class RedisBackendMixin:
    """Connection lifecycle and key naming for the optional Redis tier.

    A connection failure is expected and handled: it drops to the in-process
    L1 after logging. A *configuration* failure is not handled the same way —
    it raises, because a misconfigured cache should be visible immediately
    rather than silently degrading forever.
    """

    _redis_backend: Any
    _redis: Any
    _redis_failed_at: float
    backend: str

    def _redis_url(self) -> str:
        """Redis URL, or ``""`` only when Redis is genuinely not configured.

        A settings-resolution failure is not that: returning ``""`` would pin
        the process to memory-only, so those raise.
        """
        if self._redis_backend is not None:
            return str(self._redis_backend)
        try:
            from pry.core.settings import settings

            return str(settings.redis_url)
        except (ImportError, AttributeError, TypeError, ValueError) as e:
            # An unusable redis_url is a config error, not "Redis is off".
            logger.error(
                "response_cache_redis_url_unresolvable",
                extra={"error_type": type(e).__name__},
            )
            raise

    async def _get_redis(self) -> Any:
        """Return a pinged async Redis client, or None (with cooldown)."""
        if self._redis is not None:
            return self._redis
        url = self._redis_url()
        if not url:
            return None
        now = time.time()
        if now - self._redis_failed_at < _REDIS_RETRY_SECONDS:
            return None
        try:
            import redis.asyncio as aioredis

            client = aioredis.Redis.from_url(
                url,
                socket_connect_timeout=0.25,
                socket_timeout=0.25,
                decode_responses=True,
            )
            await client.ping()
            self._redis = client
            self.backend = "redis"
            logger.info("response_cache_redis_connected")
            return client
        except Exception as e:  # noqa: BLE001 — any backend error must degrade
            self._redis_failed_at = now
            logger.warning(
                "response_cache_redis_unavailable_falling_back_to_memory",
                extra={"error": str(e)[:160]},
            )
            return None

    def _redis_key(self, key: str) -> str:
        """Full Redis key for a cache key (md5 hash)."""
        return f"{_REDIS_KEY_PREFIX}{key}"

    async def close(self) -> None:
        """Close the Redis connection on shutdown. Safe to call repeatedly."""
        if self._redis is not None:
            with contextlib.suppress(Exception):  # best-effort close
                await self._redis.aclose()
            self._redis = None
