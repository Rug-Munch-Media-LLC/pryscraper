"""First-half / second-half and quarter (period) betting markets.

Books publish same-game markets for discrete game segments — first half,
second half and (for basketball) quarters — as moneyline, spread and
over/under markets. This module exposes them through a single event-driven
call.

Source
------
Only **The Odds API** publishes period markets in the schema this module
reads (``h1``, ``h2``, ``q1``..``q4`` plus their ``_spreads``/``_totals``
variants), via the v4 per-event odds endpoint. It requires a free API key
(https://the-odds-api.com) via the ``PRY_ODDS_API_KEY`` env var. ESPN
publishes no half/quarter odds feed, so without a key this module returns
``[]`` rather than fabricating lines — the same degradation contract as
:func:`sports_data.props.get_game_props`. Each requested period market
counts against the Odds API free-tier quota, so the per-sport market sets
(``_PERIOD_MARKETS``) are kept to the keys books actually price.

Contract
--------
* :func:`get_half_quarters` — async, never raises, returns a ``list``
  (``[]`` on failure / no key / no period markets for the sport). One record
  per (event, period, book, market).

Result shapes
-------------
``get_half_quarters`` returns a list of:

    {
        "event": "Celtics @ Lakers",
        "event_id": "nba:eid123",
        "sport": "nba",
        "period": "first_half",   # first_half | second_half | q1..q4
        "market": "h1_totals",    # raw Odds API market key
        "home_odds": 1.91,        # moneyline/spread price or Over price
        "away_odds": 1.95,        # moneyline/spread price or Under price
        "total": 112.5,           # totals markets only, else None
        "line": None,             # spread markets only (home perspective)
        "book": "draftkings",
        "source": "the_odds_api",
    }

The ``period`` values are normalized: ``h1`` -> ``first_half``, ``h2`` ->
``second_half``, ``q1``..``q4`` unchanged.

Backoff: 1 retry, exponential (0.1s -> 0.4s). Free-API terms:
https://the-odds-api.com.

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
import os
from typing import Any
from urllib.parse import quote

import httpx

from retry import RetryConfig, async_retry

# Guarded import: sports_data.odds is owned by a parallel agent and may not
# exist yet when this module is first imported.
try:
    from sports_data.odds import (
        _SPORTS,
        _bookmaker_params,
        _canonical_book,
        _resolve_sports,
    )
except ImportError:  # pragma: no cover - parallel build guard
    _SPORTS = {}  # type: ignore[assignment]
    _bookmaker_params = None  # type: ignore[assignment]
    _canonical_book = None  # type: ignore[assignment]
    _resolve_sports = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

_ODDS_BASE = "https://api.the-odds-api.com/v4/sports"

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
_ODDS_API_REGIONS = "us"

# Period markets per canonical sport key. Kept to what books actually price;
# each market counts against the Odds API free-tier quota.
_PERIOD_MARKETS: dict[str, tuple[str, ...]] = {
    "basketball_nba": (
        "h1",
        "h2",
        "h1_spreads",
        "h2_spreads",
        "h1_totals",
        "h2_totals",
        "q1",
        "q2",
        "q3",
        "q4",
        "q1_spreads",
        "q2_spreads",
        "q3_spreads",
        "q4_spreads",
        "q1_totals",
        "q2_totals",
        "q3_totals",
        "q4_totals",
    ),
    "basketball_ncaab": (
        "h1",
        "h2",
        "h1_spreads",
        "h2_spreads",
        "h1_totals",
        "h2_totals",
        "q1",
        "q2",
        "q3",
        "q4",
        "q1_totals",
        "q2_totals",
        "q3_totals",
        "q4_totals",
    ),
    "basketball_wnba": (
        "h1",
        "h2",
        "h1_spreads",
        "h2_spreads",
        "h1_totals",
        "h2_totals",
        "q1",
        "q2",
        "q3",
        "q4",
        "q1_totals",
        "q2_totals",
        "q3_totals",
        "q4_totals",
    ),
    "americanfootball_nfl": (
        "h1",
        "h2",
        "h1_spreads",
        "h2_spreads",
        "h1_totals",
        "h2_totals",
        "q1",
        "q2",
        "q3",
        "q4",
        "q1_totals",
        "q2_totals",
        "q3_totals",
        "q4_totals",
    ),
    "americanfootball_ncaaf": (
        "h1",
        "h2",
        "h1_spreads",
        "h2_spreads",
        "h1_totals",
        "h2_totals",
        "q1",
        "q2",
        "q3",
        "q4",
        "q1_totals",
        "q2_totals",
        "q3_totals",
        "q4_totals",
    ),
    "americanfootball_cfl": (
        "h1",
        "h2",
        "h1_spreads",
        "h2_spreads",
        "h1_totals",
        "h2_totals",
    ),
    "soccer_epl": ("h1", "h2", "h1_totals", "h2_totals"),
    "soccer_spain_la_liga": ("h1", "h2", "h1_totals", "h2_totals"),
    "soccer_germany_bundesliga": ("h1", "h2", "h1_totals", "h2_totals"),
    "soccer_italy_serie_a": ("h1", "h2", "h1_totals", "h2_totals"),
    "soccer_uefa_champions_league": ("h1", "h2", "h1_totals", "h2_totals"),
    "soccer_usa_mls": ("h1", "h2", "h1_totals", "h2_totals"),
}

# Raw market key -> normalized period label.
_PERIOD_LABELS: dict[str, str] = {
    "h1": "first_half",
    "h2": "second_half",
    "q1": "q1",
    "q2": "q2",
    "q3": "q3",
    "q4": "q4",
}


def _api_key() -> str:
    """Return the configured The Odds API key (or '' when unset)."""
    return os.environ.get(_API_KEY_ENV, "").strip()


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


def _event_label(home: str | None, away: str | None) -> str | None:
    """Compose the conventional "Away @ Home" event label."""
    if not home or not away:
        return None
    return f"{away} @ {home}"


def _resolve_event(event_id: str) -> tuple[list[str], str]:
    """Split a (possibly sport-prefixed) event id into (sport slugs, id)."""
    raw = str(event_id or "").strip()
    prefix, _, rest = raw.partition(":")
    if rest:
        if _resolve_sports is not None:
            return _resolve_sports(prefix), rest
        return [], rest
    if _resolve_sports is not None:
        return _resolve_sports("all"), raw
    return [], raw


def _canonical_key(slug: str) -> str:
    """Map a resolved slug (alias or canonical) to the Odds API sport key."""
    try:
        return _SPORTS[slug][0]
    except (KeyError, TypeError):
        return slug


def _period_markets_for(slug: str) -> list[str]:
    """Return the period market keys available for a sport slug."""
    return list(_PERIOD_MARKETS.get(_canonical_key(slug), []))


def _period_label(market_key: str) -> str | None:
    """Map a raw market key (h1, h2, q1, h1_totals, ...) to a period label."""
    base = market_key.split("_", 1)[0]
    return _PERIOD_LABELS.get(base)


# ── Transport ───────────────────────────────────────────────────────────
async def _fetch_json(
    url: str, params: dict[str, str] | None = None
) -> dict[str, Any] | list[Any] | None:
    """GET ``url`` and return the parsed JSON (object or array), or ``None``."""

    async def _one() -> dict[str, Any] | list[Any]:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT, headers=_HEADERS, follow_redirects=True
        ) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            payload = response.json()
        if not isinstance(payload, (dict, list)):
            raise ValueError("sports period payload is not an object or array")
        return payload

    try:
        return await async_retry(_one, config=_RETRY_CONFIG)
    except (httpx.HTTPError, OSError, ValueError):
        return None


# ── The Odds API mapping ───────────────────────────────────────────────
def _map_period_event(
    raw: dict[str, Any], sport_slug: str, book_slug: str | None
) -> list[dict[str, Any]]:
    """Map one Odds API period-markets payload onto period records."""
    home = _as_text(raw.get("home_team"))
    away = _as_text(raw.get("away_team"))
    event = _event_label(home, away)
    event_id = _as_text(raw.get("id"))
    if not event or not event_id:
        return []
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
        if _canonical_book is not None:
            book = _canonical_book(_as_text(bk.get("key")) or title)
        else:
            book = str(title).strip().lower()
        if book_slug is not None and book != book_slug:
            continue
        markets = bk.get("markets")
        if not isinstance(markets, list):
            continue
        for mkt in markets:
            if not isinstance(mkt, dict):
                continue
            market_key = _as_text(mkt.get("key")) or ""
            period = _period_label(market_key)
            if period is None:
                continue
            outcomes = mkt.get("outcomes")
            if not isinstance(outcomes, list):
                continue
            record = _parse_period_outcomes(
                outcomes, market_key, period, home, away, event, event_id, sport_slug, book
            )
            if record is not None:
                records.append(record)
    return records


def _parse_period_outcomes(
    outcomes: list[Any],
    market_key: str,
    period: str,
    home: str | None,
    away: str | None,
    event: str,
    event_id: str,
    sport_slug: str,
    book: str,
) -> dict[str, Any] | None:
    """Parse one period market's outcomes into a canonical record."""
    base: dict[str, Any] = {
        "event": event,
        "event_id": event_id,
        "sport": sport_slug,
        "period": period,
        "market": market_key,
        "home_odds": None,
        "away_odds": None,
        "total": None,
        "line": None,
        "book": book,
        "source": "the_odds_api",
    }
    suffix = market_key.split("_", 1)[1] if "_" in market_key else ""
    if suffix == "totals":
        over_odds = under_odds = None
        total: float | None = None
        for outcome in outcomes:
            if not isinstance(outcome, dict):
                continue
            label = str(outcome.get("name") or "").strip().lower()
            price = _to_float(outcome.get("price"))
            point = _to_float(outcome.get("point"))
            if price is None:
                continue
            if label in {"over", "o"}:
                over_odds, total = price, point
            elif label in {"under", "u"}:
                under_odds, total = price, point
        if over_odds is None and under_odds is None:
            return None
        base["home_odds"] = over_odds
        base["away_odds"] = under_odds
        base["total"] = total
        return base
    if suffix == "spreads":
        for outcome in outcomes:
            if not isinstance(outcome, dict):
                continue
            team_name = _as_text(outcome.get("name"))
            price = _to_float(outcome.get("price"))
            point = _to_float(outcome.get("point"))
            if team_name is None or price is None or point is None:
                continue
            if home and team_name.casefold() == home.casefold():
                base["home_odds"] = price
                base["line"] = point
            elif away and team_name.casefold() == away.casefold():
                base["away_odds"] = price
                if base["line"] is None:
                    base["line"] = -point
        if base["home_odds"] is None and base["away_odds"] is None:
            return None
        return base
    # Moneyline (h1, h2, q1..q4): outcomes named by team.
    for outcome in outcomes:
        if not isinstance(outcome, dict):
            continue
        team_name = _as_text(outcome.get("name"))
        price = _to_float(outcome.get("price"))
        if team_name is None or price is None:
            continue
        if home and team_name.casefold() == home.casefold():
            base["home_odds"] = price
        elif away and team_name.casefold() == away.casefold():
            base["away_odds"] = price
    if base["home_odds"] is None and base["away_odds"] is None:
        return None
    return base


