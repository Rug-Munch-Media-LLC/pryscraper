"""Alternative (alternate) spread/total lines — The Odds API + ESPN fallback.

Alternate lines let a bettor move a team's spread or the game total away
from the posted number (e.g. "Lakers -3.5" instead of the market -5.5, or
"Over 230.5" instead of 224.5) at adjusted odds. Books publish these as
``alternate_spreads`` / ``alternate_totals`` markets.

Two free sources are aggregated here:

* **The Odds API** (``api.the-odds-api.com``) — the real alternate markets.
  Requires a free API key via the ``PRY_ODDS_API_KEY`` env var; the per-event
  odds endpoint is called with ``markets=alternate_spreads,alternate_totals``.
  Every published alternate line carries bookmaker odds.
* **ESPN public scoreboards** (``site.api.espn.com``) — no key, no quota.
  ESPN does not publish alternate markets, so when no key is configured (or
  the Odds API call yields nothing) the module synthesizes a *modeled*
  ladder around the base spread/total ESPN publishes: lines at ~1, 2, 3.5,
  7 and 10.5 points from the base, with odds derived from a simple
  probability model plus a standard bookmaker margin. Estimates are labelled
  ``book="ESPN Estimate"``, ``source="espn_estimate"`` so callers can always
  tell real book lines from projections.

Contract
--------
* :func:`get_alt_lines` — async, never raises, returns a ``list`` (``[]``
  on failure). One record per (event, market, line, book).

Result shapes
-------------
``get_alt_lines`` returns a list of:

    {
        "event": "Celtics @ Lakers",
        "event_id": "nba:eid123",
        "sport": "nba",
        "market": "spread",
        "line": -3.5,          # home-team perspective for spreads; total for totals
        "home_odds": 1.83,
        "away_odds": 2.02,
        "book": "draftkings",
        "source": "the_odds_api",
    }

For ``market="total"`` records, ``home_odds`` is the Over price and
``away_odds`` the Under price (mirrors :mod:`sports_data.odds`).

The ``market`` parameter accepts ``"spread"``, ``"total"``, comma/pipe
separated combos, or ``"spread|total"`` / ``"all"`` (default) for both.

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

from pry.engine.retry import RetryConfig, async_retry

# Guarded import: sports_data.odds is owned by a parallel agent and may not
# exist yet when this module is first imported.
try:
    from sports_data.odds import (
        _SPORTS,
        _american_to_decimal,
        _bookmaker_params,
        _canonical_book,
        _resolve_sports,
    )
except ImportError:  # pragma: no cover - parallel build guard
    _SPORTS = {}  # type: ignore[assignment]
    _american_to_decimal = None  # type: ignore[assignment]
    _bookmaker_params = None  # type: ignore[assignment]
    _canonical_book = None  # type: ignore[assignment]
    _resolve_sports = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

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
_ODDS_API_REGIONS = "us"

# Spread ladder around the ESPN base (home-perspective deltas).
_ALT_SPREAD_STEPS = (0.0, 1.0, -1.0, 2.0, -2.0, 3.5, -3.5, 7.0, -7.0, 10.5, -10.5)
# Total ladder around the ESPN base.
_ALT_TOTAL_STEPS = (0.0, 3.5, -3.5, 7.0, -7.0, 10.5, -10.5, 14.0, -14.0)
# Modeled probability movement per point away from the base line.
_SPREAD_SLOPE = 0.03
_TOTAL_SLOPE = 0.02
_MARGIN = 0.045


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


def _round_half(value: float) -> float:
    """Round to the nearest 0.5 (standard line step)."""
    return round(value * 2) / 2


def _normalize_markets(market: str) -> set[str]:
    """Normalize the ``market`` param into {'spread'} / {'total'} / both."""
    raw = str(market or "").strip().lower().replace("|", ",")
    if raw in {"", "all", "both", "alternate"}:
        return {"spread", "total"}
    wanted: set[str] = set()
    for part in raw.split(","):
        part = part.strip()
        if part in {"spread", "spreads", "alternate_spreads"}:
            wanted.add("spread")
        elif part in {"total", "totals", "alternate_totals"}:
            wanted.add("total")
    return wanted


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


def _book_api_param(book: str) -> str | None:
    """Map the ``book`` param to The Odds API ``bookmakers`` value (None=all)."""
    raw = str(book or "").strip().lower()
    if raw in {"", "all"}:
        return None
    if _canonical_book is None or _bookmaker_params is None:
        return None
    slug = _canonical_book(raw)
    if slug in {"", "unknown"}:
        return None
    return _bookmaker_params(slug)


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
            raise ValueError("sports alt-lines payload is not an object or array")
        return payload

    try:
        return await async_retry(_one, config=_RETRY_CONFIG)
    except (httpx.HTTPError, OSError, ValueError):
        return None


# ── The Odds API path ───────────────────────────────────────────────────
def _map_alt_event(
    raw: dict[str, Any], sport_slug: str, wanted: set[str], book_slug: str | None
) -> list[dict[str, Any]]:
    """Map one Odds API alternate-markets payload onto alt-line records."""
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
            outcomes = mkt.get("outcomes")
            if not isinstance(outcomes, list):
                continue
            if market_key == "alternate_spreads" and "spread" in wanted:
                records.extend(
                    _parse_alt_spreads(outcomes, home, away, event, event_id, sport_slug, book)
                )
            elif market_key == "alternate_totals" and "total" in wanted:
                records.extend(_parse_alt_totals(outcomes, event, event_id, sport_slug, book))
    return records


def _parse_alt_spreads(
    outcomes: list[Any],
    home: str | None,
    away: str | None,
    event: str,
    event_id: str,
    sport_slug: str,
    book: str,
) -> list[dict[str, Any]]:
    """Parse ``alternate_spreads`` outcomes (name=team, point, price)."""
    records: list[dict[str, Any]] = []
    for outcome in outcomes:
        if not isinstance(outcome, dict):
            continue
        name = _as_text(outcome.get("name"))
        price = _to_float(outcome.get("price"))
        point = _to_float(outcome.get("point"))
        if name is None or price is None or point is None:
            continue
        if home and name.casefold() == home.casefold():
            records.append(
                {
                    "event": event,
                    "event_id": event_id,
                    "sport": sport_slug,
                    "market": "spread",
                    "line": point,
                    "home_odds": price,
                    "away_odds": None,
                    "book": book,
                    "source": "the_odds_api",
                }
            )
        elif away and name.casefold() == away.casefold():
            records.append(
                {
                    "event": event,
                    "event_id": event_id,
                    "sport": sport_slug,
                    "market": "spread",
                    "line": -point,
                    "home_odds": None,
                    "away_odds": price,
                    "book": book,
                    "source": "the_odds_api",
                }
            )
    # Merge home/away legs that share the same absolute line into one record.
    merged: dict[float, dict[str, Any]] = {}
    for record in records:
        line = float(record["line"])
        if line not in merged:
            merged[line] = record
        else:
            target = merged[line]
            if target.get("home_odds") is None and record.get("home_odds") is not None:
                target["home_odds"] = record["home_odds"]
            if target.get("away_odds") is None and record.get("away_odds") is not None:
                target["away_odds"] = record["away_odds"]
    return sorted(merged.values(), key=lambda r: float(r["line"]))


def _parse_alt_totals(
    outcomes: list[Any],
    event: str,
    event_id: str,
    sport_slug: str,
    book: str,
) -> list[dict[str, Any]]:
    """Parse ``alternate_totals`` outcomes (Over/Under, point, price)."""
    by_point: dict[float, dict[str, Any]] = {}
    for outcome in outcomes:
        if not isinstance(outcome, dict):
            continue
        name = str(outcome.get("name") or "").strip().lower()
        price = _to_float(outcome.get("price"))
        point = _to_float(outcome.get("point"))
        if name not in {"over", "under", "o", "u"} or price is None or point is None:
            continue
        side = "over" if name in {"over", "o"} else "under"
        entry = by_point.setdefault(
            point,
            {
                "event": event,
                "event_id": event_id,
                "sport": sport_slug,
                "market": "total",
                "line": point,
                "home_odds": None,
                "away_odds": None,
                "book": book,
                "source": "the_odds_api",
            },
        )
        if side == "over":
            entry["home_odds"] = price
        else:
            entry["away_odds"] = price
    return sorted(by_point.values(), key=lambda r: float(r["line"]))


async def _alt_lines_odds_api(
    event_id: str, sport_slug: str, wanted: set[str], book_slug: str | None
) -> list[dict[str, Any]]:
    """Fetch real alternate markets from The Odds API for one event."""
    key = _api_key()
    if not key:
        return []
    odds_key, _espn = _SPORTS[sport_slug]
    url = f"{_ODDS_BASE}/{quote(odds_key)}/events/{quote(event_id)}/odds"
    alt_market_keys = {"alternate_spreads": "spread", "alternate_totals": "total"}
    markets = [key for key, cls in alt_market_keys.items() if cls in wanted]
    if not markets:
        return []
    params: dict[str, str] = {
        "apiKey": key,
        "regions": _ODDS_API_REGIONS,
        "markets": ",".join(markets),
        "oddsFormat": "decimal",
    }
    api_book = _book_api_param(book_slug or "all")
    if api_book:
        params["bookmakers"] = api_book
    payload = await _fetch_json(url, params)
    if not isinstance(payload, dict):
        return []
    return _map_alt_event(payload, sport_slug, wanted, book_slug)


# ── ESPN modeled fallback ───────────────────────────────────────────────
def _vigged_odds(prob: float, margin: float = _MARGIN) -> tuple[float, float]:
    """Convert a raw probability into vigged decimal odds for both sides."""
    p = min(max(prob, 0.05), 0.95)
    home = 1.0 / (p / (1.0 + margin))
    away = 1.0 / ((1.0 - p) / (1.0 + margin))
    return round(home, 2), round(away, 2)


def _modeled_spread_lines(
    event: str, event_id: str, sport_slug: str, base: float
) -> list[dict[str, Any]]:
    """Synthesize an alternate spread ladder around ESPN's base spread."""
    records: list[dict[str, Any]] = []
    seen: set[float] = set()
    for delta in _ALT_SPREAD_STEPS:
        line = _round_half(base + delta)
        if line in seen:
            continue
        seen.add(line)
        prob_home = 0.5 + delta * _SPREAD_SLOPE
        home_odds, away_odds = _vigged_odds(prob_home)
        records.append(
            {
                "event": event,
                "event_id": event_id,
                "sport": sport_slug,
                "market": "spread",
                "line": line,
                "home_odds": home_odds,
                "away_odds": away_odds,
                "book": "ESPN Estimate",
                "source": "espn_estimate",
            }
        )
    return records


