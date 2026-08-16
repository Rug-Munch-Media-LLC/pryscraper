"""Live sports betting odds — The Odds API (free tier) + ESPN scoreboard fallback.

Two free sources are aggregated here:

* **The Odds API** (``api.the-odds-api.com``) — the market-standard live
  odds feed used by betting bots. Requires a free API key
  (https://the-odds-api.com) via the ``PRY_ODDS_API_KEY`` env var. The free
  tier is 500 requests/month and covers upcoming events only (historical
  endpoints are paid). Used whenever a key is configured.
* **ESPN public scoreboards** (``site.api.espn.com``) — no key, no quota.
  When no key is configured (or the Odds API call fails) the module degrades
  to the ``odds`` block ESPN publishes on each competition (moneyline,
  converted to decimal). Coverage varies by league and window; when ESPN
  publishes no odds the module returns ``[]`` (never raises).

Contract
--------
* :func:`get_odds` — async, never raises, returns a ``list`` (``[]`` on
  failure). One record per (event, bookmaker, market).
* :func:`get_event_odds` — async, never raises, returns a ``dict`` (``{}``
  on failure). Multi-sportsbook comparison for one event id.

Result shapes
-------------
``get_odds`` returns a list of:

    {
        "sport": "nba",
        "event": "Celtics @ Lakers",
        "event_id": "bda33adc...",
        "market": "h2h",
        "bookmaker": "DraftKings",
        "home_odds": 1.85,
        "away_odds": 2.10,
        "last_update": "2026-08-16T12:00:00Z",
        "source": "the_odds_api",
    }

``get_event_odds`` returns:

    {
        "event_id": "bda33adc...",
        "sport": "nba",
        "event": "Celtics @ Lakers",
        "commence_time": "2026-08-17T00:00:00Z",
        "bookmakers": [
            {
                "key": "draftkings",
                "title": "DraftKings",
                "markets": [
                    {"key": "h2h", "outcomes": [{"name": "Celtics", "price": 1.85}, ...]}
                ],
            },
        ],
    }

Sport names accepted: ``nba``, ``nfl``, ``mlb``, ``nhl``, ``ncaab``,
``ncaaf``, ``epl``, ``mls``, ``wnba``, ``ufc``, ``cfl`` (or the Odds API key
style directly, e.g. ``basketball_nba``). ``"all"`` (default) queries the
most popular sports: nba, nfl, epl.

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

import logging
import os
from typing import Any
from urllib.parse import quote

import httpx

from retry import RetryConfig, async_retry

logger = logging.getLogger(__name__)

# Canonical slug → (The Odds API sport key, (ESPN sport, ESPN league)).
# Keep entries cheap to query: each slug in a "all" run costs one request.
_SPORTS: dict[str, tuple[str, tuple[str, str]]] = {
    "nba": ("basketball_nba", ("basketball", "nba")),
    "nfl": ("americanfootball_nfl", ("americanfootball", "nfl")),
    "mlb": ("baseball_mlb", ("baseball", "mlb")),
    "nhl": ("icehockey_nhl", ("icehockey", "nhl")),
    "ncaab": ("basketball_ncaab", ("basketball", "mens-college-basketball")),
    "ncaaf": ("americanfootball_ncaaf", ("americanfootball", "college-football")),
    "epl": ("soccer_epl", ("soccer", "eng.1")),
    "mls": ("soccer_usa_mls", ("soccer", "usa.1")),
    "wnba": ("basketball_wnba", ("basketball", "wnba")),
    "ufc": ("mma_ufc", ("mma", "ufc")),
    "cfl": ("americanfootball_cfl", ("americanfootball", "cfl")),
}

# The Odds API free tier is quota-bound (500 req/month); "all" never queries
# the full sport list. These are the sports betting bots care about most.
_DEFAULT_SPORTS: tuple[str, ...] = ("nba", "nfl", "epl")

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
_ODDS_API_MARKETS = "h2h"


def _api_key() -> str:
    """Return the configured The Odds API key (or '' when unset)."""
    return os.environ.get(_API_KEY_ENV, "").strip()


def _resolve_sports(sport: str) -> list[str]:
    """Map a ``sport`` parameter to the list of canonical slugs to query.

    ``""`` / ``"all"`` → the default sports; a known name or an Odds API key
    (e.g. ``basketball_nba``) → that one sport; anything unknown → ``[]``
    (callers treat this as "invalid sport, return empty").
    """
    raw = str(sport or "").strip().lower()
    if raw in {"", "all"}:
        return list(_DEFAULT_SPORTS)
    if raw in _SPORTS:
        return [raw]
    for name, (odds_key, _espn) in _SPORTS.items():
        if raw == odds_key:
            return [name]
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


# ── Fetching ───────────────────────────────────────────────────────────
async def _fetch_json(
    url: str, params: dict[str, str] | None = None
) -> dict[str, Any] | list[Any] | None:
    """GET ``url`` and return the parsed JSON (object or array), or ``None`` on failure."""

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
def _map_odds_event(raw: dict[str, Any], sport_slug: str) -> list[dict[str, Any]]:
    """Map one The Odds API event object onto canonical odds records."""
    home = _as_text(raw.get("home_team"))
    away = _as_text(raw.get("away_team"))
    event = _event_label(home, away)
    if not event:
        return []
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
        last_update = _as_text(bk.get("last_update")) or commence
        markets = bk.get("markets")
        if not isinstance(markets, list):
            continue
        for mkt in markets:
            if not isinstance(mkt, dict):
                continue
            market = _as_text(mkt.get("key")) or "h2h"
            home_price: float | None = None
            away_price: float | None = None
            outcomes = mkt.get("outcomes")
            if not isinstance(outcomes, list):
                continue
            for outcome in outcomes:
                if not isinstance(outcome, dict):
                    continue
                price = _to_float(outcome.get("price"))
                if price is None:
                    continue
                name = _as_text(outcome.get("name"))
                if name is None:
                    continue
                if name.lower() == str(home).lower():
                    home_price = price
                elif name.lower() == str(away).lower():
                    away_price = price
            if home_price is None and away_price is None:
                continue
            records.append(
                {
                    "sport": sport_slug,
                    "event": event,
                    "event_id": event_id,
                    "market": market,
                    "bookmaker": title,
                    "home_odds": home_price,
                    "away_odds": away_price,
                    "last_update": last_update,
                    "source": "the_odds_api",
                }
            )
    return records


def _map_event_comparison(raw: dict[str, Any], sport_slug: str) -> dict[str, Any]:
    """Map a single-event Odds API payload onto the comparison dict."""
    home = _as_text(raw.get("home_team"))
    away = _as_text(raw.get("away_team"))
    event = _event_label(home, away) or ""
    bookmakers: list[dict[str, Any]] = []
    raw_bookmakers = raw.get("bookmakers")
    if isinstance(raw_bookmakers, list):
        for bk in raw_bookmakers:
            if not isinstance(bk, dict):
                continue
            markets: list[dict[str, Any]] = []
            raw_markets = bk.get("markets")
            if isinstance(raw_markets, list):
                for mkt in raw_markets:
                    if not isinstance(mkt, dict):
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
                        markets.append(
                            {
                                "key": _as_text(mkt.get("key")) or "h2h",
                                "outcomes": outcomes,
                            }
                        )
            bookmakers.append(
                {
                    "key": _as_text(bk.get("key")),
                    "title": _as_text(bk.get("title")) or _as_text(bk.get("key")),
                    "markets": markets,
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
    comp: dict[str, Any], sport_slug: str, home: str | None, away: str | None
) -> list[dict[str, Any]]:
    """Map the ESPN ``odds`` block of one competition onto canonical records."""
    event = _event_label(home, away)
    if not event:
        return []
    odds_list = comp.get("odds")
    if not isinstance(odds_list, list):
        return []
    records: list[dict[str, Any]] = []
    for odd in odds_list:
        if not isinstance(odd, dict):
            continue
        provider = odd.get("provider")
        title = _as_text(provider.get("name")) if isinstance(provider, dict) else None
        if not title:
            continue
        home_ml = _american_to_decimal(
            odd.get("homeTeamOdds", {}).get("moneyLine")
            if isinstance(odd.get("homeTeamOdds"), dict)
            else None
        )
        away_ml = _american_to_decimal(
            odd.get("awayTeamOdds", {}).get("moneyLine")
            if isinstance(odd.get("awayTeamOdds"), dict)
            else None
        )
        if home_ml is None and away_ml is None:
            continue
        records.append(
            {
                "sport": sport_slug,
                "event": event,
                "event_id": _as_text(comp.get("id")),
                "market": "h2h",
                "bookmaker": title,
                "home_odds": home_ml,
                "away_odds": away_ml,
                "last_update": None,
                "source": "espn",
            }
        )
    return records


def _espn_odds_to_comparison(
    comp: dict[str, Any], sport_slug: str, event_id: str
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
            outcomes: list[dict[str, Any]] = []
            home_ml = _american_to_decimal(
                odd.get("homeTeamOdds", {}).get("moneyLine")
                if isinstance(odd.get("homeTeamOdds"), dict)
                else None
            )
            away_ml = _american_to_decimal(
                odd.get("awayTeamOdds", {}).get("moneyLine")
                if isinstance(odd.get("awayTeamOdds"), dict)
                else None
            )
            if home_ml is not None and home is not None:
                outcomes.append({"name": home, "price": home_ml})
            if away_ml is not None and away is not None:
                outcomes.append({"name": away, "price": away_ml})
            if outcomes:
                bookmakers.append(
                    {
                        "key": None,
                        "title": title,
                        "markets": [{"key": "h2h", "outcomes": outcomes}],
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
    espn_sport: str, espn_league: str, sport_slug: str
) -> list[dict[str, Any]]:
    """Fetch one ESPN scoreboard and flatten its odds blocks into records."""
    url = _ESPN_SCOREBOARD.format(sport=espn_sport, league=espn_league)
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
        records.extend(_espn_odds_to_records(comp, sport_slug, home, away))
    return records


async def _espn_find_event(
    espn_sport: str, espn_league: str, sport_slug: str, event_id: str
) -> dict[str, Any] | None:
    """Find one event on an ESPN scoreboard and build its odds comparison."""
    url = _ESPN_SCOREBOARD.format(sport=espn_sport, league=espn_league)
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
            comparison = _espn_odds_to_comparison(comp, sport_slug, event_id)
            if comparison.get("bookmakers"):
                return comparison
    return None


# ── Public API ─────────────────────────────────────────────────────────
async def get_odds(
    event_query: str = "", sport: str = "all", limit: int = 20
) -> list[dict[str, Any]]:
    """Fetch live odds across bookmakers for one or more sports.

    Args:
        event_query: Optional substring filter against event labels (e.g.
            ``"celtics"``). Empty matches everything.
        sport: Sport name (see module docstring) or ``"all"`` (default).
        limit: Max records to return (1-100).

    Returns:
        A list of odds records (see module docstring). ``[]`` on failure or
        invalid sport. Never raises.
    """
    try:
        return await _get_odds(event_query, sport, limit)
    except Exception:
        logger.exception("sports_odds_crashed", extra={"event_query": event_query, "sport": sport})
        return []


async def _get_odds(event_query: str, sport: str, limit: int) -> list[dict[str, Any]]:
    slugs = _resolve_sports(sport)
    if not slugs:
        logger.warning("sports_odds_invalid_sport", extra={"sport": sport})
        return []
    clamped = max(1, min(int(limit), _MAX_LIMIT))
    key = _api_key()
    records: list[dict[str, Any]] = []
    for slug in slugs:
        odds_key, (espn_sport, espn_league) = _SPORTS[slug]
        if key:
            url = f"{_ODDS_BASE}/{quote(odds_key)}/odds"
            params = {
                "apiKey": key,
                "regions": _ODDS_API_REGIONS,
                "markets": _ODDS_API_MARKETS,
                "oddsFormat": "decimal",
            }
            payload = await _fetch_json(url, params)
            if isinstance(payload, list):
                for raw in payload:
                    if isinstance(raw, dict):
                        records.extend(_map_odds_event(raw, slug))
        else:
            records.extend(await _espn_odds_for_league(espn_sport, espn_league, slug))
    query = (event_query or "").strip().lower()
    if query:
        records = [
            record
            for record in records
            if query in str(record.get("event") or "").lower()
            or query in str(record.get("sport") or "").lower()
        ]
    records.sort(key=lambda record: str(record.get("last_update") or ""), reverse=True)
    return records[:clamped]


async def get_event_odds(event_id: str) -> dict[str, Any]:
    """Fetch multi-sportsbook odds for a single event.

    Args:
        event_id: The event id. Accepts an optional ``sport:event_id`` prefix
            (e.g. ``nba:bda33adc...`` or ``basketball_nba:...``) to skip the
            default-sport scan.

    Returns:
        A comparison dict (see module docstring) or ``{}`` on failure
        (unknown event, network error). Never raises.
    """
    try:
        return await _get_event_odds(event_id)
    except Exception:
        logger.exception("sports_event_odds_crashed", extra={"event_id": event_id})
        return {}


async def _get_event_odds(event_id: str) -> dict[str, Any]:
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
    for slug in candidates:
        odds_key, (espn_sport, espn_league) = _SPORTS[slug]
        if key:
            url = f"{_ODDS_BASE}/{quote(odds_key)}/events/{quote(target_id)}/odds"
            params = {
                "apiKey": key,
                "regions": _ODDS_API_REGIONS,
                "markets": _ODDS_API_MARKETS,
                "oddsFormat": "decimal",
            }
            payload = await _fetch_json(url, params)
            if isinstance(payload, dict) and payload.get("id"):
                return _map_event_comparison(payload, slug)
        else:
            comparison = await _espn_find_event(espn_sport, espn_league, slug, target_id)
            if comparison is not None:
                return comparison
    return {}
