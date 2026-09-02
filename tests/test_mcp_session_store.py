"""Tests for pry_mcp.session_store — Redis-backed MCP session state.

Covers: in-memory add/exists/remove, Redis-backed operations (mocked
redis.asyncio client), TTL expiry, factory selection (Redis when
``PRY_REDIS_URL`` is set and reachable, in-memory otherwise), graceful
Redis-failure fallback, and cross-replica visibility (the reason this
store exists).
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pry_mcp.session_store import (
    SESSION_KEY,
    InMemorySessionStore,
    RedisSessionStore,
    get_session_store,
    reset_session_store,
)


@pytest.fixture(autouse=True)
def _fresh_store(monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolate store resolution per test (no Redis URL, fresh cache)."""
    monkeypatch.delenv("PRY_REDIS_URL", raising=False)
    monkeypatch.delenv("MCP_SESSION_TTL_SECONDS", raising=False)
    reset_session_store()
    yield
    reset_session_store()


# ── In-memory store ────────────────────────────────────────────────────────


class TestInMemorySessionStore:
    async def test_add_exists_remove(self) -> None:
        store = InMemorySessionStore()
        assert not await store.exists("s1")
        await store.add("s1")
        assert await store.exists("s1")
        await store.remove("s1")
        assert not await store.exists("s1")

    async def test_remove_unknown_is_noop(self) -> None:
        store = InMemorySessionStore()
        await store.remove("never-added")  # must not raise

    async def test_ttl_expiry(self, monkeypatch: pytest.MonkeyPatch) -> None:
        store = InMemorySessionStore(ttl_seconds=60)
        await store.add("s1")
        assert await store.exists("s1")
        # Age the entry past its TTL by shifting the clock.
        real_monotonic = time.monotonic
        monkeypatch.setattr("pry_mcp.session_store.time.monotonic", lambda: real_monotonic() + 120)
        assert not await store.exists("s1")

    async def test_ttl_configurable_via_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MCP_SESSION_TTL_SECONDS", "90")
        store = InMemorySessionStore()
        assert store._ttl == 90

    async def test_ttl_env_invalid_falls_back_to_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("MCP_SESSION_TTL_SECONDS", "not-a-number")
        assert InMemorySessionStore()._ttl == 3600


# ── Redis store (mocked redis.asyncio client) ──────────────────────────────


def _fake_redis_client() -> tuple[MagicMock, dict[str, Any]]:
    """Build a mock redis.asyncio client with a real backing set."""
    backing: set[str] = set()
    client = MagicMock()

    async def _ping() -> bool:
        return True

    async def _sadd(key: str, member: str) -> int:
        backing.add(member)
        return 1

    async def _sismember(key: str, member: str) -> bool:
        return member in backing

    async def _srem(key: str, member: str) -> int:
        backing.discard(member)
        return 1

    async def _delete(key: str) -> int:
        n = len(backing)
        backing.clear()
        return n

    client.ping = AsyncMock(side_effect=_ping)
    client.sadd = AsyncMock(side_effect=_sadd)
    client.sismember = AsyncMock(side_effect=_sismember)
    client.srem = AsyncMock(side_effect=_srem)
    client.delete = AsyncMock(side_effect=_delete)
    client.expire = AsyncMock(return_value=True)
    # Pipeline records ops and applies them to the backing set on execute.
    ops: list[tuple[str, tuple[Any, ...]]] = []
    pipe = MagicMock()
    pipe.sadd = MagicMock(side_effect=lambda *a: ops.append(("sadd", a)))
    pipe.expire = MagicMock(side_effect=lambda *a: ops.append(("expire", a)))

    async def _execute() -> list[Any]:
        results: list[Any] = []
        for op, args in ops:
            if op == "sadd":
                backing.add(args[1])
                results.append(1)
            else:  # expire
                results.append(True)
        ops.clear()
        return results

    pipe.execute = AsyncMock(side_effect=_execute)
    client.pipeline = MagicMock(return_value=pipe)
    return client, backing


