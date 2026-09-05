"""Live sports betting odds — The Odds API + ESPN + multi-source redundancy.

Core free sources, aggregated here:

* **The Odds API** (``api.the-odds-api.com``) — the market-standard live
  odds feed used by betting bots. Requires a free API key
  (https://the-odds-api.com) via the ``PRY_ODDS_API_KEY`` env var. The free
  tier is 500 requests/month and covers upcoming events only (historical
  endpoints are paid). It aggregates 10+ major bookmakers (Pinnacle,
  DraftKings, FanDuel, BetMGM, Caesars, PointsBet, BetRivers, bet365,
  Unibet, William Hill, Bovada, BetOnline) and normalizes their odds into a
  common schema. Used whenever a key is configured.
* **ESPN public scoreboards** (``site.api.espn.com``) — no key, no quota.
  When no key is configured (or the Odds API call fails) the module degrades
  to the ``odds`` block ESPN publishes on each competition (moneyline,
  converted to decimal; spread and over/under lines where published).
  Coverage varies by league and window; when ESPN publishes no odds the
  module returns ``[]`` (never raises).
* **Redundancy sources** (:mod:`sports_data.sources`) — OddsPortal
  (scrape), Bovada and BetOnline (offshore public feeds). ``get_odds``
  accepts a ``sources`` parameter to combine any of
  ``the_odds_api,espn,oddsportal,bovada,betonline,books``; ``get_odds_multi``
  aggregates every reachable source for one event via ``asyncio.gather``
  and merges the deduped set. Every source degrades independently — one
  source down never blanks the result if another works.
* **112-book direct scrapers** (:mod:`sports_data.books`) — the sportsbook
  registry + generic scraper ("more sources than anyone, free"). Pass
  ``sources="books"`` (or ``"all"``, which includes them) to ALSO pull
  direct per-book odds from the 112-book registry and merge them in,
  tagged ``source="books"``. The books module is imported lazily so it can
  land from a parallel edit without breaking this module. Its results are
  cached for 30s inside ``sports_data.books`` so back-to-back 112-book
  polls don't re-scrape.

Contract
--------
* :func:`get_odds` — async, never raises, returns a ``list`` (``[]`` on
  failure). One record per (event, bookmaker, market).
* :func:`get_event_odds` — async, never raises, returns a ``dict`` (``{}``
  on failure). Multi-sportsbook comparison for one event id.
* :func:`supported_coverage` — sync, returns the sports x books x markets
  matrix the engine can serve (so bots know what to request).

Coverage
--------
Sports (20+): ``americanfootball_nfl``, ``americanfootball_ncaaf``,
``basketball_nba``, ``basketball_ncaab``, ``basketball_wnba``,
``baseball_mlb``, ``icehockey_nhl``, ``soccer_epl``,
``soccer_spain_la_liga``, ``soccer_germany_bundesliga``,
``soccer_italy_serie_a``, ``soccer_uefa_champions_league``, ``tennis_atp``,
``tennis_wta``, ``golf_pga``, ``mma_mixed_martial_arts``, ``boxing``,
``esports_csgo``, ``esports_dota2``, ``esports_league_of_legends``,
``formula_1``, ``cricket_international_t20`` plus the legacy short aliases
``nba``, ``nfl``, ``mlb``, ``nhl``, ``ncaab``, ``ncaaf``, ``epl``, ``mls``,
``wnba``, ``ufc``, ``cfl``. ``"all"`` (default) queries the most popular
sports: nba, nfl, epl.

Markets: ``h2h`` (moneyline, 2-way or 3-way with ``draw_odds``), ``spreads``,
``totals`` (over/under), ``outrights`` (futures/winner). Pass
``market="h2h,spreads"`` (comma or pipe separated) or ``market="all"``.

Books (12+): ``pinnacle``, ``draftkings``, ``fanduel``, ``betmgm``,
``caesars``, ``pointsbet``, ``betrivers``, ``bet365``, ``unibet``,
``williamhill``, ``bovada``, ``betonline``. Pass ``book="draftkings"`` to
filter (and ask The Odds API for just that book).

Result shapes
-------------
``get_odds`` returns a list of:

    {
        "sport": "basketball_nba",
        "event": "Celtics @ Lakers",
        "event_id": "bda33adc...",
        "market": "h2h",
        "book": "draftkings",
        "bookmaker": "DraftKings",       # legacy alias of ``book``
        "home": "Los Angeles Lakers",
        "away": "Boston Celtics",
        "home_odds": 2.10,
        "away_odds": 1.85,
        "draw_odds": None,               # 3-way markets only
        "spread": None,                  # spreads market only
        "total": None,                   # totals market only
        "last_update": "2026-08-16T12:00:00Z",
        "source": "the_odds_api",
    }

``get_event_odds`` returns:

    {
        "event_id": "bda33adc...",
        "sport": "basketball_nba",
        "event": "Celtics @ Lakers",
        "commence_time": "2026-08-17T00:00:00Z",
        "bookmakers": [
            {
                "key": "draftkings",
                "title": "DraftKings",
                "book": "draftkings",
                "markets": [
                    {"key": "h2h", "outcomes": [{"name": "Celtics", "price": 1.85}, ...]}
                ],
            },
        ],
    }

Caching
-------
Raw upstream responses are cached in-memory for 10 seconds (bots poll
fast); the cache is keyed by URL + query params and is bypassed while an
HTTP mock (respx) is active so tests observe every request.
:func:`~sports_data.odds._clear_cache` drops the cache (tests/tuning).

Free-API terms: https://the-odds-api.com (v4 docs, cost = markets x regions
per call; free tier ~ 500 requests/month). Backoff: 1 retry, exponential
(0.1s -> 0.4s) to keep latency low for high-frequency pollers.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

from pry.engine.retry import RetryConfig, async_retry

logger = logging.getLogger(__name__)

# ── Data-driven registry loader ─────────────────────────────────────────
# Static sports/books metadata lives as plain JSON (data, not code) under
# ``data/odds.json``; this module loads it at import time.
_DATA_DIR = Path(__file__).resolve().parent / "data"


def _load_json(name: str) -> Any:
    with (_DATA_DIR / name).open(encoding="utf-8") as fh:
        return json.load(fh)


# ── Markets ────────────────────────────────────────────────────────────
_MARKET_H2H = "h2h"
_MARKET_SPREADS = "spreads"
_MARKET_TOTALS = "totals"
_MARKET_OUTRIGHTS = "outrights"
_MARKETS_ALL: tuple[str, ...] = (
    _MARKET_H2H,
    _MARKET_SPREADS,
    _MARKET_TOTALS,
    _MARKET_OUTRIGHTS,
)

# Accept common aliases (moneyline, spread, over/under, futures...).
_MARKET_ALIASES: dict[str, str] = {
    "h2h": _MARKET_H2H,
    "ml": _MARKET_H2H,
    "moneyline": _MARKET_H2H,
    "spread": _MARKET_SPREADS,
    "spreads": _MARKET_SPREADS,
    "pointspread": _MARKET_SPREADS,
    "total": _MARKET_TOTALS,
    "totals": _MARKET_TOTALS,
    "overunder": _MARKET_TOTALS,
    "ou": _MARKET_TOTALS,
    "outrights": _MARKET_OUTRIGHTS,
    "futures": _MARKET_OUTRIGHTS,
    "winner": _MARKET_OUTRIGHTS,
    "championship": _MARKET_OUTRIGHTS,
}

# ── Sports ─────────────────────────────────────────────────────────────
# Canonical sport key (the Odds API key) -> ESPN (sport, league) fallback.
# ``None`` ESPN means The Odds API is the only source for that sport.
# Data-driven (JSON).
_ODDS_DATA: dict[str, Any] = _load_json("odds.json")
_CANONICAL_SPORTS: dict[str, tuple[str, str] | None] = {
    k: (v[0], v[1]) if v is not None else None for k, v in _ODDS_DATA["_CANONICAL_SPORTS"].items()
}

# Legacy short aliases -> canonical key (backward compatibility).
_SPORT_ALIASES: dict[str, str] = _ODDS_DATA["_SPORT_ALIASES"]


def _build_sports_table() -> dict[str, tuple[str, tuple[str, str] | None]]:
    """Build the lookup table: alias/canonical key -> (odds key, ESPN tuple)."""
    table: dict[str, tuple[str, tuple[str, str] | None]] = {}
    for key, espn in _CANONICAL_SPORTS.items():
        table[key] = (key, espn)
    for alias, canonical in _SPORT_ALIASES.items():
        table[alias] = table[canonical]
    return table


_SPORTS: dict[str, tuple[str, tuple[str, str] | None]] = _build_sports_table()

# The Odds API free tier is quota-bound (500 req/month); "all" never queries
# the full sport list. These are the sports betting bots care about most.
_DEFAULT_SPORTS: tuple[str, ...] = tuple(_ODDS_DATA["_DEFAULT_SPORTS"])

# ── Books ──────────────────────────────────────────────────────────────
# Canonical book slug -> the upstream identifiers that identify it.
# The values are The Odds API ``bookmakers`` keys (valid for the upstream
# request) — display titles live in ``_BOOK_TITLES`` below (normalization
# only, never sent upstream). Data-driven (JSON).
_BOOKS: dict[str, tuple[str, ...]] = {k: tuple(v) for k, v in _ODDS_DATA["_BOOKS"].items()}

# Display titles (ESPN provider names etc.) -> canonical slug. Used for
# normalization only — never sent upstream.
_BOOK_TITLES: dict[str, str] = _ODDS_DATA["_BOOK_TITLES"]

# ── Endpoints / transport ──────────────────────────────────────────────
_ODDS_BASE = "https://api.the-odds-api.com/v4/sports"
_ESPN_SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/scoreboard"

_API_KEY_ENV = "PRY_ODDS_API_KEY"
_TIMEOUT = httpx.Timeout(10.0)
_RETRY_CONFIG = RetryConfig(
    max_retries=1,
    base_delay=0.1,
    max_delay=0.4,
    retryable_exceptions=(httpx.HTTPError,),
)
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; pryscraper-sports/1.0; "
        "+https://git.rugmunch.io/RugMunchMedia/pryscraper)"
    ),
    "Accept": "application/json",
}

_MAX_LIMIT = 100
_ODDS_API_REGIONS = "us"

# 10s in-memory TTL cache on raw upstream responses (bots poll fast).
_CACHE_TTL = 10.0


def _api_key() -> str:
    """Return the configured The Odds API key (or '' when unset)."""
    return os.environ.get(_API_KEY_ENV, "").strip()


def _resolve_sports(sport: str) -> list[str]:
    """Map a ``sport`` parameter to the list of sports to query.

    ``""`` / ``"all"`` → the default sports; a known canonical key or short
    alias (e.g. ``basketball_nba`` or ``nba``) → that one sport; anything
    unknown → ``[]`` (callers treat this as "invalid sport, return empty").
    """
    raw = str(sport or "").strip().lower()
    if raw in {"", "all"}:
        return list(_DEFAULT_SPORTS)
    if raw in _SPORTS:
        return [raw]
    return []


def _as_text(value: Any) -> str | None:
    """Coerce a JSON value to str/None ('' -> None)."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _to_float(value: Any) -> float | None:
    """Coerce a JSON value to float/None ('' / garbage -> None)."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _nested(mapping: Any, *keys: str) -> Any:
    """Dive into nested dicts, returning None if any level is missing."""
    current = mapping
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _american_to_decimal(price: Any) -> float | None:
    """Convert American moneyline odds (e.g. -150, +125) to decimal odds."""
    value = _to_float(price)
    if value is None or value == 0:
        return None
    if value > 0:
        return round(1 + value / 100, 2)
    return round(1 + 100 / abs(value), 2)


def _event_label(home: str | None, away: str | None) -> str | None:
    """Compose the conventional "Away @ Home" event label."""
    if not home or not away:
        return None
    return f"{away} @ {home}"


def _canonical_book(value: str | None) -> str:
    """Normalize a bookmaker key/title to a canonical book slug."""
    if not value:
        return "unknown"
    norm = "".join(ch for ch in str(value).strip().lower() if ch.isalnum())
    for slug, keys in _BOOKS.items():
        for key in keys:
            if "".join(ch for ch in key.lower() if ch.isalnum()) == norm:
                return slug
    for title, slug in _BOOK_TITLES.items():
        if "".join(ch for ch in title.lower() if ch.isalnum()) == norm:
            return slug
    return norm or "unknown"


def _bookmaker_params(book_key: str) -> str | None:
    """Map a canonical book slug to the The Odds API ``bookmakers`` value."""
    keys = _BOOKS.get(book_key)
    if not keys:
        return None
    return ",".join(keys)


def _normalize_markets(market: str) -> list[str]:
    """Normalize a ``market`` parameter into the canonical markets to fetch.

    Accepts comma or pipe separated values plus aliases (``moneyline``,
    ``spread``, ``overunder``, ``futures``...). ``"all"`` / ``"*"`` requests
    every market; anything unparseable falls back to ``h2h``.
    """
    raw = str(market or "").strip().lower().replace("|", ",")
    if raw in {"all", "*"}:
        return list(_MARKETS_ALL)
    if not raw:
        return [_MARKET_H2H]
    markets: list[str] = []
    for part in raw.split(","):
        part = part.strip().lower()
        canonical = _MARKET_ALIASES.get(part)
        if canonical is not None and canonical not in markets:
            markets.append(canonical)
    return markets or [_MARKET_H2H]


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


# ── The Odds API mapping ───────────────────────────────────────────────
def _record(
    *,
    sport: str,
    event: str,
    event_id: str | None,
    market: str,
    book: str,
    bookmaker: str,
    home: str | None,
    away: str | None,
    home_odds: float | None,
    away_odds: float | None,
    draw_odds: float | None = None,
    spread: float | None = None,
    total: float | None = None,
    last_update: str | None,
    source: str,
) -> dict[str, Any]:
    """Build one canonical odds record (the shared schema across sources)."""
    return {
        "sport": sport,
        "event": event,
        "event_id": event_id,
        "market": market,
        "book": book,
        "bookmaker": bookmaker,
        "home": home,
        "away": away,
        "home_odds": home_odds,
        "away_odds": away_odds,
        "draw_odds": draw_odds,
        "spread": spread,
        "total": total,
        "last_update": last_update,
        "source": source,
    }


def _outcome_prices(outcomes: Any) -> dict[str, float]:
    """Map normalized outcome name -> decimal price for one market."""
    prices: dict[str, float] = {}
    if not isinstance(outcomes, list):
        return prices
    for outcome in outcomes:
        if not isinstance(outcome, dict):
            continue
        name = _as_text(outcome.get("name"))
        price = _to_float(outcome.get("price"))
        if name is not None and price is not None:
            prices.setdefault(name.lower(), price)
    return prices


def _market_records(
    market_key: str,
    outcomes: Any,
    *,
    sport: str,
    event: str | None,
    event_id: str | None,
    book: str,
    bookmaker: str,
    home: str | None,
    away: str | None,
    last_update: str | None,
) -> list[dict[str, Any]]:
    """Map one (bookmaker, market) block onto canonical odds records."""
    market = _MARKET_ALIASES.get(str(market_key or "").strip().lower(), _MARKET_H2H)

    if market == _MARKET_H2H:
        prices = _outcome_prices(outcomes)
        home_price = prices.get(home.lower()) if home else None
        away_price = prices.get(away.lower()) if away else None
        draw_price = prices.get("draw") or prices.get("tie")
        if home_price is None and away_price is None:
            return []
        return [
            _record(
                sport=sport,
                event=event or "",
                event_id=event_id,
                market=_MARKET_H2H,
                book=book,
                bookmaker=bookmaker,
                home=home,
                away=away,
                home_odds=home_price,
                away_odds=away_price,
                draw_odds=draw_price,
                last_update=last_update,
                source="the_odds_api",
            )
        ]

    if market == _MARKET_SPREADS:
        home_price = away_price = None
        home_point = away_point = None
        for outcome in outcomes if isinstance(outcomes, list) else []:
            if not isinstance(outcome, dict):
                continue
            name = _as_text(outcome.get("name"))
            price = _to_float(outcome.get("price"))
            point = _to_float(outcome.get("point"))
            if name is None or price is None:
                continue
            if home and name.lower() == home.lower():
                home_price, home_point = price, point
            elif away and name.lower() == away.lower():
                away_price, away_point = price, point
        if home_price is None and away_price is None:
            return []
        spread = home_point
        if spread is None and away_point is not None:
            spread = -away_point
        return [
            _record(
                sport=sport,
                event=event or "",
                event_id=event_id,
                market=_MARKET_SPREADS,
                book=book,
                bookmaker=bookmaker,
                home=home,
                away=away,
                home_odds=home_price,
                away_odds=away_price,
                spread=spread,
                last_update=last_update,
                source="the_odds_api",
            )
        ]

    if market == _MARKET_TOTALS:
        over_price = under_price = None
        total: float | None = None
        for outcome in outcomes if isinstance(outcomes, list) else []:
            if not isinstance(outcome, dict):
                continue
            name = _as_text(outcome.get("name"))
            price = _to_float(outcome.get("price"))
            point = _to_float(outcome.get("point"))
            if name is None or price is None:
                continue
            if name.lower() in {"over", "o"}:
                over_price, total = price, point
            elif name.lower() in {"under", "u"}:
                under_price, total = price, point
        if over_price is None and under_price is None:
            return []
        return [
            _record(
                sport=sport,
                event=event or "",
                event_id=event_id,
                market=_MARKET_TOTALS,
                book=book,
                bookmaker=bookmaker,
                home=home,
                away=away,
                home_odds=over_price,
                away_odds=under_price,
                total=total,
                last_update=last_update,
                source="the_odds_api",
            )
        ]

    if market == _MARKET_OUTRIGHTS:
        contenders: list[tuple[str, float]] = []
        for outcome in outcomes if isinstance(outcomes, list) else []:
            if not isinstance(outcome, dict):
                continue
            name = _as_text(outcome.get("name"))
            price = _to_float(outcome.get("price"))
            if name is not None and price is not None:
                contenders.append((name, price))
        records: list[dict[str, Any]] = []
        for name, price in contenders:
            records.append(
                _record(
                    sport=sport,
                    event=event or name,
                    event_id=event_id,
                    market=_MARKET_OUTRIGHTS,
                    book=book,
                    bookmaker=bookmaker,
                    home=name,
                    away=None,
                    home_odds=price,
                    away_odds=None,
                    last_update=last_update,
                    source="the_odds_api",
                )
            )
        return records

    return []


def _map_odds_event(
    raw: dict[str, Any],
    sport_key: str,
    markets: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Map one The Odds API event object onto canonical odds records.

    ``markets`` optionally restricts which markets are emitted (upstream
    usually filters server-side; this keeps the mapper defensive).
    """
    wanted = markets or [_MARKET_H2H]
    home = _as_text(raw.get("home_team"))
    away = _as_text(raw.get("away_team"))
    event = _event_label(home, away)
    event_id = _as_text(raw.get("id"))
    commence = _as_text(raw.get("commence_time"))
    bookmakers = raw.get("bookmakers")
    if not isinstance(bookmakers, list):
        return []
    records: list[dict[str, Any]] = []
    for bk in bookmakers:
        if not isinstance(bk, dict):
            continue
        title = _as_text(bk.get("title")) or _as_text(bk.get("key"))
        if not title:
            continue
        book = _canonical_book(_as_text(bk.get("key")) or title)
        last_update = _as_text(bk.get("last_update")) or commence
        markets_list = bk.get("markets")
        if not isinstance(markets_list, list):
            continue
        for mkt in markets_list:
            if not isinstance(mkt, dict):
                continue
            market_key = _as_text(mkt.get("key")) or _MARKET_H2H
            canonical = _MARKET_ALIASES.get(market_key, _MARKET_H2H)
            if canonical not in wanted:
                continue
            records.extend(
                _market_records(
                    market_key,
                    mkt.get("outcomes"),
                    sport=sport_key,
                    event=event,
                    event_id=event_id,
                    book=book,
                    bookmaker=title,
                    home=home,
                    away=away,
                    last_update=last_update,
                )
            )
    return records


