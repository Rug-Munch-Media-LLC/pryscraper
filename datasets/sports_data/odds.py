"""Live sports betting odds — The Odds API + ESPN + multi-source redundancy.

Core free sources, aggregated here:
* **The Odds API** (``api.the-odds-api.com``) — the market-standard live
  odds feed used by betting bots. Requires a free API key
  (https://the-odds-api.com) via the ``PRY_ODDS_API_KEY`` env var (free
  tier: 500 requests/month, upcoming events only). Aggregates 10+ major
  bookmakers and normalizes their odds into a common schema.
* **ESPN public scoreboards** (``site.api.espn.com``) — no key, no quota.
  When no key is configured (or the Odds API call fails) the module
  degrades to the ``odds`` block ESPN publishes on each competition;
  when ESPN publishes no odds the module returns ``[]``.
* **Redundancy sources** (:mod:`sports_data.sources`) — OddsPortal
  (scrape), Bovada and BetOnline (offshore public feeds). ``get_odds``
  accepts a ``sources`` parameter to combine any of
  ``the_odds_api,espn,oddsportal,bovada,betonline,books``; ``get_odds_multi``
  aggregates every reachable source for one event via ``asyncio.gather``
  and merges the deduped set; every source degrades independently.
* **112-book direct scrapers** (:mod:`sports_data.books`) — pass
  ``sources="books"`` (or ``"all"``) to ALSO pull direct per-book odds
  from the 112-book registry, tagged ``source="books"``.
Contract
--------
* :func:`get_odds` — async, never raises, returns a ``list`` (``[]`` on
  failure). One record per (event, bookmaker, market).
* :func:`get_event_odds` — async, never raises, returns a ``dict`` (``{}``
  on failure). Multi-sportsbook comparison for one event id.
* :func:`get_odds_multi` — async, never raises; merged multi-source set.
* :func:`supported_coverage` — sync sports x books x markets matrix.

Record shape (``get_odds``): ``{sport, event, event_id, market, book,
bookmaker, home, away, home_odds, away_odds, draw_odds, spread, total,
last_update, source}``. ``get_event_odds`` returns ``{event_id, sport,
event, commence_time, bookmakers: [{key, title, book, markets:
[{key, outcomes: [{name, price, point?}]}]}], source}``.Sports (20+): canonical Odds API keys (``basketball_nba``,
``americanfootball_nfl``, ``soccer_epl``, ...) plus legacy short aliases
(``nba``, ``nfl``, ``epl``, ``ufc``, ...). ``"all"`` (default) queries
nba, nfl, epl. Markets: ``h2h``, ``spreads``, ``totals``, ``outrights``
(aliases: ``moneyline``, ``spread``, ``overunder``, ``futures``; combos
comma/pipe separated or ``"all"``). Books (12+): ``pinnacle``,
``draftkings``, ``fanduel``, ``betmgm``, ``caesars``, ``bovada``, ...

Caching: raw upstream responses are cached in-memory for 10 seconds,
keyed by URL + query params, bypassed while an HTTP mock (respx) is
active so tests observe every request. :func:`_clear_cache` drops it.
Backoff: 1 retry, exponential (0.1s -> 0.4s). Registry/mapping internals
live in the ``odds_common`` / ``odds_mapping`` / ``odds_espn`` /
``odds_supplement`` / ``odds_multi`` siblings; this module re-exports
them so the ``sports_data.odds`` surface is unchanged.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import logging
import sys
import time
from typing import Any
from urllib.parse import quote

import httpx

from datasets.sports_data.odds_common import (  # re-exported surface
    _BOOK_TITLES as _BOOK_TITLES,
    _BOOKS as _BOOKS,
    _CANONICAL_SPORTS as _CANONICAL_SPORTS,
    _DEFAULT_SPORTS as _DEFAULT_SPORTS,
    _ESPN_SCOREBOARD as _ESPN_SCOREBOARD,
    _MARKET_ALIASES as _MARKET_ALIASES,
    _MARKETS_ALL as _MARKETS_ALL,
    _MAX_LIMIT as _MAX_LIMIT,
    _ODDS_API_REGIONS as _ODDS_API_REGIONS,
    _ODDS_BASE as _ODDS_BASE,
    _SOURCE_NAMES as _SOURCE_NAMES,
    _SPORT_ALIASES as _SPORT_ALIASES,
    _SPORTS as _SPORTS,
    _american_to_decimal as _american_to_decimal,
    _api_key as _api_key,
    _as_text as _as_text,
    _bookmaker_params as _bookmaker_params,
    _canonical_book as _canonical_book,
    _event_label as _event_label,
    _nested as _nested,
    _normalize_markets as _normalize_markets,
    _parse_sources_param as _parse_sources_param,
    _record as _record,
    _resolve_sports as _resolve_sports,
    _to_float as _to_float,
)
from datasets.sports_data.odds_espn import (  # re-exported surface
    _espn_competitors as _espn_competitors,
    _espn_odds_to_comparison as _espn_odds_to_comparison,
    _espn_odds_to_records as _espn_odds_to_records,
)
from datasets.sports_data.odds_mapping import (  # re-exported surface
    _map_event_comparison as _map_event_comparison,
    _map_odds_event as _map_odds_event,
    _market_records as _market_records,
    _outcome_prices as _outcome_prices,
)
from datasets.sports_data.odds_multi import (  # re-exported surface
    _get_odds_multi as _get_odds_multi,
    get_odds_multi as get_odds_multi,
)
from datasets.sports_data.odds_supplement import (  # re-exported surface
    _books_odds_for_sport as _books_odds_for_sport,
    _supplementary_records as _supplementary_records,
)
from pry.engine.retry import RetryConfig, async_retry

logger = logging.getLogger(__name__)

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


# ── Public API ─────────────────────────────────────────────────────────
async def get_odds(
    event_query: str = "",
    sport: str = "all",
    limit: int = 20,
    market: str = "h2h",
    book: str | None = None,
    sources: str | None = None,
) -> list[dict[str, Any]]:
    """Fetch live odds across bookmakers for one or more sports.

    Args:
        event_query: Optional substring filter against event labels (e.g.
            ``"celtics"``). Empty matches everything.
        sport: Sport name (see module docstring) or ``"all"`` (default).
        limit: Max records to return (1-100).
        market: Market(s) to fetch — ``"h2h"`` (default), ``"spreads"``,
            ``"totals"``, ``"outrights"``, combos, or ``"all"``.
        book: Optional single-book filter (e.g. ``"draftkings"``). When set
            The Odds API is asked for just that book and the result is
            filtered client-side too (covers the ESPN fallback).
        sources: Optional comma-separated source list — ``"the_odds_api"``,
            ``"espn"``, ``"oddsportal"``, ``"bovada"``, ``"betonline"``,
            ``"books"`` (or ``"all"``). ``None`` (default) keeps the legacy
            behavior (The Odds API when a key is configured, else ESPN).
            When set, only those sources are queried and the results are
            merged/deduped across them; unknown names are ignored.

    Returns:
        A list of odds records (see module docstring). ``[]`` on failure or
        invalid sport. Never raises.
    """
    try:
        return await _get_odds(event_query, sport, limit, market, book, sources)
    except Exception:
        logger.exception(
            "sports_odds_crashed",
            extra={
                "event_query": event_query,
                "sport": sport,
                "market": market,
                "book": book,
                "sources": sources,
            },
        )
        return []


async def _get_odds(
    event_query: str,
    sport: str,
    limit: int,
    market: str,
    book: str | None,
    sources: str | None = None,
) -> list[dict[str, Any]]:
    slugs = _resolve_sports(sport)
    if not slugs:
        logger.warning("sports_odds_invalid_sport", extra={"sport": sport})
        return []
    clamped = max(1, min(int(limit), _MAX_LIMIT))
    markets = _normalize_markets(market)
    key = _api_key()
    book_key = _canonical_book(book) if book else None
    wanted = _parse_sources_param(sources)
    core_records: list[dict[str, Any]] = []
    supplemental: list[dict[str, Any]] = []
    for slug in slugs:
        odds_key, espn = _SPORTS[slug]
        if key and (wanted is None or "the_odds_api" in wanted):
            params: dict[str, str] = {
                "apiKey": key,
                "regions": _ODDS_API_REGIONS,
                "markets": ",".join(markets),
                "oddsFormat": "decimal",
            }
            if book_key:
                api_books = _bookmaker_params(book_key)
                if api_books:
                    params["bookmakers"] = api_books
            url = f"{_ODDS_BASE}/{quote(odds_key)}/odds"
            payload = await _fetch_json(url, params)
            if isinstance(payload, list):
                for raw in payload:
                    if isinstance(raw, dict):
                        core_records.extend(_map_odds_event(raw, slug, markets=markets))
        elif wanted is None or "espn" in wanted:
            core_records.extend(await _espn_odds_for_league(espn, slug, markets))
        if wanted is not None:
            supplemental.extend(
                await _supplementary_records(wanted, slug, markets, book_key, limit=clamped)
            )
    records = core_records + supplemental
    if wanted is not None and len({record.get("source") for record in records}) > 1:
        from datasets.sports_data import sources as _odds_sources

        records = _odds_sources.merge_odds(records)
    query = (event_query or "").strip().lower()
    if query:
        records = [
            record
            for record in records
            if query in str(record.get("event") or "").lower()
            or query in str(record.get("sport") or "").lower()
            or query in str(record.get("home") or "").lower()
            or query in str(record.get("away") or "").lower()
        ]
    if book_key:
        records = [
            record
            for record in records
            if record.get("book") == book_key or str(record.get("book_id") or "") == book_key
        ]
    records.sort(key=lambda record: str(record.get("last_update") or ""), reverse=True)
    return records[:clamped]


async def get_event_odds(
    event_id: str,
    market: str = "h2h",
    book: str | None = None,
) -> dict[str, Any]:
    """Fetch multi-sportsbook odds for a single event.

    Args:
        event_id: The event id. Accepts an optional ``sport:event_id`` prefix
            (e.g. ``nba:bda33adc...``) to skip the default-sport scan.
        market: Market(s) to include in the comparison (default ``"h2h"``).
        book: Optional single-book filter (e.g. ``"draftkings"``).

    Returns:
        A comparison dict (see module docstring) or ``{}`` on failure
        (unknown event, network error). Never raises.
    """
    try:
        return await _get_event_odds(event_id, market, book)
    except Exception:
        logger.exception(
            "sports_event_odds_crashed",
            extra={"event_id": event_id, "market": market, "book": book},
        )
        return {}


async def _get_event_odds(
    event_id: str,
    market: str,
    book: str | None,
) -> dict[str, Any]:
    if not event_id or not str(event_id).strip():
        return {}
    raw_id = str(event_id).strip()
    prefix, _, rest = raw_id.partition(":")
    if rest:
        slugs = _resolve_sports(prefix)
        if not slugs:
            return {}
        candidates = slugs
        target_id = rest
    else:
        candidates = list(_DEFAULT_SPORTS)
        target_id = raw_id
    key = _api_key()
    markets = _normalize_markets(market)
    book_key = _canonical_book(book) if book else None
    for slug in candidates:
        odds_key, espn = _SPORTS[slug]
        if key:
            params: dict[str, str] = {
                "apiKey": key,
                "regions": _ODDS_API_REGIONS,
                "markets": ",".join(markets),
                "oddsFormat": "decimal",
            }
            if book_key:
                api_books = _bookmaker_params(book_key)
                if api_books:
                    params["bookmakers"] = api_books
            url = f"{_ODDS_BASE}/{quote(odds_key)}/events/{quote(target_id)}/odds"
            payload = await _fetch_json(url, params)
            if isinstance(payload, dict) and payload.get("id"):
                return _map_event_comparison(payload, slug, markets=markets, book=book_key)
        else:
            comparison = await _espn_find_event(
                espn, slug, target_id, markets=markets, book=book_key
            )
            if comparison is not None:
                return comparison
    return {}


def supported_coverage() -> dict[str, Any]:
    """Describe the sports x books x markets the odds engine can serve.

    Bots use this to decide what to request. The matrix is static (the
    engine's capabilities), not live availability — whether a given
    bookmaker prices a given sport/market today varies upstream, and some
    futures are only published under dedicated Odds API sport keys (e.g.
    ``basketball_nba_championship``) which this module does not query.
    """
    sports: dict[str, Any] = {}
    for key in _CANONICAL_SPORTS:
        _odds_key, espn = _SPORTS[key]
        sports[key] = {
            "odds_api_key": _odds_key,
            "espn": {"sport": espn[0], "league": espn[1]} if espn else None,
            "markets": list(_MARKETS_ALL),
        }
    return {
        "sports": sports,
        "sport_keys": list(_CANONICAL_SPORTS),
        "aliases": dict(sorted(_SPORT_ALIASES.items())),
        "books": list(_BOOKS),
        "markets": list(_MARKETS_ALL),
        "default_sports": list(_DEFAULT_SPORTS),
        "sources": ["the_odds_api", "espn"],
        "additional_sources": ["oddsportal", "bovada", "betonline"],
        "cache_ttl_seconds": _CACHE_TTL,
        "api_key_configured": bool(_api_key()),
    }
