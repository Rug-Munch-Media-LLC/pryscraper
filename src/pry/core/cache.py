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

import json
import logging
import threading
import time
from collections import OrderedDict
from typing import Any

from pry.core.cache_redis import RedisBackendMixin
from pry.core.observability import CACHE_HITS

logger = logging.getLogger(__name__)


class ResponseCache(RedisBackendMixin):
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
        self._lock = threading.RLock()

        # Redis backend state (lazy connect + failure cooldown). Mirrors the
        # pattern in ratelimit.py / session_store.py: never raise on Redis
        # failure, degrade to memory.
        self._redis_backend = redis_backend
        self._redis: Any = None
        self._redis_failed_at = 0.0
        self.backend = "memory"

    # ── Redis backend ────────────────────────────────────────────────────────

    # ── Key / payload helpers ────────────────────────────────────────────────

    def _payload_bytes(self, data: dict[str, Any]) -> int:
        """Serialized byte size of a payload (used for size accounting)."""
        return len(json.dumps(data, default=str).encode())

    # ── Synchronous in-memory API (unchanged behavior) ──────────────────────

    def get(self, url: str, options: dict[str, Any] | None = None) -> dict[str, Any] | None:
        """Get cached response from the in-memory LRU if fresh."""
        key, now = self._key(url, options), time.time()
        with self._lock:
            entry = self._cache.get(key)
            if entry is not None and entry["expires"] > now:
                self._hits += 1
                self._cache.move_to_end(key)
                if CACHE_HITS:
                    CACHE_HITS.labels(cache_type="local").inc()
                data: dict[str, Any] = entry["data"]
                return data
            if entry is not None:
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
        if not self._store_local(key, data, ttl=ttl, options=options):
            return
        # The scrape endpoint calls this sync method, so L2 is written from
        # here (fire-and-forget) instead of staying unreachable via aget/aset.
        self._schedule_l2_write(key, data, ttl)

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
            except Exception as e:
                logger.warning("cache_exception_handler", exc_info=True)
                self._drop_redis(e)
            else:
                if raw is not None:
                    try:
                        data = json.loads(raw)
                    except (TypeError, ValueError) as e:
                        # Poisoned entry, not a miss. Reported, then the bad
                        # value is discarded so the next get re-fetches.
                        logger.error(
                            "response_cache_redis_entry_undecodable",
                            extra={"key": self._redis_key(key), "error_type": type(e).__name__},
                        )
                        await self._discard_redis_entry(client, self._redis_key(key))
                        data = None
                    if data is not None:
                        # Populate L1 so subsequent reads hit memory.
                        self._store_local(key, data, options=options)
                        self._hits += 1
                        if CACHE_HITS:
                            CACHE_HITS.labels(cache_type="redis").inc()
                        return data

        self._misses += 1
        return None

    async def _discard_redis_entry(self, client: Any, full_key: str) -> None:
        """Best-effort delete of a poisoned Redis entry (never raises)."""
        try:
            await client.delete(full_key)
        except Exception as e:  # noqa: BLE001 — best-effort cleanup
            logger.warning(
                "response_cache_redis_cleanup_failed",
                extra={"key": full_key, "error_type": type(e).__name__},
            )

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
        self._store_local(key, data, ttl=ttl, options=options)

        # 2. Redis L2 (best-effort).
        client = await self._get_redis()
        if client is not None:
            try:
                await client.setex(self._redis_key(key), ttl, json.dumps(data))
            except Exception as e:
                logger.warning("cache_exception_handler", exc_info=True)
                self._drop_redis(e)

    def _store_local(
        self, key: str, data: dict[str, Any], ttl: int = 300, options: dict[str, Any] | None = None
    ) -> bool:
        """Store an entry in the LRU; False when the payload was refused."""
        if not self._cacheable(data, options):
            return False
        payload_bytes = self._payload_bytes(data)
        if payload_bytes > self._MAX_PAYLOAD_BYTES:
            logger.debug("cache_skip_oversized", extra={"payload_bytes": payload_bytes})
            return False

        with self._lock:
            # A re-set of the same key must release the bytes it replaces,
            # otherwise _total_bytes only ever drifts upward.
            replaced = self._cache.pop(key, None)
            if replaced is not None:
                self._decrement_bytes(replaced)

            while self._cache and (
                len(self._cache) >= self.capacity
                or self._total_bytes + payload_bytes > self._MAX_TOTAL_BYTES
            ):
                self._evict_oldest()

            self._cache[key] = {
                "data": data,
                "expires": time.time() + ttl,
                "cached_at": time.time(),
            }
            self._total_bytes += payload_bytes
        return True

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
        with self._lock:
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
        with self._lock:
            total = self._hits + self._misses
            return {
                "size": len(self._cache),
                "capacity": self.capacity,
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate": round(self._hits / total * 100, 1) if total > 0 else 0,
                "bytes": self._total_bytes,
                "backend": self.backend,
            }

    def invalidate(self, url: str) -> None:
        """Purge a URL from L1 and, best-effort, from Redis (``pry:cache:*``).

        Purge call from an async context (CLI/admin task):
        ``await cache._l2_purge_url(url)`` then ``cache.invalidate(url)``.
        From sync code L1 is cleared and the Redis purge is skipped.
        """
        with self._lock:
            keys = [k for k, v in self._cache.items() if v["data"].get("url") == url]
            for k in keys:
                self._decrement_bytes(self._cache[k])
                del self._cache[k]
        self._schedule_l2_purge(url)

    def clear(self) -> None:
        """Clear the in-memory cache."""
        with self._lock:
            self._cache.clear()
            self._hits = 0
            self._misses = 0
            self._total_bytes = 0
        # Guards the LRU, the byte counter and the hit/miss counters. An
        # RLock because aget() -> get() re-enters on the same thread.
        self._lock = threading.RLock()
