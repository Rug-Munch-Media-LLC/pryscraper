# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Cache must not swallow a real failure into a plausible success.

Two signals that used to be indistinguishable from a healthy outcome:

1. A settings-resolution error returned ``""`` — identical to "Redis not
   configured" — silently pinning the process to memory-only.
2. An undecodable Redis entry was reported as a plain cache miss, hiding a
   poisoned L2 record behind an ordinary "nothing cached" answer.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

import pytest

from pry.core.cache import ResponseCache

if TYPE_CHECKING:
    from collections.abc import Iterator


@contextmanager
def _swap(obj: Any, name: str, value: Any) -> Iterator[None]:
    """Temporarily rebind ``obj.name``, restoring the original on exit."""
    had = hasattr(obj, name)
    original = getattr(obj, name, None)
    setattr(obj, name, value)
    try:
        yield
    finally:
        if had:
            setattr(obj, name, original)
        else:
            delattr(obj, name)


class _NoRedisURL:
    """Settings double whose redis_url cannot be read."""


class _BadRedisURL:
    """Settings double whose redis_url is structurally invalid."""

    @property
    def redis_url(self) -> str:
        raise ValueError("redis_url is not a string")


class _EmptyRedisURL:
    """Settings double for the genuine "Redis deliberately off" case."""

    redis_url = ""


@pytest.mark.parametrize("broken", [_NoRedisURL, _BadRedisURL])
def test_redis_url_resolution_failure_is_not_reported_as_unconfigured(broken: type) -> None:
    import pry.core.settings as settings_mod

    with _swap(settings_mod, "settings", broken()):
        c = ResponseCache(capacity=1)
        with pytest.raises((AttributeError, TypeError, ValueError)):
            c._redis_url()


def test_unconfigured_redis_backend_still_reports_empty_url() -> None:
    """The genuine "Redis off" case must still return "" — no false alarm."""
    import pry.core.settings as settings_mod

    with _swap(settings_mod, "settings", _EmptyRedisURL()):
        assert ResponseCache(capacity=1)._redis_url() == ""


def test_injected_backend_url_is_used_verbatim() -> None:
    assert ResponseCache(capacity=1, redis_backend="redis://h:6379/0")._redis_url() == (
        "redis://h:6379/0"
    )


class _PoisonedRedis:
    """Redis double holding an undecodable payload."""

    def __init__(self) -> None:
        self.deleted: list[str] = []

    async def get(self, _key: str) -> bytes:
        return b"{not-json"

    async def delete(self, key: str) -> int:
        self.deleted.append(key)
        return 1


@pytest.mark.asyncio
async def test_undecodable_redis_entry_is_reported_not_hidden_as_miss(
    caplog: pytest.LogCaptureFixture,
) -> None:
    c = ResponseCache(capacity=10)
    redis = _PoisonedRedis()
    # A pre-set client short-circuits _get_redis: no network, no config read.
    c._redis = redis

    with caplog.at_level(logging.ERROR, logger="pry.core.cache"):
        result = await c.aget("https://poisoned.example.com")

    # The read still degrades to a miss (availability preserved) ...
    assert result is None
    # ... but the poisoned record is surfaced AND evicted, never silently missed.
    assert "response_cache_redis_entry_undecodable" in caplog.text
    expected = [c._redis_key(c._key("https://poisoned.example.com"))]
    assert redis.deleted == expected
    # A miss must not poison L1.
    assert c.get("https://poisoned.example.com") is None
