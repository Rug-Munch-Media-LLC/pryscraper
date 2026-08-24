# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for the generic fallback-chain framework (``fallback.py``).

Covers ``fetch_with_fallback`` chain semantics (first-fail -> second-returns,
all-fail -> last result, success short-circuit, sync + async fetchers, never
raises), ``with_fallback`` composition, and per-fetcher status tracking via
``fallback_status`` (success / failed / blocked / latency).

Synthetic fetchers only — no live network.
"""

from __future__ import annotations

from typing import Any

import pytest

from pry.engine.fallback import (
    BlockedError,
    fallback_status,
    fetch_with_fallback,
    reset_status,
    with_fallback,
)


@pytest.fixture(autouse=True)
def _clean_status() -> Any:
    """Hermetic health registry per test (mirrors fallback_telemetry.reset)."""
    reset_status()
    yield
    reset_status()


def _empty() -> None:
    return None


async def _async_empty() -> None:
    return None


async def _async_value(value: Any = "ok") -> Any:
    return value


def _raising(msg: str = "boom") -> Any:
    raise RuntimeError(msg)


# ── chain semantics ────────────────────────────────────────────────────


async def test_first_fetcher_fails_second_returns() -> None:
    result = await fetch_with_fallback([_empty, _async_value])
    assert result == "ok"


async def test_sync_and_async_fetchers_mix() -> None:
    async def _second() -> Any:
        return [1, 2, 3]

    result = await fetch_with_fallback([_empty, _second])
    assert result == [1, 2, 3]


async def test_first_fetcher_raises_second_returns() -> None:
    result = await fetch_with_fallback([_raising, _async_value])
    assert result == "ok"


async def test_blocked_fetcher_continues_chain() -> None:
    def _blocked() -> Any:
        raise BlockedError("captcha wall")

    result = await fetch_with_fallback([_blocked, _async_value])
    assert result == "ok"


async def test_all_fail_returns_last_result() -> None:
    async def _last() -> None:
        return None

    result = await fetch_with_fallback([_empty, _async_empty, _last])
    assert result is None


async def test_all_fail_returns_last_empty_list() -> None:
    async def _empty_list() -> list[Any]:
        return []

    result = await fetch_with_fallback([_empty, _empty_list])
    assert result == []


async def test_all_fail_returns_last_empty_dict() -> None:
    async def _empty_dict() -> dict[str, Any]:
        return {}

    result = await fetch_with_fallback([_empty, _empty_dict])
    assert result == {}


async def test_success_short_circuits() -> None:
    calls: list[str] = []

    async def _first() -> Any:
        calls.append("first")
        return "data"

    async def _second() -> Any:
        calls.append("second")
        return "second-data"

    result = await fetch_with_fallback([_first, _second])
    assert result == "data"
    assert calls == ["first"], "second fetcher must not run after a success"


async def test_empty_fetcher_list_returns_none() -> None:
    assert await fetch_with_fallback([]) is None


async def test_never_raises_on_fetcher_exception() -> None:
    result = await fetch_with_fallback([_raising, _raising])
    assert result is None


async def test_args_kwargs_forwarded_to_each_fetcher() -> None:
    seen: list[tuple[Any, ...]] = []

    async def _first(*args: Any, **kwargs: Any) -> None:
        seen.append((args, kwargs))
        return None

    async def _second(*args: Any, **kwargs: Any) -> Any:
        seen.append((args, kwargs))
        return kwargs.get("query")

    result = await fetch_with_fallback([_first, _second], "x", query="btc")
    assert result == "btc"
    assert seen[0] == (("x",), {"query": "btc"})
    assert seen[1] == (("x",), {"query": "btc"})


# ── with_fallback composition ──────────────────────────────────────────


async def test_with_fallback_returns_first_success() -> None:
    composed = with_fallback(_empty, _async_value)
    assert await composed() == "ok"


async def test_with_fallback_all_fail_returns_last() -> None:
    async def _last() -> None:
        return None

    composed = with_fallback(_empty, _async_empty, _last)
    assert await composed() is None


async def test_with_fallback_never_raises() -> None:
    composed = with_fallback(_raising, _raising)
    assert await composed() is None


# ── status tracking ────────────────────────────────────────────────────


async def test_status_tracks_success_and_latency() -> None:
    await fetch_with_fallback([_async_value])
    status = fallback_status([_async_value])
    entry = status["_async_value:0"]
    assert entry["status"] == "success"
    assert entry["reachable"] is True
    assert entry["blocked"] is False
    assert entry["latency_ms"] is not None
    assert entry["latency_ms"] >= 0
    assert entry["error"] is None


async def test_status_tracks_failure() -> None:
    await fetch_with_fallback([_raising])
    entry = fallback_status([_raising])["_raising:0"]
    assert entry["status"] == "failed"
    assert entry["reachable"] is False
    assert entry["blocked"] is False
    assert entry["error"] is not None


async def test_status_tracks_blocked() -> None:
    def _blocked() -> Any:
        raise BlockedError("access denied")

    await fetch_with_fallback([_blocked])
    entry = fallback_status([_blocked])["_blocked:0"]
    assert entry["status"] == "blocked"
    assert entry["blocked"] is True
    assert entry["reachable"] is False


async def test_status_untried_before_any_attempt() -> None:
    entry = fallback_status([_async_value])["_async_value:0"]
    assert entry["status"] == "untried"
    assert entry["last_checked"] is None


async def test_status_all_fetchers_reported() -> None:
    await fetch_with_fallback([_empty, _async_value])
    status = fallback_status([_empty, _async_value])
    assert "_empty:0" in status
    assert "_async_value:1" in status


async def test_status_never_raises_for_unknown() -> None:
    status = fallback_status([])
    assert status == {}


# ── truthiness edge cases ──────────────────────────────────────────────


async def test_falsy_zero_continues_chain() -> None:
    async def _zero() -> Any:
        return 0

    result = await fetch_with_fallback([_zero, _async_value])
    assert result == "ok"


async def test_empty_string_continues_chain() -> None:
    async def _blank() -> str:
        return ""

    result = await fetch_with_fallback([_blank, _async_value])
    assert result == "ok"


@pytest.mark.parametrize("value", ["data", 1, True, [1], {"a": 1}])
async def test_truthy_result_returned(value: Any) -> None:
    async def _first() -> Any:
        return value

    async def _second() -> Any:
        return "fallback"

    assert await fetch_with_fallback([_first, _second]) == value
