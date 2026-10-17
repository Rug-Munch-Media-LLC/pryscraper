"""MCP session store — backend selection and in-memory fallback.

Streamable HTTP session ids were previously held in a process-local set
(``_MCP_SESSIONS``), which broke horizontal scaling: a second replica
answered 404 for sessions created on the first. Session state now sits
behind a small store interface:

* :class:`RedisSessionStore` — one Redis key per session
  (``pry:mcp:sess:<id>``) with its OWN TTL, plus the ``pry:mcp:sessions``
  index used for listing. Per-key TTLs are the fix for the old single-SET
  shape: ``EXPIRE`` re-armed the whole set on every ``add``, so a session
  created three days ago never died while new sessions kept arriving.
  Implemented in :mod:`pry_mcp.session_redis` and re-exported here.
* :class:`InMemorySessionStore` — the previous behavior, used for
  single-process self-hosted deployments and as a per-request fallback
  when Redis is unavailable.

The factory :func:`get_session_store` picks Redis when configured and
reachable, otherwise falls back to in-memory with a warning. Redis
failures never crash a request: the Redis store degrades to its internal
in-memory store for that operation.

The Redis key layout (:func:`session_key`, ``SESSION_KEY``) lives in
:mod:`pry_mcp.session_redis` — it is Redis-specific — and is re-exported
here for existing callers.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

import logging
import os
import time
from typing import Protocol

from pry_mcp import session_redis as _session_redis
from pry_mcp.session_redis import RedisSessionStore  # noqa: F401

logger = logging.getLogger(__name__)

# The Redis key layout lives in session_redis; re-export it here so callers
# keep importing ``session_key`` / ``SESSION_KEY`` from this module.
SESSION_KEY = _session_redis.SESSION_KEY
SESSION_KEY_PREFIX = _session_redis.SESSION_KEY_PREFIX
DEFAULT_SESSION_TTL_SECONDS = _session_redis.DEFAULT_SESSION_TTL_SECONDS
session_key = _session_redis.session_key


class SessionStore(Protocol):
    """Minimal session-id store interface (async, uniform across backends)."""

    async def add(self, session_id: str) -> None: ...
    async def exists(self, session_id: str) -> bool: ...
    async def remove(self, session_id: str) -> None: ...
    async def clear(self) -> None: ...
    async def list_sessions(self) -> list[str]: ...


class InMemorySessionStore:
    """Process-local session store with per-session TTL expiry.

    Backed by a ``dict[str, float]`` mapping session id → monotonic expiry.
    Expired ids are pruned lazily on access. This is the single-process
    fallback and matches the previous ``set[str]`` behavior when TTLs are
    not a concern.
    """

    def __init__(self, ttl_seconds: int | None = None) -> None:
        self._ttl = ttl_seconds if ttl_seconds is not None else _session_redis._session_ttl()
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

    async def list_sessions(self) -> list[str]:
        """Live session ids (expired entries pruned first)."""
        self._prune()
        return list(self._sessions)


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
        candidate = _session_redis.RedisSessionStore(url)
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
