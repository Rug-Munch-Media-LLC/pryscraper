"""HTTP transport + response cache + ESPN scoreboard fetchers for odds.

Split out of ``odds.py`` (god-file reduction). The ``odds.py`` facade
re-exports everything here so the ``sports_data.odds`` surface is
unchanged.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import sys
import time
from typing import Any

import httpx

from datasets.sports_data.odds_common import (
    _ESPN_SCOREBOARD,
    _as_text,
)
from datasets.sports_data.odds_espn import (
    _espn_competitors,
    _espn_odds_to_comparison,
    _espn_odds_to_records,
)
from pry.engine.retry import RetryConfig, async_retry

# ── Transport ──────────────────────────────────────────────────────────
_TIMEOUT = httpx.Timeout(10.0)
_RETRY_CONFIG = RetryConfig(
    max_retries=1,
    base_delay=0.1,
    max_delay=0.4,
    retryable_exceptions=(httpx.HTTPError,),
)
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; pryscraper-sports/1.0; "
    "+https://git.rugmunch.io/RugMunchMedia/pryscraper)",
    "Accept": "application/json",
}

# 10s in-memory TTL cache on raw upstream responses (bots poll fast).
_CACHE_TTL = 10.0

# ── Upstream response cache (10s TTL) ─────────────────────────────────
_http_cache: dict[tuple[Any, ...], tuple[float, Any]] = {}


def _monotonic() -> float:
    """Injectable clock for cache expiry (tests control time)."""
    return time.monotonic()


def _cache_enabled() -> bool:
    """Return False while an HTTP mock (respx) is active.

    The cache exists to stop production pollers hammering upstream APIs.
    When tests install respx routes they expect every request to be
    observed, so the cache is bypassed — otherwise a cached response would
    leak across tests that mock the same URL differently.
    """
    respx_mod = sys.modules.get("respx")
    if respx_mod is None:
        return True
    return not bool(getattr(respx_mod, "routes", []))


def _cache_key(url: str, params: dict[str, str] | None) -> tuple[Any, ...]:
    """Cache key = URL + sorted query params (the API key stays in-memory only)."""
    return (url, tuple(sorted((params or {}).items())))


def _clear_cache() -> None:
    """Drop all cached upstream responses (exposed for tests/tuning)."""
    _http_cache.clear()


async def _fetch_json(
    url: str, params: dict[str, str] | None = None
) -> dict[str, Any] | list[Any] | None:
    """GET ``url`` (cached for :data:`_CACHE_TTL` seconds) and parse JSON.

    Returns the parsed object/array, or ``None`` on failure. The raw
    upstream response is what gets cached, so rapid pollers share one
    upstream call per (URL, params) within the TTL window.
    """
    key = _cache_key(url, params)
    if _cache_enabled():
        entry = _http_cache.get(key)
        if entry is not None:
            cached_at, payload = entry
            if _monotonic() - cached_at < _CACHE_TTL:
                return payload
            _http_cache.pop(key, None)
    payload = await _fetch_uncached(url, params)
    if payload is not None and _cache_enabled():
        _http_cache[key] = (_monotonic(), payload)
    return payload


async def _fetch_uncached(
    url: str, params: dict[str, str] | None = None
) -> dict[str, Any] | list[Any] | None:
    """Perform the actual HTTP GET with retry/backoff (no caching)."""

    async def _one() -> dict[str, Any] | list[Any]:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT, headers=_HEADERS, follow_redirects=True
        ) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            payload = response.json()
        if not isinstance(payload, (dict, list)):
            raise ValueError("sports API payload is not an object or array")
        return payload

    try:
        return await async_retry(_one, config=_RETRY_CONFIG)
    except (httpx.HTTPError, OSError, ValueError):
        return None


# ── ESPN scoreboard fetchers (fallback) ────────────────────────────────
async def _espn_odds_for_league(
    espn: tuple[str, str] | None,
    sport_slug: str,
    markets: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Fetch one ESPN scoreboard and flatten its odds blocks into records."""
    if espn is None:
        return []
    url = _ESPN_SCOREBOARD.format(sport=espn[0], league=espn[1])
    payload = await _fetch_json(url)
    if not isinstance(payload, dict):
        return []
    events = payload.get("events")
    if not isinstance(events, list):
        return []
    records: list[dict[str, Any]] = []
    for ev in events:
        if not isinstance(ev, dict):
            continue
        competitions = ev.get("competitions")
        if not isinstance(competitions, list) or not competitions:
            continue
        comp = competitions[0]
        if not isinstance(comp, dict):
            continue
        home, away, _hs, _as = _espn_competitors(comp)
        records.extend(_espn_odds_to_records(comp, sport_slug, home, away, markets))
    return records


async def _espn_find_event(
    espn: tuple[str, str] | None,
    sport_slug: str,
    event_id: str,
    markets: list[str] | None = None,
    book: str | None = None,
) -> dict[str, Any] | None:
    """Find one event on an ESPN scoreboard and build its odds comparison."""
    if espn is None:
        return None
    url = _ESPN_SCOREBOARD.format(sport=espn[0], league=espn[1])
    payload = await _fetch_json(url)
    if not isinstance(payload, dict):
        return None
    events = payload.get("events")
    if not isinstance(events, list):
        return None
    for ev in events:
        if not isinstance(ev, dict):
            continue
        competitions = ev.get("competitions")
        if not isinstance(competitions, list) or not competitions:
            continue
        comp = competitions[0]
        if not isinstance(comp, dict):
            continue
        if _as_text(ev.get("id")) == event_id or _as_text(comp.get("id")) == event_id:
            comparison = _espn_odds_to_comparison(comp, sport_slug, event_id, markets, book)
            if comparison.get("bookmakers"):
                return comparison
    return None
