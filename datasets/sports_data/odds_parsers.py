"""Odds record assembly / orchestration for the odds engine.

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

import logging
from typing import Any
from urllib.parse import quote

from datasets.sports_data.odds_common import (
    _BOOKS,
    _CANONICAL_SPORTS,
    _DEFAULT_SPORTS,
    _MARKETS_ALL,
    _MAX_LIMIT,
    _ODDS_API_REGIONS,
    _ODDS_BASE,
    _SPORT_ALIASES,
    _SPORTS,
    _api_key,
    _bookmaker_params,
    _canonical_book,
    _normalize_markets,
    _parse_sources_param,
    _resolve_sports,
)
from datasets.sports_data.odds_fetchers import (
    _CACHE_TTL,
    _espn_find_event,
    _espn_odds_for_league,
    _fetch_json,
)
from datasets.sports_data.odds_mapping import (
    _map_event_comparison,
    _map_odds_event,
)
from datasets.sports_data.odds_supplement import _supplementary_records

logger = logging.getLogger(__name__)


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
        sport: Sport name (see ``odds.py`` docstring) or ``"all"`` (default).
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
        A list of odds records (see ``odds.py`` docstring). ``[]`` on
        failure or invalid sport. Never raises.
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
        A comparison dict (see ``odds.py`` docstring) or ``{}`` on failure
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