def _map_event_comparison(
    raw: dict[str, Any],
    sport_slug: str,
    markets: list[str] | None = None,
    book: str | None = None,
) -> dict[str, Any]:
    """Map a single-event Odds API payload onto the comparison dict."""
    home = _as_text(raw.get("home_team"))
    away = _as_text(raw.get("away_team"))
    event = _event_label(home, away) or ""
    wanted_markets = markets or [_MARKET_H2H]
    bookmakers: list[dict[str, Any]] = []
    raw_bookmakers = raw.get("bookmakers")
    if isinstance(raw_bookmakers, list):
        for bk in raw_bookmakers:
            if not isinstance(bk, dict):
                continue
            bk_key = _as_text(bk.get("key"))
            title = _as_text(bk.get("title")) or bk_key
            if not title:
                continue
            book_slug = _canonical_book(bk_key or title)
            if book is not None and book_slug != book:
                continue
            markets_out: list[dict[str, Any]] = []
            raw_markets = bk.get("markets")
            if isinstance(raw_markets, list):
                for mkt in raw_markets:
                    if not isinstance(mkt, dict):
                        continue
                    mkt_key = _as_text(mkt.get("key")) or _MARKET_H2H
                    canonical_mkt = _MARKET_ALIASES.get(mkt_key, _MARKET_H2H)
                    if canonical_mkt not in wanted_markets:
                        continue
                    outcomes: list[dict[str, Any]] = []
                    raw_outcomes = mkt.get("outcomes")
                    if isinstance(raw_outcomes, list):
                        for outcome in raw_outcomes:
                            if not isinstance(outcome, dict):
                                continue
                            price = _to_float(outcome.get("price"))
                            name = _as_text(outcome.get("name"))
                            if name is None or price is None:
                                continue
                            entry: dict[str, Any] = {"name": name, "price": price}
                            point = _to_float(outcome.get("point"))
                            if point is not None:
                                entry["point"] = point
                            outcomes.append(entry)
                    if outcomes:
                        markets_out.append({"key": mkt_key, "outcomes": outcomes})
            bookmakers.append(
                {
                    "key": bk_key,
                    "title": title,
                    "book": book_slug,
                    "markets": markets_out,
                }
            )
    return {
        "event_id": _as_text(raw.get("id")),
        "sport": sport_slug,
        "event": event,
        "commence_time": _as_text(raw.get("commence_time")),
        "bookmakers": bookmakers,
        "source": "the_odds_api",
    }


