# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
import time

import pytest

from pry.core.cache import ResponseCache


def test_cache_set_and_get() -> None:
    c = ResponseCache(capacity=100)
    c.set("https://example.com", {"content": "hello"})
    hit = c.get("https://example.com")
    assert hit is not None
    assert hit["content"] == "hello"


def test_cache_miss() -> None:
    c = ResponseCache(capacity=100)
    miss = c.get("https://unknown.com")
    assert miss is None


def test_cache_expiry() -> None:
    c = ResponseCache(capacity=100)
    c.set("https://example.com", {"content": "hello"}, ttl=0)
    time.sleep(0.01)
    miss = c.get("https://example.com")
    assert miss is None


def test_cache_eviction() -> None:
    c = ResponseCache(capacity=2)
    c.set("https://a.com", {"content": "a"})
    c.set("https://b.com", {"content": "b"})
    c.set("https://c.com", {"content": "c"})
    assert c.get("https://a.com") is None
    assert c.get("https://b.com") is not None
    assert c.get("https://c.com") is not None


def test_cache_stats() -> None:
    c = ResponseCache(capacity=50)
    c.get("https://miss.com")
    c.get("https://miss2.com")
    c.set("https://hit.com", {"data": 1})
    c.get("https://hit.com")
    stats = c.stats()
    assert stats["hits"] == 1
    assert stats["misses"] == 2
    assert stats["hit_rate"] > 0


def test_cache_invalidate() -> None:
    c = ResponseCache(capacity=100)
    c.set("https://example.com", {"data": 1, "url": "https://example.com"})
    c.invalidate("https://example.com")
    assert c.get("https://example.com") is None


def test_cache_clear() -> None:
    c = ResponseCache(capacity=100)
    c.set("https://a.com", {"data": 1})
    c.set("https://b.com", {"data": 2})
    c.clear()
    assert c.stats()["size"] == 0
    assert c.stats()["hits"] == 0


# ---------------------------------------------------------------------------
# Async read-through cache path (aget / aset)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_async_cache_set_and_get() -> None:
    c = ResponseCache(capacity=10)
    data = {"content": "hello", "url": "https://example.com"}
    await c.aset("https://example.com", data)
    hit = await c.aget("https://example.com")
    assert hit is not None
    assert hit["content"] == "hello"


@pytest.mark.asyncio
async def test_async_cache_miss() -> None:
    c = ResponseCache(capacity=10)
    miss = await c.aget("https://nonexistent.com")
    assert miss is None


@pytest.mark.asyncio
async def test_async_cache_invalidate() -> None:
    c = ResponseCache(capacity=10)
    data = {"data": 1, "url": "https://example.com"}
    await c.aset("https://example.com", data)
    assert await c.aget("https://example.com") is not None
    c.invalidate("https://example.com")
    assert await c.aget("https://example.com") is None


@pytest.mark.asyncio
async def test_async_cache_with_options() -> None:
    c = ResponseCache(capacity=10)
    options = {"headers": {"Accept": "application/json"}}
    data = {"content": "json", "url": "https://example.com"}
    await c.aset("https://example.com", data, options=options)
    hit = await c.aget("https://example.com", options=options)
    assert hit is not None
    assert hit["content"] == "json"