def _redis_store_with(client: MagicMock) -> RedisSessionStore:
    with patch("redis.asyncio.Redis.from_url", return_value=client):
        return RedisSessionStore("redis://test:6379/0")


class TestRedisSessionStore:
    async def test_add_exists_remove(self) -> None:
        client, backing = _fake_redis_client()
        store = _redis_store_with(client)
        assert not await store.exists("s1")
        await store.add("s1")
        assert "s1" in backing
        assert await store.exists("s1")
        await store.remove("s1")
        assert not await store.exists("s1")

    async def test_add_refreshes_ttl(self) -> None:
        client, _ = _fake_redis_client()
        store = _redis_store_with(client)
        await store.add("s1")
        client.pipeline.return_value.expire.assert_called_with(SESSION_KEY, 3600)

    async def test_ttl_configurable_via_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MCP_SESSION_TTL_SECONDS", "120")
        client, _ = _fake_redis_client()
        store = _redis_store_with(client)
        await store.add("s1")
        client.pipeline.return_value.expire.assert_called_with(SESSION_KEY, 120)

    async def test_redis_failure_falls_back_to_memory(self) -> None:
        client, _ = _fake_redis_client()
        client.ping = AsyncMock(side_effect=ConnectionError("redis down"))
        store = _redis_store_with(client)
        # Every op degrades to the internal in-memory store, no crash.
        await store.add("s1")
        assert await store.exists("s1")
        await store.remove("s1")
        assert not await store.exists("s1")

    async def test_exists_failure_falls_back_to_memory(self) -> None:
        client, _ = _fake_redis_client()
        store = _redis_store_with(client)
        # Seed the fallback while Redis is down, then Redis dies mid-exists.
        client.ping = AsyncMock(side_effect=ConnectionError("redis down"))
        await store.add("s1")  # lands in the internal memory fallback
        client.ping = AsyncMock(return_value=True)
        client.sismember = AsyncMock(side_effect=ConnectionError("redis down"))
        assert await store.exists("s1") is True  # served from memory fallback

    async def test_cross_replica_visibility(self) -> None:
        """Two store instances over the same Redis see each other's sessions."""
        client, _ = _fake_redis_client()
        replica_a = _redis_store_with(client)
        replica_b = _redis_store_with(client)
        await replica_a.add("shared-session")
        assert await replica_b.exists("shared-session")
        await replica_b.remove("shared-session")
        assert not await replica_a.exists("shared-session")


# ── Factory ────────────────────────────────────────────────────────────────


class TestSessionFactory:
    async def test_memory_when_no_url(self) -> None:
        store = await get_session_store()
        assert isinstance(store, InMemorySessionStore)

    async def test_redis_when_url_set_and_reachable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client, _ = _fake_redis_client()
        monkeypatch.setenv("PRY_REDIS_URL", "redis://test:6379/0")
        with patch("redis.asyncio.Redis.from_url", return_value=client):
            store = await get_session_store()
        assert isinstance(store, RedisSessionStore)

    async def test_falls_back_when_redis_unreachable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PRY_REDIS_URL", "redis://test:6379/0")
        client, _ = _fake_redis_client()
        client.ping = AsyncMock(side_effect=ConnectionError("redis down"))
        with patch("redis.asyncio.Redis.from_url", return_value=client):
            store = await get_session_store()
        assert isinstance(store, InMemorySessionStore)

    async def test_factory_result_is_cached(self) -> None:
        first = await get_session_store()
        second = await get_session_store()
        assert first is second


# ── App integration: cross-replica visibility through the endpoint ─────────


class TestAppSessionStoreIntegration:
    async def test_initialize_then_post_roundtrip_uses_store(self) -> None:
        """initialize issues a session id that the store reports as existing."""
        from pry_mcp.session_store import get_memory_store, reset_session_store

        reset_session_store()
        store = await get_session_store()
        memory = get_memory_store()
        memory._sessions.clear()
        await store.add("abc123")
        assert await store.exists("abc123")
        assert "abc123" in memory._sessions
        await store.remove("abc123")
        assert "abc123" not in memory._sessions