# ── ESPN scoreboard mapping (fallback) ─────────────────────────────────
def _espn_competitors(
    comp: dict[str, Any],
) -> tuple[str | None, str | None, str | None, str | None]:
    """Extract (home, away, home_score, away_score) from an ESPN competition."""
    home = away = home_score = away_score = None
    competitors = comp.get("competitors")
    if not isinstance(competitors, list):
        return home, away, home_score, away_score
    for c in competitors:
        if not isinstance(c, dict):
            continue
        team = c.get("team")
        name = _as_text(team.get("displayName")) if isinstance(team, dict) else None
        if c.get("homeAway") == "home":
            home = name
            home_score = _as_text(c.get("score"))
        elif c.get("homeAway") == "away":
            away = name
            away_score = _as_text(c.get("score"))
    return home, away, home_score, away_score


def _espn_odds_to_records(
    comp: dict[str, Any],
    sport_slug: str,
    home: str | None,
    away: str | None,
    markets: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Map the ESPN ``odds`` block of one competition onto canonical records."""
    event = _event_label(home, away)
    if not event:
        return []
    odds_list = comp.get("odds")
    if not isinstance(odds_list, list):
        return []
    wanted_markets = markets or [_MARKET_H2H]
    records: list[dict[str, Any]] = []
    for odd in odds_list:
        if not isinstance(odd, dict):
            continue
        provider = odd.get("provider")
        title = _as_text(provider.get("name")) if isinstance(provider, dict) else None
        if not title:
            continue
        book = _canonical_book(title)
        event_id = _as_text(comp.get("id"))
        base = {
            "sport": sport_slug,
            "event": event,
            "event_id": event_id,
            "book": book,
            "bookmaker": title,
            "home": home,
            "away": away,
            "last_update": None,
            "source": "espn",
        }
        for market in wanted_markets:
            if market == _MARKET_H2H:
                home_ml = _american_to_decimal(_nested(odd, "homeTeamOdds", "moneyLine"))
                away_ml = _american_to_decimal(_nested(odd, "awayTeamOdds", "moneyLine"))
                if home_ml is None and away_ml is None:
                    continue
                record = dict(base)
                record.update(
                    {
                        "market": _MARKET_H2H,
                        "home_odds": home_ml,
                        "away_odds": away_ml,
                        "draw_odds": None,
                        "spread": None,
                        "total": None,
                    }
                )
                records.append(record)
            elif market == _MARKET_SPREADS:
                spread = _to_float(odd.get("spread"))
                if spread is None:
                    continue
                home_so = _american_to_decimal(_nested(odd, "homeTeamOdds", "spreadOdds"))
                away_so = _american_to_decimal(_nested(odd, "awayTeamOdds", "spreadOdds"))
                record = dict(base)
                record.update(
                    {
                        "market": _MARKET_SPREADS,
                        "home_odds": home_so,
                        "away_odds": away_so,
                        "draw_odds": None,
                        "spread": spread,
                        "total": None,
                    }
                )
                records.append(record)
            elif market == _MARKET_TOTALS:
                total = _to_float(odd.get("overUnder"))
                if total is None:
                    continue
                record = dict(base)
                record.update(
                    {
                        "market": _MARKET_TOTALS,
                        "home_odds": None,
                        "away_odds": None,
                        "draw_odds": None,
                        "spread": None,
                        "total": total,
                    }
                )
                records.append(record)
    return records


def _espn_odds_to_comparison(
    comp: dict[str, Any],
    sport_slug: str,
    event_id: str,
    markets: list[str] | None = None,
    book: str | None = None,
) -> dict[str, Any]:
    """Build a multi-book comparison dict from one ESPN competition's odds."""
    home, away, _home_score, _away_score = _espn_competitors(comp)
    odds_list = comp.get("odds")
    bookmakers: list[dict[str, Any]] = []
    if isinstance(odds_list, list):
        for odd in odds_list:
            if not isinstance(odd, dict):
                continue
            provider = odd.get("provider")
            title = _as_text(provider.get("name")) if isinstance(provider, dict) else None
            if not title:
                continue
            book_slug = _canonical_book(title)
            if book is not None and book_slug != book:
                continue
            outcomes: list[dict[str, Any]] = []
            home_ml = _american_to_decimal(_nested(odd, "homeTeamOdds", "moneyLine"))
            away_ml = _american_to_decimal(_nested(odd, "awayTeamOdds", "moneyLine"))
            if home_ml is not None and home is not None:
                outcomes.append({"name": home, "price": home_ml})
            if away_ml is not None and away is not None:
                outcomes.append({"name": away, "price": away_ml})
            if outcomes:
                bookmakers.append(
                    {
                        "key": None,
                        "title": title,
                        "book": book_slug,
                        "markets": [{"key": _MARKET_H2H, "outcomes": outcomes}],
                    }
                )
    return {
        "event_id": event_id,
        "sport": sport_slug,
        "event": _event_label(home, away) or "",
        "commence_time": None,
        "bookmakers": bookmakers,
        "source": "espn",
    }


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


# ── Multi-source support ────────────────────────────────────────────────
# Canonical source names understood by the ``sources`` parameter. The
# supplementary fetchers + merge logic live in sports_data.sources (owned
# alongside this module); they are imported lazily to keep this module's
# import order independent of the package __init__ cycle. ``books`` is the
# 112-book direct scraper registry (sports_data.books) — it is also
# imported lazily because that module can land from a parallel edit.
_SOURCE_NAMES = ("the_odds_api", "espn", "oddsportal", "bovada", "betonline", "books")


def _parse_sources_param(sources: str | None) -> set[str] | None:
    """Normalize a ``sources`` param into the set of source names to query.

    ``None`` / ``""`` -> ``None`` (legacy behavior: The Odds API when a key
    is configured, else ESPN). ``"all"`` / ``"*"`` -> every source name
    (including ``"books"``, the 112-book direct scrapers). Unknown names
    are ignored (never raises); if nothing valid remains the result is
    ``None`` (legacy behavior).
    """
    if sources is None:
        return None
    raw = str(sources).strip().lower()
    if not raw or raw in {"all", "*"}:
        return set(_SOURCE_NAMES)
    names = {part.strip() for part in re.split(r"[,\s|]+", raw) if part.strip()}
    valid = names & set(_SOURCE_NAMES)
    return valid or None


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
            ``"totals"``, ``"outrights"``, comma/pipe separated combos, or
            ``"all"``. Aliases: ``moneyline``, ``spread``, ``overunder``,
            ``futures``.
        book: Optional single-book filter (e.g. ``"draftkings"``). When set
            The Odds API is asked for just that book and the result is
            filtered client-side too (covers the ESPN fallback).
        sources: Optional comma-separated source list —
            ``"the_odds_api"``, ``"espn"``, ``"oddsportal"``, ``"bovada"``,
            ``"betonline"``, ``"books"`` (or ``"all"``, which includes the
            112-book direct scrapers). ``None`` (default) keeps the
            legacy behavior (The Odds API when a key is configured, else
            ESPN). When set, only those sources are queried and the results
            are merged/deduped across them; unknown names are ignored.

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


async def _supplementary_records(
    wanted: set[str],
    slug: str,
    markets: list[str],
    book_key: str | None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Fetch records from the scrape/offshore sources for one sport.

    Each source is fetched independently (``asyncio.gather`` with
    ``return_exceptions=True``) so one failure never affects the others.
    ``books`` (the 112-book direct scrapers) participates too when
    requested; it is imported lazily because that module can land from a
    parallel edit.
    """
    from datasets.sports_data import sources as _odds_sources

    jobs: list[tuple[str, Any]] = []
    if "oddsportal" in wanted and _odds_sources.source_supports("oddsportal", slug):
        jobs.append(("oddsportal", _odds_sources.fetch_oddsportal(slug)))
    if "bovada" in wanted and _odds_sources.source_supports("bovada", slug):
        jobs.append(("bovada", _odds_sources.fetch_bovada(slug)))
    if "betonline" in wanted and _odds_sources.source_supports("betonline", slug):
        jobs.append(("betonline", _odds_sources.fetch_betonline(slug)))
    if "books" in wanted:
        jobs.append(("books", _books_odds_for_sport(slug, markets, book_key, limit=limit)))
    if not jobs:
        return []
    results = await asyncio.gather(*(job for _name, job in jobs), return_exceptions=True)
    records: list[dict[str, Any]] = []
    for (name, _job), result in zip(jobs, results, strict=False):
        if isinstance(result, BaseException):
            logger.warning(
                "sports_supplementary_source_failed", extra={"source": name, "sport": slug}
            )
            continue
        for record in result or []:
            if not isinstance(record, dict):
                continue
            if record.get("market") not in markets:
                continue
            if book_key is not None and record.get("book") != book_key:
                continue
            records.append(record)
    return records


async def _books_odds_for_sport(
    slug: str,
    markets: list[str],
    book_key: str | None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Pull normalized odds from the 112-book scraper registry for one sport.

    The ``sports_data.books`` module may be edited in parallel, so the
    import is guarded: if it is momentarily unavailable the books source
    simply contributes nothing (never raises). Records are copied and
    tagged ``source="books"`` (the pipeline-level source name); the
    per-book identity stays in ``book`` / ``book_id``.
    """
    try:
        from datasets.sports_data import books as _books
    except Exception:  # noqa: BLE001 - guarded parallel import
        logger.warning("sports_books_module_unavailable", extra={"sport": slug})
        return []
    try:
        market_arg = markets[0] if len(markets) == 1 else "all"
        records = await _books.get_all_books_odds(sport=slug, market=market_arg, limit=limit)
    except Exception:  # noqa: BLE001 - never raise
        logger.warning("sports_books_failed", extra={"sport": slug})
        return []
    tagged: list[dict[str, Any]] = []
    for record in records or []:
        if not isinstance(record, dict):
            continue
        if record.get("market") not in markets:
            continue
        if book_key is not None and record.get("book_id") != book_key:
            continue
        copy = dict(record)
        copy["source"] = "books"
        copy["sport"] = slug
        tagged.append(copy)
    return tagged


async def get_event_odds(
    event_id: str,
    market: str = "h2h",
    book: str | None = None,
) -> dict[str, Any]:
    """Fetch multi-sportsbook odds for a single event.

    Args:
        event_id: The event id. Accepts an optional ``sport:event_id`` prefix
            (e.g. ``nba:bda33adc...`` or ``basketball_nba:...``) to skip the
            default-sport scan.
        market: Market(s) to include in the comparison — ``"h2h"``
            (default), ``"spreads"``, ``"totals"``, ``"outrights"`` or a
            comma/pipe separated combo.
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


async def get_odds_multi(
    event_id: str,
    market: str = "h2h",
    book: str | None = None,
    limit: int = 50,
    sources: str | None = None,
) -> list[dict[str, Any]]:
    """Aggregate one event's odds from every reachable source.

    Resolves the event (label + sport) through the core comparison path,
    then fetches from each reachable source in parallel via
    ``asyncio.gather`` (The Odds API / ESPN core plus OddsPortal, Bovada and
    BetOnline where the sport is mapped, and the 112-book direct scrapers
    when ``sources`` includes ``"books"`` or ``"all"``) and returns the
    merged, deduped record set (:func:`sports_data.sources.merge_odds` —
    Pinnacle wins conflicts). Each source degrades independently: one
    source being down or blocked never blanks the result if another works.

    Args:
        event_id: The event id; accepts an optional ``sport:event_id``
            prefix (e.g. ``nba:bda33adc...``) like :func:`get_event_odds`.
        market: Market(s) to include — ``"h2h"`` (default), ``"spreads"``,
            ``"totals"``, ``"outrights"`` or a comma/pipe separated combo.
        book: Optional single-book filter (e.g. ``"draftkings"``).
        limit: Max records to return (1-100).
        sources: Optional comma-separated source list (see
            :func:`get_odds`); ``None`` queries every reachable source
            except the 112-book scrapers (those require an explicit
            ``"books"`` / ``"all"``).

    Returns:
        A deduped list of canonical odds records for the event. ``[]`` when
        the event cannot be resolved or nothing is reachable. Never raises.
    """
    try:
        return await _get_odds_multi(event_id, market, book, limit, sources)
    except Exception:
        logger.exception(
            "sports_odds_multi_crashed",
            extra={"event_id": event_id, "market": market, "book": book},
        )
        return []


async def _get_odds_multi(
    event_id: str,
    market: str,
    book: str | None,
    limit: int,
    sources: str | None,
) -> list[dict[str, Any]]:
    from datasets.sports_data import sources as _odds_sources

    if not event_id or not str(event_id).strip():
        return []
    # Resolve event meta (label + sport) through the existing comparison
    # path — never raises.
    comparison = await _get_event_odds(event_id, market, book)
    label = _as_text(comparison.get("event")) if comparison else None
    sport = _as_text(comparison.get("sport")) if comparison else None
    if not label:
        return []
    slug = sport if sport and sport in _SPORTS else ""
    if not slug:
        return []
    clamped = max(1, min(int(limit), _MAX_LIMIT))
    markets = _normalize_markets(market)
    book_key = _canonical_book(book) if book else None
    key = _api_key()
    wanted = _parse_sources_param(sources)

    jobs: list[tuple[str, Any]] = []
    if key and (wanted is None or "the_odds_api" in wanted):
        jobs.append(
            (
                "the_odds_api",
                _get_odds(
                    event_query=label, sport=slug, limit=_MAX_LIMIT, market=market, book=book
                ),
            )
        )
    if wanted is None or "espn" in wanted:
        espn = _SPORTS[slug][1]
        jobs.append(("espn", _espn_odds_for_league(espn, slug, markets)))
    for name in ("oddsportal", "bovada", "betonline"):
        if wanted is not None and name not in wanted:
            continue
        if not _odds_sources.source_supports(name, slug):
            continue
        if name == "oddsportal":
            jobs.append((name, _odds_sources.fetch_oddsportal(slug, limit=8)))
        elif name == "bovada":
            jobs.append((name, _odds_sources.fetch_bovada(slug)))
        else:
            jobs.append((name, _odds_sources.fetch_betonline(slug)))
    # The 112-book direct scrapers are only pulled when explicitly
    # requested ("books" / "all") — they are the heaviest source and the
    # default ``sources=None`` behavior stays unchanged.
    if wanted is not None and "books" in wanted:
        jobs.append(("books", _books_odds_for_sport(slug, markets, book_key, limit=clamped)))

    if not jobs:
        return []
    results = await asyncio.gather(*(job for _name, job in jobs), return_exceptions=True)
    records: list[dict[str, Any]] = []
    for (name, _job), result in zip(jobs, results, strict=False):
        if isinstance(result, BaseException):
            logger.warning(
                "sports_odds_multi_source_failed",
                extra={"event_id": event_id, "source": name},
            )
            continue
        for record in result or []:
            if not isinstance(record, dict):
                continue
            if record.get("market") not in markets:
                continue
            if not (
                _odds_sources.event_matches(record, label)
                or _odds_sources._event_id_matches(record, comparison.get("event_id"))
            ):
                continue
            if book_key is not None and record.get("book") != book_key:
                continue
            records.append(record)
    if len({record.get("source") for record in records}) > 1:
        records = _odds_sources.merge_odds(records)
    records.sort(key=lambda record: str(record.get("last_update") or ""), reverse=True)
    return records[:clamped]


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