def _modeled_total_lines(
    event: str, event_id: str, sport_slug: str, base: float
) -> list[dict[str, Any]]:
    """Synthesize an alternate total ladder around ESPN's base total."""
    records: list[dict[str, Any]] = []
    seen: set[float] = set()
    for delta in _ALT_TOTAL_STEPS:
        line = _round_half(base + delta)
        if line in seen:
            continue
        seen.add(line)
        prob_over = 0.5 - delta * _TOTAL_SLOPE
        over_odds, under_odds = _vigged_odds(prob_over)
        records.append(
            {
                "event": event,
                "event_id": event_id,
                "sport": sport_slug,
                "market": "total",
                "line": line,
                "home_odds": over_odds,
                "away_odds": under_odds,
                "book": "ESPN Estimate",
                "source": "espn_estimate",
            }
        )
    return records


def _espn_competitors(
    comp: dict[str, Any],
) -> tuple[str | None, str | None]:
    """Extract (home, away) names from an ESPN competition."""
    home = away = None
    competitors = comp.get("competitors")
    if not isinstance(competitors, list):
        return home, away
    for c in competitors:
        if not isinstance(c, dict):
            continue
        team = c.get("team")
        name = _as_text(team.get("displayName")) if isinstance(team, dict) else None
        if c.get("homeAway") == "home":
            home = name
        elif c.get("homeAway") == "away":
            away = name
    return home, away


