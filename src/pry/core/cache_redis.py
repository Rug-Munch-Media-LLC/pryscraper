"""Redis backend plumbing for the response cache.

Split out of ``cache`` so the cache's own policy — keys, TTLs, eviction, byte
budget — is readable without the connection lifecycle mixed in. Mixed in as
:class:`RedisBackendMixin`, so ``ResponseCache`` still exposes every one of
these as a method and no call site changes.

Redis is optional by design: absent, unreachable or broken and the cache
degrades to its in-process L1. A *settings* failure is not handled that way —
it raises, because an empty URL would pin the process to memory-only forever.

**Required Redis eviction policy: ``noeviction`` or a ``volatile-*`` policy.
NEVER ``allkeys-lru`` / ``allkeys-random`` / ``allkeys-lfu``.** This instance is
shared with x402 replay/nonce keys, billing counters and MCP sessions; evicting
one silently reopens a replay window or under-counts a quota.
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
import time
from typing import Any

_REDIS_KEY_PREFIX = "pry:cache:"
_REDIS_RETRY_SECONDS = 30.0
# v1 hashed url + caller options only, letting a hit cross tenants and schemas.
_KEY_VERSION = "v2"
# Any one of these pins a separate tenant namespace; absent -> shared public.
_TENANT_KEYS = ("tenant", "tenant_id", "api_key", "apikey", "caller_id", "caller", "auth")
# An extracted ``data.json`` payload caches only when one of these is in the key.
_SCHEMA_KEYS = ("json_schema", "jsonSchema", "schema", "extraction_schema", "extract_schema")
logger = logging.getLogger(__name__)


class RedisBackendMixin:
    """Connection lifecycle and key naming for the optional Redis tier.

    A connection failure drops to the in-process L1 after logging. A
    *configuration* failure raises, so a broken cache is visible immediately.
    """

    _redis_backend: Any
    _redis: Any
    _redis_failed_at: float
    backend: str

    def _redis_url(self) -> str:
        """Redis URL, or ``""`` only when Redis is genuinely not configured."""
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

    # ── Single-flight loads (machinery lives in ``core.singleflight``) ───────

    async def fetch_or_load(self, url, options, loader, ttl=300):
        """One loader run per cold key, process- and cluster-wide."""
        from pry.core.singleflight import fetch_or_load as _f

        return await _f(self, url, options, loader, ttl)

    def _schedule(self, coro: Any) -> None:
        """Run a best-effort Redis task when a loop is running (else L1 only)."""
        try:
            asyncio.get_running_loop().create_task(coro)
        except RuntimeError:
            coro.close()

    async def _l2_write(self, key: str, data: dict[str, Any], ttl: int) -> None:
        """Write one entry to Redis, degrading to memory on any failure."""
        client = await self._get_redis()
        if client is None:
            return
        try:
            await client.setex(self._redis_key(key), ttl, json.dumps(data, default=str))
        except Exception as e:  # noqa: BLE001 — a cache write must never raise
            self._drop_redis(e)

    def _schedule_l2_write(self, key: str, data: dict[str, Any], ttl: int) -> None:
        """Best-effort Redis write from a sync call."""
        self._schedule(self._l2_write(key, data, ttl))

    def _schedule_l2_purge(self, url: str) -> None:
        """Best-effort Redis purge for a URL from a sync call."""
        self._schedule(self._l2_purge_url(url))

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
