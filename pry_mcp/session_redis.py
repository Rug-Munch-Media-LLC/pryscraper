"""Redis-backed MCP session storage.

Owns the Redis key layout and :class:`RedisSessionStore`. It lives apart from
:mod:`pry_mcp.session_store` so each module has one responsibility: here the
Redis implementation, there the protocol, the in-memory fallback and backend
selection. ``session_store`` re-exports :class:`RedisSessionStore` and the key
helpers, so existing imports keep working.

Import direction: this module imports ``session_store`` only for the
``InMemorySessionStore`` fallback, lazily inside ``RedisSessionStore.__init__``.
A module-level import back would be circular — ``session_store`` imports this
module for the re-export — and ``SessionStore`` is a typing-only import.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pry_mcp.session_store import SessionStore

logger = logging.getLogger(__name__)

#: Index set of live session ids (listing only — liveness is the per-key TTL).
SESSION_KEY = "pry:mcp:sessions"
#: One key per session; this key's TTL is that session's lifetime.
SESSION_KEY_PREFIX = "pry:mcp:sess:"
DEFAULT_SESSION_TTL_SECONDS = 3600


def session_key(session_id: str) -> str:
    """Redis key holding one session (its TTL is the session lifetime)."""
    return f"{SESSION_KEY_PREFIX}{session_id}"


def _session_ttl() -> int:
    """Configured session TTL in seconds (``MCP_SESSION_TTL_SECONDS``)."""
    raw = os.getenv("MCP_SESSION_TTL_SECONDS", "")
    try:
        ttl = int(raw)
    except ValueError as e:
        logger.warning(
            "suppressed %s in _session_ttl (session_redis.py): %s",
            "ValueError",
            e,
        )
        return DEFAULT_SESSION_TTL_SECONDS
    return ttl if ttl > 0 else DEFAULT_SESSION_TTL_SECONDS


class RedisSessionStore:
    """Redis SET-backed session store shared across replicas.

    All session ids live in one SET (``pry:mcp:sessions``); the key's TTL
    is refreshed on every ``add`` so idle deployments expire cleanly.
    Every operation degrades to an internal in-memory store on Redis
    failure — a Redis outage must not take the MCP endpoint down.
    """

    def __init__(self, url: str, ttl_seconds: int | None = None) -> None:
        # Local import breaks the session_store <-> session_redis cycle: the
        # fallback class is the only runtime dependency on that module.
        from pry_mcp.session_store import InMemorySessionStore

        self._ttl = ttl_seconds if ttl_seconds is not None else _session_ttl()
        self._fallback: SessionStore = InMemorySessionStore(ttl_seconds=self._ttl)
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
                "suppressed %s in _ping_ok (session_redis.py): %s",
                "Exception",
                e,
            )
            return False

    async def add(self, session_id: str) -> None:
        """Create/refresh ONE session key; its TTL is that session's lifetime.

        The index TTL is refreshed too (listing only), but it can never extend
        another session's life: each session key expires on its own clock.
        """
        if await self._ping_ok():
            try:
                pipe = self._client.pipeline()
                # A 1-member SET keeps the sadd/sismember contract; the point
                # is the per-key EXPIRE, not the container type.
                pipe.sadd(session_key(session_id), session_id)
                pipe.expire(session_key(session_id), self._ttl)
                pipe.sadd(SESSION_KEY, session_id)
                pipe.expire(SESSION_KEY, self._ttl)
                await pipe.execute()
                return
            except Exception:  # noqa: BLE001 — Redis down → fallback
                logger.warning("mcp_session_redis_unavailable")
        await self._fallback.add(session_id)

    async def exists(self, session_id: str) -> bool:
        """True only while THAT session's own key is alive."""
        if await self._ping_ok():
            try:
                return bool(await self._client.sismember(session_key(session_id), session_id))
            except Exception:  # noqa: BLE001 — Redis down → fallback
                logger.warning("mcp_session_redis_unavailable")
        return await self._fallback.exists(session_id)

    async def list_sessions(self) -> list[str]:
        """Live session ids; expired index entries are pruned on read."""
        if not await self._ping_ok():
            return await self._fallback.list_sessions()
        try:
            members = await self._client.smembers(SESSION_KEY)
            live: list[str] = []
            for sid in members or []:
                if await self._client.sismember(session_key(sid), sid):
                    live.append(str(sid))
                else:
                    await self._client.srem(SESSION_KEY, sid)
            return live
        except Exception:  # noqa: BLE001 — Redis down → fallback
            logger.warning("mcp_session_redis_unavailable")
            return await self._fallback.list_sessions()

    async def remove(self, session_id: str) -> None:
        if await self._ping_ok():
            try:
                # Two commands, not a pipeline: the per-session key is what
                # governs liveness, so a partial failure still expires the
                # session on its own TTL (the index entry is pruned on read).
                await self._client.delete(session_key(session_id))
                await self._client.srem(SESSION_KEY, session_id)
                return
            except Exception:  # noqa: BLE001 — Redis down → fallback
                logger.warning("mcp_session_redis_unavailable")
        await self._fallback.remove(session_id)

    async def clear(self) -> None:
        """Drop the index and this store's session keys (SCAN, never KEYS)."""
        if await self._ping_ok():
            try:
                await self._client.delete(SESSION_KEY)
                async for key in self._client.scan_iter(match=f"{SESSION_KEY_PREFIX}*", count=500):
                    await self._client.delete(key)
                return
            except Exception:  # noqa: BLE001 — Redis down → fallback
                logger.warning("mcp_session_redis_unavailable")
        await self._fallback.clear()
