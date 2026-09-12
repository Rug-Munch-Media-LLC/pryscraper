"""Pry — LRU cache with optional Redis backing.

Prevents re-scraping the same URL within TTL window.

The in-memory LRU (``OrderedDict``) is the L1 cache. When a Redis URL is
configured and reachable, entries are also written to Redis (``SETEX`` with
the entry TTL) so the cache survives restarts and is shared across replicas.
The in-memory LRU then acts as a read-through L1: check memory first, then
Redis, then fetch. If Redis is unavailable (unset, unreachable, or a runtime
error) the cache degrades to in-memory only — a Redis outage never takes the
scraper down.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

import contextlib
import hashlib
import json
import logging
import time
from collections import OrderedDict
from typing import Any

from pry.core.observability import CACHE_HITS

logger = logging.getLogger(__name__)

# Redis key prefix for cached responses. Full key: ``pry:cache:{md5_hash}``.
_REDIS_KEY_PREFIX = "pry:cache:"
# Cooldown (seconds) before retrying a failed Redis connection.
_REDIS_RETRY_SECONDS = 30.0


class ResponseCache:
    """LRU cache with TTL expiry and optional Redis backing.

    Default TTL: 300 seconds (5 min) for pages, 3600 (1 hr) for API calls.

    The synchronous :meth:`get` / :meth:`set` operate purely on the in-memory
    LRU (unchanged behavior). The async :meth:`aget` / :meth:`aset` are the
    read-through path: they check memory first, then Redis, then fetch, and
    write through to both layers.
    """

    # Max size of a single cached payload. Larger responses are skipped to
    # avoid a single 5MB HTML page x 1000 entries ballooning memory.
    _MAX_PAYLOAD_BYTES = 5 * 1024 * 1024  # 5MB
    # Soft ceiling on total cached bytes. When exceeded, oldest entries are
    # evicted (LRU) until the cache fits back under the limit.
    _MAX_TOTAL_BYTES = 512 * 1024 * 1024  # 512MB

    def __init__(self, capacity: int = 500, redis_backend: Any = None):
        self.capacity = capacity
        self._cache: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._hits = 0
        self._misses = 0
        self._total_bytes = 0

        # Redis backend state (lazy connect + failure cooldown). Mirrors the
        # pattern in ratelimit.py / session_store.py: never raise on Redis
        # failure, degrade to memory.
        self._redis_backend = redis_backend
        self._redis: Any = None
        self._redis_failed_at = 0.0
        self.backend = "memory"

    # ── Redis backend ────────────────────────────────────────────────────────

    def _redis_url(self) -> str:
        """Resolve the Redis URL from the injected backend or settings."""
        if self._redis_backend is not None:
            return str(self._redis_backend)
        try:
            from pry.core.settings import settings

            return str(settings.redis_url)
        except Exception:  # noqa: BLE001 — settings import must never break cache
            return ""

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

    # ── Key / payload helpers ────────────────────────────────────────────────

    def _key(self, url: str, options: dict[str, Any] | None = None) -> str:
        """Generate cache key from URL + options."""
        opt_str = json.dumps(options or {}, sort_keys=True)
        raw = f"{url}:{opt_str}"
        return hashlib.md5(raw.encode(), usedforsecurity=False).hexdigest()

    def _payload_bytes(self, data: dict[str, Any]) -> int:
        """Serialized byte size of a payload (used for size accounting)."""
        return len(json.dumps(data, default=str).encode())

    # ── Synchronous in-memory API (unchanged behavior) ──────────────────────

    def get(self, url: str, options: dict[str, Any] | None = None) -> dict[str, Any] | None:
        """Get cached response from the in-memory LRU if fresh."""
        key = self._key(url, options)
        now = time.time()

        # Check local cache
        if key in self._cache:
            entry = self._cache[key]
            if entry["expires"] > now:
                self._hits += 1
                self._cache.move_to_end(key)
                if CACHE_HITS:
                    CACHE_HITS.labels(cache_type="local").inc()
                data: dict[str, Any] = entry["data"]
                return data
            else:
                del self._cache[key]
                self._decrement_bytes(entry)

        self._misses += 1
        return None

    def set(
        self,
        url: str,
        data: dict[str, Any],
        options: dict[str, Any] | None = None,
        ttl: int = 300,
    ) -> None:
        """Cache a response in the in-memory LRU with TTL in seconds."""
        key = self._key(url, options)

        # Skip caching oversized payloads to bound memory usage.
        payload_bytes = self._payload_bytes(data)
        if payload_bytes > self._MAX_PAYLOAD_BYTES:
            logger.debug(
                "cache_skip_oversized",
                extra={"url": url, "payload_bytes": payload_bytes},
            )
            return

        entry = {"data": data, "expires": time.time() + ttl, "cached_at": time.time()}

        # Evict oldest if at capacity
        if len(self._cache) >= self.capacity:
            self._evict_oldest()

        # Evict oldest until total bytes fit under the ceiling.
        while self._total_bytes + payload_bytes > self._MAX_TOTAL_BYTES and self._cache:
            self._evict_oldest()

        self._cache[key] = entry
        self._total_bytes += payload_bytes

    # ── Async read-through API (memory → Redis → fetch) ─────────────────────

    async def aget(self, url: str, options: dict[str, Any] | None = None) -> dict[str, Any] | None:
        """Read-through get: check memory, then Redis, then fetch.

        Returns the cached payload or ``None`` on a miss. Redis failures
        degrade to the in-memory result (or a miss) — never raise.
        """
        key = self._key(url, options)

        # 1. In-memory L1 first.
        local = self.get(url, options)
        if local is not None:
            return local

        # 2. Redis L2.
        client = await self._get_redis()
        if client is not None:
            try:
                raw = await client.get(self._redis_key(key))
                if raw is not None:
                    try:
                        data = json.loads(raw)
                    except (TypeError, ValueError):
                        data = None
                    if data is not None:
                        # Populate L1 so subsequent reads hit memory.
                        self._store_local(key, data)
                        self._hits += 1
                        if CACHE_HITS:
                            CACHE_HITS.labels(cache_type="redis").inc()
                        redis_data: dict[str, Any] = data
                        return redis_data
            except Exception as e:  # noqa: BLE001 — Redis down → memory fallback
                self._drop_redis(e)

        self._misses += 1
        return None

    async def aset(
        self,
        url: str,
        data: dict[str, Any],
        options: dict[str, Any] | None = None,
        ttl: int = 300,
    ) -> None:
        """Write-through set: store in memory and, if configured, Redis.

        Oversized payloads (over ``_MAX_PAYLOAD_BYTES``) are skipped entirely
        (both layers) to bound memory. Redis failures degrade to memory-only.
        """
        key = self._key(url, options)

        payload_bytes = self._payload_bytes(data)
        if payload_bytes > self._MAX_PAYLOAD_BYTES:
            logger.debug(
                "cache_skip_oversized",
                extra={"url": url, "payload_bytes": payload_bytes},
            )
            return

        # 1. In-memory L1.
        self._store_local(key, data, ttl=ttl)

        # 2. Redis L2 (best-effort).
        client = await self._get_redis()
        if client is not None:
            try:
                await client.setex(self._redis_key(key), ttl, json.dumps(data))
            except Exception as e:  # noqa: BLE001 — Redis down → memory only
                self._drop_redis(e)

    def _store_local(self, key: str, data: dict[str, Any], ttl: int = 300) -> None:
        """Store an entry in the in-memory LRU (shared by set/aset/aget)."""
        payload_bytes = self._payload_bytes(data)

        # Evict oldest if at capacity.
        if len(self._cache) >= self.capacity:
            self._evict_oldest()

        # Evict oldest until total bytes fit under the ceiling.
        while self._total_bytes + payload_bytes > self._MAX_TOTAL_BYTES and self._cache:
            self._evict_oldest()

        entry = {"data": data, "expires": time.time() + ttl, "cached_at": time.time()}
        self._cache[key] = entry
        self._total_bytes += payload_bytes

    def _drop_redis(self, error: Exception) -> None:
        """Drop the Redis client and enter the failure cooldown."""
        self._redis = None
        self._redis_failed_at = time.time()
        self.backend = "memory"
        logger.warning(
            "response_cache_redis_error_falling_back_to_memory",
            extra={"error": str(error)[:160]},
        )

    def _evict_oldest(self) -> None:
        """Evict the least-recently-used entry and decrement byte accounting."""
        if not self._cache:
            return
        _key, entry = self._cache.popitem(last=False)
        self._decrement_bytes(entry)

    def _decrement_bytes(self, entry: dict[str, Any]) -> None:
        """Decrement total byte accounting for a removed entry."""
        self._total_bytes -= len(json.dumps(entry["data"], default=str).encode())
        if self._total_bytes < 0:
            self._total_bytes = 0

    def stats(self) -> dict[str, Any]:
        """Get cache hit/miss statistics."""
        total = self._hits + self._misses
        return {
            "size": len(self._cache),
            "capacity": self.capacity,
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": round(self._hits / total * 100, 1) if total > 0 else 0,
            "backend": self.backend,
        }

    def invalidate(self, url: str) -> None:
        """Remove cached entry for a URL from the in-memory LRU."""
        keys_to_remove = [k for k, v in self._cache.items() if v["data"].get("url") == url]
        for k in keys_to_remove:
            self._decrement_bytes(self._cache[k])
            del self._cache[k]

    def clear(self) -> None:
        """Clear the in-memory cache."""
        self._cache.clear()
        self._hits = 0
        self._misses = 0
        self._total_bytes = 0
