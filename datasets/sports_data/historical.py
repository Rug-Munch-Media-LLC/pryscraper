"""Closing-line history + backtesting data — The Odds API v4 historical endpoint.

The Odds API's ``/v4/historical/sports/{sport}/odds`` endpoint returns the
odds snapshot for every event of a sport at a single timestamp in the past
(the ``date`` param, ISO-8601). That is the only supported way to get
closing-line history for backtesting a "money printer" strategy:

* :func:`get_historical_odds` pulls the per-book odds for one event at one
  timestamp (default: the most recent snapshot, i.e. the closing line).
* :func:`get_closing_line` resolves the event's sport via the live odds
  comparison, snaps the historical feed at the event's commence time, and
  returns the best closing price per book plus the single best price per side.

Like every other :mod:`sports_data` module, both functions are async and
never raise — they degrade to ``[]`` / ``{}`` on any failure. The historical
endpoint is **paid** on The Odds API (the free 500 req/month tier covers
upcoming events only), so without a ``PRY_ODDS_API_KEY`` both functions
return empty results immediately (key-gated).

Result shapes
-------------
``get_historical_odds`` returns a list of:

    {
        "book": "pinnacle",
        "odds": {"home": 1.95, "away": 1.90},
        "updated_at": "2026-08-15T23:55:00Z",
    }

``odds`` holds decimal moneyline prices keyed by side. The ``home``/``away``
mapping is resolved by team name from the event payload, falling back to The
Odds API's documented h2h ordering (away outcome first) when names do not
match. Records are sorted by book name.

``get_closing_line`` returns:

    {
        "event_id": "eid123",
        "sport": "nba",
        "event": "Boston Celtics @ Los Angeles Lakers",
        "closing": {
            "pinnacle": {"home": 1.95, "away": 1.90},
            "draftkings": {"home": 2.00, "away": 1.85},
        },
        "best": {
            "home": {"book": "draftkings", "odds": 2.00},
            "away": {"book": "pinnacle", "odds": 1.90},
        },
        "source": "the_odds_api",
    }

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
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

import httpx

from pry.engine.retry import RetryConfig, async_retry

logger = logging.getLogger(__name__)

# The Odds API v4 historical odds endpoint (paid tier). The ``{sport}``
# placeholder is the canonical sport key (e.g. ``basketball_nba``).
_HIST_BASE = "https://api.the-odds-api.com/v4/historical/sports/{sport}/odds"

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

# Short aliases (as returned by sports_data.odds) -> canonical The Odds API
# sport keys. Anything not listed is passed through untouched so canonical
# keys keep working.
_CANONICAL_SPORTS: dict[str, str] = {
    "nba": "basketball_nba",
    "wnba": "basketball_wnba",
    "ncaab": "basketball_ncaab",
    "nfl": "americanfootball_nfl",
    "ncaaf": "americanfootball_ncaaf",
    "mlb": "baseball_mlb",
    "nhl": "icehockey_nhl",
    "epl": "soccer_epl",
    "mls": "soccer_usa_mls",
    "ufc": "mma_mixed_martial_arts",
}

# Guarded import: sports_data.odds is owned by a parallel agent and may not
# exist yet when this module is first imported.
try:
    from datasets.sports_data.odds import get_event_odds as _get_event_odds
except ImportError:  # pragma: no cover - parallel build guard
    _get_event_odds = None  # type: ignore[assignment]


def _api_key() -> str:
    """Return the configured The Odds API key (or '' when unset)."""
    return os.environ.get(_API_KEY_ENV, "").strip()


def _canonical_sport(sport: str) -> str:
    """Map a short alias to its canonical The Odds API sport key."""
    raw = str(sport or "").strip().lower()
    if not raw:
        return ""
    return _CANONICAL_SPORTS.get(raw, raw)


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


async def _fetch_json(
    url: str, params: dict[str, str] | None = None
) -> dict[str, Any] | list[Any] | None:
    """GET ``url`` and parse JSON with retry/backoff (never raises)."""

    async def _one() -> dict[str, Any] | list[Any]:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT, headers=_HEADERS, follow_redirects=True
        ) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            payload = response.json()
        if not isinstance(payload, (dict, list)):
            raise ValueError("historical odds payload is not an object or array")
        return payload

    try:
        return await async_retry(_one, config=_RETRY_CONFIG)
    except (httpx.HTTPError, OSError, ValueError):
        return None


def _book_outcome_prices(book: dict[str, Any], market: str) -> dict[str, float]:
    """Collect ``{outcome_name: decimal_price}`` for one book + market."""
    prices: dict[str, float] = {}
    markets = book.get("markets")
    if not isinstance(markets, list):
        return prices
    for mkt in markets:
        if not isinstance(mkt, dict):
            continue
        if str(mkt.get("key") or "") != market:
            continue
        outcomes = mkt.get("outcomes")
        if not isinstance(outcomes, list):
            continue
        for outcome in outcomes:
            if not isinstance(outcome, dict):
                continue
            name = _as_text(outcome.get("name"))
            price = _to_float(outcome.get("price"))
            if name is not None and price is not None and price > 1.0:
                prices[name] = round(price, 4)
    return prices


def _record_from_book(
    book: dict[str, Any],
    prices: dict[str, float],
    home_team: str | None,
    away_team: str | None,
) -> dict[str, Any] | None:
    """Map one bookmaker's outcome prices onto ``{home, away}`` odds."""
    title = _as_text(book.get("title")) or _as_text(book.get("key"))
    if not title:
        return None
    home = prices.get(home_team) if home_team else None
    away = prices.get(away_team) if away_team else None
    if (home is None or away is None) and len(prices) >= 2:
        # The Odds API h2h outcomes are conventionally ordered [away, home].
        names = list(prices)
        if home is None:
            home = prices.get(names[1])
        if away is None:
            away = prices.get(names[0])
    if home is None and away is None:
        return None
    return {
        "book": title,
        "odds": {"home": home, "away": away},
        "updated_at": _as_text(book.get("last_update")),
    }