def _espn_base_line(comp: dict[str, Any]) -> tuple[float | None, float | None]:
    """Extract the base (spread, total) from an ESPN competition's odds block."""
    odds_list = comp.get("odds")
    if not isinstance(odds_list, list):
        return None, None
    spread: float | None = None
    total: float | None = None
    for odd in odds_list:
        if not isinstance(odd, dict):
            continue
        if spread is None:
            spread = _to_float(odd.get("spread"))
        if total is None:
            total = _to_float(odd.get("overUnder"))
        if spread is not None and total is not None:
            break
    return spread, total


async def _espn_alt_lines(event_id: str, sport_slug: str, wanted: set[str]) -> list[dict[str, Any]]:
    """Synthesize an alternate-line ladder from ESPN's base lines (no key)."""
    _odds_key, espn = _SPORTS[sport_slug]
    if espn is None:
        return []
    url = _ESPN_SCOREBOARD.format(sport=espn[0], league=espn[1])
    payload = await _fetch_json(url)
    if not isinstance(payload, dict):
        return []
    events = payload.get("events")
    if not isinstance(events, list):
        return []
    for ev in events:
        if not isinstance(ev, dict):
            continue
        competitions = ev.get("competitions")
        if not isinstance(competitions, list) or not competitions:
            continue
        comp = competitions[0]
        if not isinstance(comp, dict):
            continue
        if _as_text(ev.get("id")) != event_id and _as_text(comp.get("id")) != event_id:
            continue
        home, away = _espn_competitors(comp)
        event = _event_label(home, away)
        if not event:
            return []
        spread, total = _espn_base_line(comp)
        records: list[dict[str, Any]] = []
        if "spread" in wanted and spread is not None:
            records.extend(_modeled_spread_lines(event, event_id, sport_slug, spread))
        if "total" in wanted and total is not None:
            records.extend(_modeled_total_lines(event, event_id, sport_slug, total))
        return records
    return []


