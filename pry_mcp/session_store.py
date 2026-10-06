"""MCP session store — Redis-backed with in-memory fallback.

Streamable HTTP session ids were previously held in a process-local set
(``_MCP_SESSIONS``), which broke horizontal scaling: a second replica
answered 404 for sessions created on the first. This module moves session
state behind a small store interface:

* :class:`RedisSessionStore` — a Redis SET with a TTL, shared by all
  replicas (enabled when ``PRY_REDIS_URL`` is set and reachable).
* :class:`InMemorySessionStore` — the previous behavior, used for
  single-process self-hosted deployments and as a per-request fallback
  when Redis is unavailable.

The factory :func:`get_session_store` picks Redis when configured and
reachable, otherwise falls back to in-memory with a warning. Redis
failures never crash a request: the Redis store degrades to its internal
in-memory store for that operation.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

import logging
import os
import time
from typing import Any, Protocol

logger = logging.getLogger(__name__)

SESSION_KEY = "pry:mcp:sessions"
DEFAULT_SESSION_TTL_SECONDS = 3600


def _session_ttl() -> int:
    """Configured session TTL in seconds (``MCP_SESSION_TTL_SECONDS``)."""
    raw = os.getenv("MCP_SESSION_TTL_SECONDS", "")
    try:
        ttl = int(raw)
    except ValueError as e:
        logger.warning(
            "suppressed %s in _session_ttl (session_store.py:42): %s",
            "ValueError",
            e,
        )
        return DEFAULT_SESSION_TTL_SECONDS
    return ttl if ttl > 0 else DEFAULT_SESSION_TTL_SECONDS


class SessionStore(Protocol):
    """Minimal session-id store interface (async, uniform across backends)."""

    async def add(self, session_id: str) -> None: ...
    async def exists(self, session_id: str) -> bool: ...
    async def remove(self, session_id: str) -> None: ...
    async def clear(self) -> None: ...


class InMemorySessionStore:
    """Process-local session store with per-session TTL expiry.

    Backed by a ``dict[str, float]`` mapping session id → monotonic expiry.
    Expired ids are pruned lazily on access. This is the single-process
    fallback and matches the previous ``set[str]`` behavior when TTLs are
    not a concern.
    """

    def __init__(self, ttl_seconds: int | None = None) -> None:
        self._ttl = ttl_seconds if ttl_seconds is not None else _session_ttl()
        self._sessions: dict[str, float] = {}

    def _prune(self) -> None:
        now = time.monotonic()
        expired = [sid for sid, exp in self._sessions.items() if exp <= now]
        for sid in expired:
            del self._sessions[sid]

    async def add(self, session_id: str) -> None:
        self._prune()
        self._sessions[session_id] = time.monotonic() + self._ttl

    async def exists(self, session_id: str) -> bool:
        self._prune()
        return session_id in self._sessions

    async def remove(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    async def clear(self) -> None:
        self._sessions.clear()


class RedisSessionStore:
    """Redis SET-backed session store shared across replicas.

    All session ids live in one SET (``pry:mcp:sessions``); the key's TTL
    is refreshed on every ``add`` so idle deployments expire cleanly.
    Every operation degrades to an internal in-memory store on Redis
    failure — a Redis outage must not take the MCP endpoint down.
    """

    def __init__(self, url: str, ttl_seconds: int | None = None) -> None:
        self._ttl = ttl_seconds if ttl_seconds is not None else _session_ttl()
        self._fallback = InMemorySessionStore(ttl_seconds=self._ttl)
        self._client: Any = None
        try:
            import redis.asyncio as aioredis

            self._client = aioredis.Redis.from_url(url, socket_timeout=2, decode_responses=True)
        except Exception:  # noqa: BLE001 — construction failure → memory fallback
            logger.warning("mcp_session_redis_init_failed")
            self._client = None

    async def _ping_ok(self) -> bool:
        """True when the Redis client is present and answers PING."""
        if self._client is None:
            return False
        try:
            return bool(await self._client.ping())
        except Exception as e:  # noqa: BLE001 — Redis down → fallback
            logger.warning(
                "suppressed %s in _ping_ok (session_store.py:117): %s",
                "Exception",
                e,
            )
            return False

    async def add(self, session_id: str) -> None:
        if await self._ping_ok():
            try:
                pipe = self._client.pipeline()
                pipe.sadd(SESSION_KEY, session_id)
                pipe.expire(SESSION_KEY, self._ttl)
                await pipe.execute()
                return
            except Exception:  # noqa: BLE001 — Redis down → fallback
                logger.warning("mcp_session_redis_unavailable")
        await self._fallback.add(session_id)

    async def exists(self, session_id: str) -> bool:
        if await self._ping_ok():
            try:
                return bool(await self._client.sismember(SESSION_KEY, session_id))
            except Exception:  # noqa: BLE001 — Redis down → fallback
                logger.warning("mcp_session_redis_unavailable")
        return await self._fallback.exists(session_id)

    async def remove(self, session_id: str) -> None:
        if await self._ping_ok():
            try:
                await self._client.srem(SESSION_KEY, session_id)
                return
            except Exception:  # noqa: BLE001 — Redis down → fallback
                logger.warning("mcp_session_redis_unavailable")
        await self._fallback.remove(session_id)

    async def clear(self) -> None:
        if await self._ping_ok():
            try:
                await self._client.delete(SESSION_KEY)
                return
            except Exception:  # noqa: BLE001 — Redis down → fallback
                logger.warning("mcp_session_redis_unavailable")
        await self._fallback.clear()


_store: SessionStore | None = None
_memory_store: InMemorySessionStore | None = None


def get_memory_store() -> InMemorySessionStore:
    """Return the process-cached in-memory store (legacy alias target)."""
    global _memory_store
    if _memory_store is None:
        _memory_store = InMemorySessionStore()
    return _memory_store


async def get_session_store() -> SessionStore:
    """Return the process-wide session store.

    Redis is used when ``PRY_REDIS_URL`` is set and the server answers a
    PING; otherwise (unset, unreachable, or import failure) the in-memory
    store is returned with a warning. The choice is cached for the
    process lifetime; per-request Redis failures still degrade gracefully
    inside :class:`RedisSessionStore`.
    """
    global _store
    if _store is not None:
        return _store
    url = os.getenv("PRY_REDIS_URL", "")
    if url:
        candidate = RedisSessionStore(url)
        if await candidate._ping_ok():
            _store = candidate
            logger.info("mcp_session_store=redis")
            return _store
        logger.warning("mcp_session_store=memory (Redis unreachable at %s)", url)
    else:
        logger.warning("mcp_session_store=memory (PRY_REDIS_URL not set)")
    _store = get_memory_store()
    return _store


def reset_session_store() -> None:
    """Drop the cached store (test hook — next call re-resolves)."""
    global _store, _memory_store
    _store = None
    _memory_store = None
