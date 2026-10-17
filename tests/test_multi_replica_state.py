# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Multi-replica correctness: cache isolation, shared quota, single-flight, TTL.

Each test pins one defect that only appears with more than one replica:

(a) cache entries never cross tenants,
(b) quota is shared, so a second replica does not get a second allowance,
(c) concurrent cold-key scrapes run the loader once,
(d) an expired session is not returned (per-session TTL, not set-wide TTL).
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import replace
from typing import Any

import pytest

from pry.commerce.billing import BillingEnforcer
from pry.commerce.billing.tiers import get_tier
from pry.core.cache import ResponseCache
from pry_mcp.session_store import RedisSessionStore

URL = "https://example.com/page"
PAGE = {"success": True, "data": {"markdown": "# hi", "metadata": {"url": URL}}}


# ── (a) tenant isolation ───────────────────────────────────────────────────


def test_two_tenant_keys_do_not_share_a_cache_entry() -> None:
    cache = ResponseCache(capacity=10, redis_backend="")
    cache.set(URL, PAGE, {"api_key": "tenant-a"})
    assert cache.get(URL, {"api_key": "tenant-b"}) is None
    assert cache.get(URL, {"api_key": "tenant-a"}) is not None


# ── (b) shared quota across replicas ───────────────────────────────────────


class _FakeSyncRedis:
    """Minimal sync Redis: INCR/DECR/EXPIRE/GET/PING over a dict."""

    def __init__(self) -> None:
        self.values: dict[str, int] = {}
        self.expiries: dict[str, int] = {}

    def ping(self) -> bool:
        return True

    def incr(self, key: str) -> int:
        self.values[key] = int(self.values.get(key, 0)) + 1
        return self.values[key]

    def decr(self, key: str) -> int:
        self.values[key] = int(self.values.get(key, 0)) - 1
        return self.values[key]

    def expire(self, key: str, ttl: int) -> bool:
        self.expiries[key] = int(ttl)
        return True

    def get(self, key: str) -> str | None:
        return str(self.values[key]) if key in self.values else None


def test_second_replica_sees_the_same_quota_count() -> None:
    shared = _FakeSyncRedis()
    tier = replace(get_tier("pro"), request_quota_monthly=2, rate_limit_rpm=None)
    replica_a = BillingEnforcer(keys_config={"sk_live": "pro"}, redis_client=shared)
    replica_b = BillingEnforcer(keys_config={"sk_live": "pro"}, redis_client=shared)

    assert replica_a.check_request("sk_live", tier) is True
    assert replica_b.check_request("sk_live", tier) is True
    # Third request lands on either replica: the ONE shared allowance is spent.
    assert replica_a.check_request("sk_live", tier) is False
    assert replica_b.check_request("sk_live", tier) is False
    # Neither replica kept a private count — the shared store is authoritative.
    assert replica_a._counters == {}
    assert replica_b._counters == {}
    # usage_stats resolves the *configured* tier (pro, 500k), so the assertion
    # here is the shared count itself: a private counter would read 0 or 1.
    assert replica_b.usage_stats("sk_live")["month_requests"] == 2


# ── (c) single-flight on a cold key ────────────────────────────────────────


@pytest.mark.asyncio
async def test_concurrent_cold_scrapes_run_the_loader_once() -> None:
    cache = ResponseCache(capacity=10, redis_backend="")
    calls: list[int] = []

    async def loader() -> dict[str, Any]:
        calls.append(1)
        await asyncio.sleep(0.05)
        return PAGE

    results = await asyncio.gather(
        *(cache.fetch_or_load(URL, {"tenant": "t1"}, loader) for _ in range(5))
    )
    expected = [1]
    assert calls == expected, f"loader ran {len(calls)} times for one cold key"
    assert all(r["data"]["markdown"] == "# hi" for r in results)
    assert cache.get(URL, {"tenant": "t1"}) is not None


# ── (d) per-session TTL ────────────────────────────────────────────────────


class _FakeAsyncRedis:
    """Per-key SETs with real TTL semantics driven by an injectable clock."""

    def __init__(self, clock: Any) -> None:
        self.clock = clock
        self.sets: dict[str, set[str]] = {}
        self.expiries: dict[str, float] = {}

    def _live(self, key: str) -> bool:
        expiry = self.expiries.get(key)
        if expiry is not None and expiry <= self.clock():
            self.sets.pop(key, None)
            self.expiries.pop(key, None)
            return False
        return True

    async def ping(self) -> bool:
        return True

    async def sadd(self, key: str, member: str) -> int:
        self.sets.setdefault(key, set()).add(member)
        return 1

    async def sismember(self, key: str, member: str) -> bool:
        return self._live(key) and member in self.sets.get(key, set())

    async def smembers(self, key: str) -> set[str]:
        return set(self.sets.get(key, set())) if self._live(key) else set()

    async def srem(self, key: str, member: str) -> int:
        self.sets.get(key, set()).discard(member)
        return 1

    async def delete(self, key: str) -> int:
        self.sets.pop(key, None)
        self.expiries.pop(key, None)
        return 1

    async def expire(self, key: str, ttl: int) -> bool:
        self.expiries[key] = self.clock() + int(ttl)
        return True

    def pipeline(self) -> Any:
        ops: list[tuple[str, str, Any]] = []
        pipe = type("Pipe", (), {})()
        pipe.sadd = lambda k, m: ops.append(("sadd", k, m)) or pipe
        pipe.delete = lambda k: ops.append(("delete", k, None)) or pipe
        pipe.srem = lambda k, m: ops.append(("srem", k, m)) or pipe
        pipe.expire = lambda k, ttl: ops.append(("expire", k, ttl)) or pipe

        async def execute() -> list[Any]:
            for op, key, arg in ops:
                if op == "sadd":
                    self.sets.setdefault(key, set()).add(arg)
                elif op == "expire":
                    self.expiries[key] = self.clock() + int(arg)
                elif op == "delete":
                    self.sets.pop(key, None)
                elif op == "srem":
                    self.sets.get(key, set()).discard(arg)
            ops.clear()
            return []

        pipe.execute = execute
        return pipe


@pytest.mark.asyncio
async def test_expired_session_is_not_returned() -> None:
    now = [time.time()]
    store = RedisSessionStore("redis://unused", ttl_seconds=5)
    store._client = _FakeAsyncRedis(lambda: now[0])

    await store.add("old-session")
    assert await store.exists("old-session") is True

    now[0] += 10  # past the session's own TTL
    # A NEW session must not revive the old one via a shared set TTL.
    await store.add("new-session")
    assert await store.exists("old-session") is False
    assert await store.exists("new-session") is True
    expected = ["new-session"]
    assert await store.list_sessions() == expected