def _parse_history(
    payload: dict[str, Any] | list[Any] | None, event_id: str
) -> list[dict[str, Any]]:
    """Extract per-book odds records from a historical odds response."""
    if not isinstance(payload, dict):
        return []
    data = payload.get("data")
    if not isinstance(data, list):
        return []
    records: list[dict[str, Any]] = []
    for event in data:
        if not isinstance(event, dict):
            continue
        if event_id and str(event.get("id") or "") != event_id:
            continue
        home_team = _as_text(event.get("home_team"))
        away_team = _as_text(event.get("away_team"))
        bookmakers = event.get("bookmakers")
        if not isinstance(bookmakers, list):
            continue
        for book in bookmakers:
            prices = _book_outcome_prices(book, "h2h")
            record = _record_from_book(book, prices, home_team, away_team)
            if record is not None:
                records.append(record)
    records.sort(key=lambda record: str(record.get("book") or ""))
    return records


async def get_historical_odds(
    sport: str,
    event_id: str,
    market: str = "h2h",
    date: str | None = None,
) -> list[dict[str, Any]]:
    """Fetch closing-line odds history for one event (key-gated, never raises).

    Args:
        sport: Sport key — canonical (``basketball_nba``) or a short alias
            (``nba``). Unknown sports resolve to ``[]`` (upstream 404).
        event_id: The Odds API event id.
        market: Market to pull (default ``"h2h"`` moneyline).
        date: ISO-8601 snapshot timestamp; ``None`` (default) uses the most
            recent snapshot (effectively the closing line).

    Returns:
        Per-book records ``{book, odds: {home, away}, updated_at}`` sorted by
        book name, or ``[]`` when the key is missing, the event is unknown,
        or the upstream call fails.
    """
    sport_key = _canonical_sport(sport)
    target_id = str(event_id or "").strip()
    if not sport_key or not target_id:
        return []
    key = _api_key()
    if not key:
        return []
    snapshot = str(date or "").strip() or datetime.now(UTC).isoformat()
    params: dict[str, str] = {
        "apiKey": key,
        "regions": _ODDS_API_REGIONS,
        "markets": str(market or "h2h"),
        "oddsFormat": "decimal",
        "eventIds": target_id,
        "date": snapshot,
    }
    url = _HIST_BASE.format(sport=quote(sport_key))
    payload = await _fetch_json(url, params)
    return _parse_history(payload, target_id)


async def _load_event_odds(event_id: str) -> dict[str, Any]:
    """Fetch the live multi-sportsbook comparison (never raises)."""
    if _get_event_odds is None:
        return {}
    try:
        return await _get_event_odds(event_id)
    except Exception:
        logger.exception("sports_historical_event_odds_failed", extra={"event_id": event_id})
        return {}


def _best_closing(closing: dict[str, Any]) -> dict[str, Any]:
    """Pick the best (highest) closing price per side across books."""
    best: dict[str, Any] = {}
    for side in ("home", "away"):
        candidates: list[tuple[str, float]] = []
        for book, odds in closing.items():
            if not isinstance(odds, dict):
                continue
            value = _to_float(odds.get(side))
            if value is not None:
                candidates.append((str(book), value))
        if candidates:
            book, value = max(candidates, key=lambda pair: pair[1])
            best[side] = {"book": book, "odds": round(value, 4)}
    return best


async def get_closing_line(event_id: str) -> dict[str, Any]:
    """Return the best closing odds per book for an event (never raises).

    Resolves the event's sport + commence time from the live odds
    comparison, then snaps the historical feed at commence time (the last
    snapshot before kickoff = the closing line). Returns ``{}`` when the
    event is unknown, the historical endpoint is unavailable, or no
    ``PRY_ODDS_API_KEY`` is configured.
    """
    target_id = str(event_id or "").strip()
    if not target_id:
        return {}
    comparison = await _load_event_odds(target_id)
    if not comparison:
        return {}
    sport_key = _canonical_sport(str(comparison.get("sport") or ""))
    commence = _as_text(comparison.get("commence_time"))
    date = commence or datetime.now(UTC).isoformat()
    history = await get_historical_odds(sport_key, target_id, market="h2h", date=date)
    if not history:
        return {}
    closing: dict[str, Any] = {}
    for record in history:
        book = str(record.get("book") or "")
        odds = record.get("odds")
        if not book or not isinstance(odds, dict):
            continue
        if odds.get("home") is not None or odds.get("away") is not None:
            closing[book] = odds
    if not closing:
        return {}
    return {
        "event_id": str(comparison.get("event_id") or target_id),
        "sport": str(comparison.get("sport") or sport_key),
        "event": str(comparison.get("event") or ""),
        "closing": closing,
        "best": _best_closing(closing),
        "source": "the_odds_api",
    }