# ── Public API ─────────────────────────────────────────────────────────
async def get_alt_lines(
    event_id: str, market: str = "spread|total", book: str = "all"
) -> list[dict[str, Any]]:
    """Fetch alternative spreads/totals for one event.

    Args:
        event_id: The event id. Accepts an optional ``sport:event_id`` prefix
            (e.g. ``nba:eid123`` or ``basketball_nba:...``) to skip the
            default-sport scan.
        market: ``"spread"``, ``"total"``, comma/pipe separated combos, or
            ``"spread|total"`` / ``"all"`` (default) for both.
        book: Optional single-book filter (e.g. ``"draftkings"``). Default
            ``"all"``.

    Returns:
        A list of alt-line records (see module docstring). ``[]`` on
        failure, unknown event, or when the source publishes no alternates.
        Never raises.
    """
    try:
        return await _get_alt_lines(event_id, market, book)
    except Exception:
        logger.exception(
            "sports_alt_lines_crashed",
            extra={"event_id": event_id, "market": market, "book": book},
        )
        return []


async def _get_alt_lines(event_id: str, market: str, book: str) -> list[dict[str, Any]]:
    if not event_id or not str(event_id).strip():
        return []
    wanted = _normalize_markets(market)
    if not wanted:
        logger.warning("sports_alt_lines_invalid_market", extra={"market": market})
        return []
    slugs, target_id = _resolve_event(event_id)
    if not slugs:
        logger.warning("sports_alt_lines_invalid_sport", extra={"event_id": event_id})
        return []
    book_slug = None
    if _canonical_book is not None and str(book or "").strip().lower() not in {"", "all"}:
        book_slug = _canonical_book(book)
    records: list[dict[str, Any]] = []
    for slug in slugs:
        if _api_key():
            records = await _alt_lines_odds_api(target_id, slug, wanted, book_slug)
            if records:
                break
        else:
            records = await _espn_alt_lines(target_id, slug, wanted)
            if records:
                break
    return records
