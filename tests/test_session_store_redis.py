# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Integration tests for :class:`pry_mcp.session_store.RedisSessionStore`.

The Redis-backed store is the production session backend and its ``exists()``
is the most-called persistent function in the service, yet the existing
integration suite only covered ``session_scope`` (postgres) and ``jobqueue``
(redis) — never the session store itself.

These tests pin the three properties the class actually promises:

* sessions are shared across replicas (a second store instance sees them),
* the key TTL is refreshed on every ``add`` so idle deployments expire,
* every operation degrades to an in-memory fallback when Redis is
  unavailable, because a Redis outage must not take the MCP endpoint down.

Marked ``integration``; deselected from the default run and executed by the
nightly Forgejo job, which provides ``PRY_REDIS_URL``.
"""

from __future__ import annotations

import os
import uuid

import pytest

from pry_mcp.session_store import SESSION_KEY, RedisSessionStore

pytestmark = pytest.mark.integration

_TTL = 300


def _url() -> str:
    return os.environ.get("PRY_REDIS_URL", "redis://127.0.0.1:6379/0")


@pytest.fixture
def store() -> RedisSessionStore:
    return RedisSessionStore(_url(), ttl_seconds=_TTL)


async def _cleanup(store: RedisSessionStore) -> None:
    if await store._ping_ok():
        await store._client.delete(SESSION_KEY)


@pytest.mark.asyncio
async def test_add_then_exists_roundtrip(store: RedisSessionStore) -> None:
    session = f"s-{uuid.uuid4()}"
    await _cleanup(store)
    try:
        assert await store.exists(session) is False
        await store.add(session)
        assert await store.exists(session) is True
        await store.remove(session)
        assert await store.exists(session) is False
    finally:
        await _cleanup(store)


@pytest.mark.asyncio
async def test_sessions_are_shared_across_replicas(store: RedisSessionStore) -> None:
    """The docstring's core claim: a second instance must observe the write."""
    session = f"s-{uuid.uuid4()}"
    await _cleanup(store)
    try:
        await store.add(session)
        replica = RedisSessionStore(_url(), ttl_seconds=_TTL)
        assert await replica.exists(session) is True, "session did not cross instances"
    finally:
        await _cleanup(store)


@pytest.mark.asyncio
async def test_add_refreshes_key_ttl(store: RedisSessionStore) -> None:
    """Idle deployments must expire, so every add re-arms the TTL."""
    await _cleanup(store)
    try:
        await store.add(f"s-{uuid.uuid4()}")
        ttl = await store._client.ttl(SESSION_KEY)
        assert 0 < ttl <= _TTL, f"expected a positive TTL <= {_TTL}, got {ttl}"
    finally:
        await _cleanup(store)


@pytest.mark.asyncio
async def test_clear_removes_every_session(store: RedisSessionStore) -> None:
    await _cleanup(store)
    try:
        await store.add(f"s-{uuid.uuid4()}")
        await store.clear()
        assert await store._client.exists(SESSION_KEY) == 0
    finally:
        await _cleanup(store)


@pytest.mark.asyncio
async def test_operations_degrade_when_redis_is_down() -> None:
    """A Redis outage must not take the MCP endpoint down."""
    unreachable = RedisSessionStore("redis://127.0.0.1:6399/0", ttl_seconds=_TTL)
    assert await unreachable._ping_ok() is False
    session = f"s-{uuid.uuid4()}"
    await unreachable.add(session)
    assert await unreachable.exists(session) is True, "fallback lost the write"
    await unreachable.remove(session)
    assert await unreachable.exists(session) is False