async def _half_quarters_odds_api(
    event_id: str, sport_slug: str, book_slug: str | None
) -> list[dict[str, Any]]:
    """Fetch real period markets from The Odds API for one event."""
    key = _api_key()
    if not key:
        return []
    market_keys = _period_markets_for(sport_slug)
    if not market_keys:
        return []
    odds_key, _espn = _SPORTS[sport_slug]
    url = f"{_ODDS_BASE}/{quote(odds_key)}/events/{quote(event_id)}/odds"
    params: dict[str, str] = {
        "apiKey": key,
        "regions": _ODDS_API_REGIONS,
        "markets": ",".join(market_keys),
        "oddsFormat": "decimal",
    }
    if book_slug is not None and _bookmaker_params is not None:
        api_book = _bookmaker_params(book_slug)
        if api_book:
            params["bookmakers"] = api_book
    payload = await _fetch_json(url, params)
    if not isinstance(payload, dict):
        return []
    return _map_period_event(payload, sport_slug, book_slug)


# ── Public API ─────────────────────────────────────────────────────────
async def get_half_quarters(event_id: str, book: str = "all") -> list[dict[str, Any]]:
    """Fetch first-half/second-half and quarter markets for one event.

    Args:
        event_id: The event id. Accepts an optional ``sport:event_id`` prefix
            (e.g. ``nba:eid123`` or ``basketball_nba:...``) to skip the
            default-sport scan.
        book: Optional single-book filter (e.g. ``"draftkings"``). Default
            ``"all"``.

    Returns:
        A list of period records (see module docstring). ``[]`` on failure,
        when no Odds API key is configured, or when the sport has no period
        markets. Never raises.
    """
    try:
        return await _get_half_quarters(event_id, book)
    except Exception:
        logger.exception("sports_half_quarters_crashed", extra={"event_id": event_id})
        return []


async def _get_half_quarters(event_id: str, book: str) -> list[dict[str, Any]]:
    if not event_id or not str(event_id).strip():
        return []
    slugs, target_id = _resolve_event(event_id)
    if not slugs:
        logger.warning("sports_half_quarters_invalid_sport", extra={"event_id": event_id})
        return []
    if not _api_key():
        # ESPN publishes no period/quarter odds feed — return empty rather
        # than fabricate lines (same contract as props.get_game_props).
        return []
    book_slug = None
    if _canonical_book is not None and str(book or "").strip().lower() not in {"", "all"}:
        book_slug = _canonical_book(book)
    for slug in slugs:
        records = await _half_quarters_odds_api(target_id, slug, book_slug)
        if records:
            return records
    return []
