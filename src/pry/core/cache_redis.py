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

**Required Redis eviction policy: ``noeviction`` or a ``volatile-*`` policy
(``volatile-lru`` / ``volatile-ttl`` / ``volatile-random``). NEVER
``allkeys-lru`` / ``allkeys-random`` / ``allkeys-lfu``.**

This instance is shared by cache entries, x402 replay/nonce keys
(``pry:x402:internal:seen:*``), billing counters (``pry:billing:*``) and MCP
sessions (``pry:mcp:sess:*``). Replay keys must survive until their own TTL
expires — evicting one silently reopens a replay window; evicting a billing
counter under-counts a quota. Every one of those keys carries a TTL, so a
``volatile-*`` policy only reaps keys that were going to expire anyway, and
``noeviction`` is always safe. Cache data keys are disposable; the security
and quota keys are not.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
import threading
import time
import uuid
from typing import Any

_REDIS_KEY_PREFIX = "pry:cache:"
_REDIS_RETRY_SECONDS = 30.0
# Bumped when the key recipe changes, so entries written under an older
# (narrower) recipe can never be served back. v1 hashed url + caller options
# only, which allowed a hit to cross tenants and extraction schemas.
_KEY_VERSION = "v2"
# Option keys that identify the caller. Any one of them separates cache
# namespaces; absent, the key is scoped to the shared public namespace.
_TENANT_KEYS = ("tenant", "tenant_id", "api_key", "apikey", "caller_id", "caller", "auth")
# Option keys that carry the extraction schema. An extracted ``data.json``
# payload may only be cached when one of them is present AND in the key.
_SCHEMA_KEYS = ("json_schema", "jsonSchema", "schema", "extraction_schema", "extract_schema")
# Cross-replica load lock: separate namespace, short PX TTL so a crashed
# holder can never wedge the key — the guard expires and the next caller loads.
_LOCK_PREFIX = f"{_REDIS_KEY_PREFIX}lock:"
_LOCK_TTL_MS = 5_000
_POLL_SECONDS = 0.05
# Per-key asyncio locks (one per event loop; process-local is the point).
_FLIGHT_LOCKS: dict[str, list[Any]] = {}
_FLIGHT_GUARD = threading.Lock()
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

    # ── Key recipe ───────────────────────────────────────────────────────────

    def _tenant(self, options: dict[str, Any] | None, tenant: str | None = None) -> str:
        """Caller namespace: explicit argument, else an option, else ``public``."""
        if tenant:
            return str(tenant)
        for name in _TENANT_KEYS:
            value = (options or {}).get(name)
            if value:
                return str(value)
        return "public"

    def _key(
        self, url: str, options: dict[str, Any] | None = None, tenant: str | None = None
    ) -> str:
        """Key over URL, the FULL option set and the tenant namespace."""
        tenant_id = self._tenant(options, tenant)
        opt_str = json.dumps(options or {}, sort_keys=True, default=str)
        raw = f"{_KEY_VERSION}:{tenant_id}:{url}:{opt_str}"
        return hashlib.md5(raw.encode(), usedforsecurity=False).hexdigest()

    def _cacheable(self, data: dict[str, Any], options: dict[str, Any] | None) -> bool:
        """False when an extracted payload must not be cached under this key."""
        inner = data.get("data")
        if not isinstance(inner, dict) or "json" not in inner:
            return True
        if any((options or {}).get(k) for k in _SCHEMA_KEYS):
            return True
        logger.debug("cache_skip_extraction_without_schema_in_key")
        return False

    # ── Single-flight loads ──────────────────────────────────────────────────

    def _flight_lock(self, key: str) -> tuple[asyncio.Lock, list[Any]]:
        """Per-key asyncio lock, reference-counted so the map cannot grow."""
        with _FLIGHT_GUARD:
            entry = _FLIGHT_LOCKS.get(key)
            if entry is None:
                entry = [asyncio.Lock(), 0]
                _FLIGHT_LOCKS[key] = entry
            entry[1] += 1
            return entry[0], entry

    def _release_flight_lock(self, key: str, entry: list[Any]) -> None:
        """Drop a waiter; the entry goes once nobody holds or waits on it."""
        with _FLIGHT_GUARD:
            entry[1] -= 1
            if entry[1] <= 0 and not entry[0].locked() and _FLIGHT_LOCKS.get(key) is entry:
                _FLIGHT_LOCKS.pop(key, None)

    async def _acquire_cross_replica(self, key: str) -> tuple[Any, str, str] | None:
        """Redis ``SET NX PX`` guard: (client, lock_key, token) or None."""
        client = await self._get_redis()
        if client is None:
            return None
        lock_key, token = f"{_LOCK_PREFIX}{key}", uuid.uuid4().hex
        try:
            if await client.set(lock_key, token, nx=True, px=_LOCK_TTL_MS):
                return client, lock_key, token
        except Exception as e:  # noqa: BLE001 — the guard is best-effort
            self._drop_redis(e)
            return None
        return client, lock_key, ""

    async def _release_cross_replica(self, client: Any, lock_key: str, token: str) -> None:
        """Release the guard only if we still own it (best-effort)."""
        if not token:
            return
        try:
            if await client.get(lock_key) == token:
                await client.delete(lock_key)
        except Exception as e:  # noqa: BLE001 — an expiring PX guard is harmless
            logger.debug("response_cache_lock_release_failed", extra={"error": str(e)[:120]})

    async def fetch_or_load(
        self,
        url: str,
        options: dict[str, Any] | None,
        loader: Any,
        ttl: int = 300,
    ) -> dict[str, Any]:
        """Cold-key coalescing: one loader run per key, process- and cluster-wide.

        ``loader`` is an async callable returning the payload. Concurrent cold
        callers in this process queue on a per-key ``asyncio.Lock`` and re-check
        the cache inside it; across replicas a Redis ``SET NX PX`` guard keeps
        one loader running while the others poll for its write. If the guard's
        PX TTL lapses (holder crashed) a waiter loads rather than blocking
        forever, so the worst case is a duplicate load, never a wedge.
        """
        hit = await self.aget(url, options)
        if hit is not None:
            return hit
        key = self._key(url, options)
        lock, entry = self._flight_lock(key)
        try:
            async with lock:
                hit = await self.aget(url, options)
                if hit is not None:
                    return hit
                client, lock_key, token = (None, "", "")
                acquired = await self._acquire_cross_replica(key)
                if acquired is not None:
                    client, lock_key, token = acquired
                if client is not None and not token:
                    # Another replica is loading: wait for its write, then load
                    # ourselves only if the PX guard lapsed first.
                    deadline = time.monotonic() + _LOCK_TTL_MS / 1000
                    while time.monotonic() < deadline:
                        await asyncio.sleep(_POLL_SECONDS)
                        hit = await self.aget(url, options)
                        if hit is not None:
                            return hit
                        if not await client.exists(lock_key):
                            break
                try:
                    data = await loader()
                    await self.aset(url, data, options, ttl=ttl)
                    return data
                finally:
                    if client is not None and token:
                        await self._release_cross_replica(client, lock_key, token)
        finally:
            self._release_flight_lock(key, entry)

    # ── L2 writes from the synchronous path ──────────────────────────────────

    def _schedule_l2_write(self, key: str, data: dict[str, Any], ttl: int) -> None:
        """Best-effort Redis write from a sync call (no loop -> L1 only)."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.create_task(self._l2_write(key, data, ttl))

    async def _l2_write(self, key: str, data: dict[str, Any], ttl: int) -> None:
        """Write one entry to Redis, degrading to memory on any failure."""
        client = await self._get_redis()
        if client is None:
            return
        try:
            await client.setex(self._redis_key(key), ttl, json.dumps(data, default=str))
        except Exception as e:  # noqa: BLE001 — a cache write must never raise
            self._drop_redis(e)

    def _schedule_l2_purge(self, url: str) -> None:
        """Best-effort Redis purge for a URL from a sync call."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.create_task(self._l2_purge_url(url))

    async def _l2_purge_url(self, url: str) -> int:
        """Delete every ``pry:cache:*`` entry whose payload is for ``url`` (SCAN)."""
        client = await self._get_redis()
        if client is None:
            return 0
        removed = 0
        try:
            async for key in client.scan_iter(match=f"{_REDIS_KEY_PREFIX}*", count=500):
                raw = await client.get(key)
                if not raw:
                    continue
                try:
                    payload = json.loads(raw)
                except (TypeError, ValueError):
                    continue
                meta = (
                    payload.get("data", {}).get("metadata", {}) if isinstance(payload, dict) else {}
                )
                if meta.get("url") == url or payload.get("url") == url:
                    await client.delete(key)
                    removed += 1
        except Exception as e:  # noqa: BLE001 — purge is best effort
            self._drop_redis(e)
        return removed

    async def close(self) -> None:
        """Close the Redis connection on shutdown. Safe to call repeatedly."""
        if self._redis is not None:
            with contextlib.suppress(Exception):  # best-effort close
                await self._redis.aclose()
            self._redis = None
