"""Live scores + in-play odds — ESPN live scoreboards + The Odds API.

Two sources are aggregated here:

* **ESPN public scoreboards** (``site.api.espn.com``) — no key, no quota.
  In-progress competitions (``status.type.state == "in"``) carry live scores
  and a clock string in ``status.type.shortDetail`` (e.g. ``"Q3 5:32"``),
  plus an optional ``odds`` block (spread / over-under) per provider. NOTE:
  some egress IPs get 403 from ESPN — every parse is defensive and degrades
  to ``[]``.
* **The Odds API** (``api.the-odds-api.com``) — live odds merge. Requires a
  free API key via ``PRY_ODDS_API_KEY``. The v4 ``odds`` endpoint keeps
  returning events whose ``commence_time`` has passed while a game is live;
  those are treated as in-play and merged into the ESPN data. The Odds API
  publishes no scores, so ``live_score``/``clock`` are ``None`` for those
  records.

Contract
--------
* :func:`get_live_odds` — async, never raises, returns a ``list`` (``[]`` on
  failure). One record per (event, market, book).
* :func:`get_live_scores` — async, never raises, returns a ``list`` (``[]``
  on failure). One record per in-progress game.

Result shapes
-------------
``get_live_odds`` returns a list of:

    {
        "event": "Golden State Warriors @ Phoenix Suns",
        "market": "spread",
        "book": "DraftKings",
        "odds": -5.5,
        "live_score": "50 - 45",
        "clock": "Q2 4:11",
        "last_update": None,
    }

``get_live_scores`` returns a list of:

    {
        "sport": "nba",
        "event": "Golden State Warriors @ Phoenix Suns",
        "home": "Phoenix Suns",
        "away": "Golden State Warriors",
        "home_score": "45",
        "away_score": "50",
        "status": "In Progress",
        "clock": "Q2 4:11",
        "last_update": None,
    }

Sport names match :mod:`sports_data.odds`. Backoff: 1 retry, exponential
(0.1s -> 0.4s). Free-API terms: https://the-odds-api.com.

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

from retry import RetryConfig, async_retry
from sports_data.odds import _SPORTS, _resolve_sports

logger = logging.getLogger(__name__)

_ESPN_SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/scoreboard"
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

_MAX_LIMIT = 100
_ODDS_API_REGIONS = "us"
_ODDS_API_MARKETS = "h2h,spreads,totals"


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


def _parse_iso(value: str) -> datetime:
    """Parse an ISO-8601 timestamp; unparseable values map to "now"."""
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed
    except ValueError:
        return datetime.now(UTC)


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
            raise ValueError("sports live payload is not an object or array")
        return payload

    try:
        return await async_retry(_one, config=_RETRY_CONFIG)
    except (httpx.HTTPError, OSError, ValueError):
        return None


async def _espn_scoreboard(slug: str) -> dict[str, Any] | None:
    """Fetch one league's ESPN scoreboard (or ``None`` on failure/403)."""
    espn = _SPORTS[slug][1]
    if espn is None:
        return None
    espn_sport, espn_league = espn
    url = _ESPN_SCOREBOARD.format(sport=espn_sport, league=espn_league)
    payload = await _fetch_json(url)
    if isinstance(payload, dict):
        return payload
    return None


# ── ESPN mapping helpers ───────────────────────────────────────────────
def _status_blocks(comp: dict[str, Any], ev: dict[str, Any]) -> list[dict[str, Any]]:
    """Collect status.type dicts from competition then event level."""
    blocks: list[dict[str, Any]] = []
    for source in (comp, ev):
        status = source.get("status")
        if isinstance(status, dict):
            status_type = status.get("type")
            if isinstance(status_type, dict):
                blocks.append(status_type)
    return blocks


def _is_in_progress(comp: dict[str, Any], ev: dict[str, Any]) -> bool:
    """True when ESPN reports the game state as 'in' (live)."""
    for status_type in _status_blocks(comp, ev):
        state = str(status_type.get("state") or "").lower()
        if state == "in":
            return True
        if state:
            return False  # explicit pre/post state beats absence
    return False


def _status_description(comp: dict[str, Any], ev: dict[str, Any]) -> str | None:
    """Extract ESPN's status.description (e.g. 'In Progress')."""
    for status_type in _status_blocks(comp, ev):
        description = _as_text(status_type.get("description"))
        if description:
            return description
    return None


def _clock_of(comp: dict[str, Any], ev: dict[str, Any]) -> str | None:
    """Extract ESPN's clock string (e.g. 'Q3 5:32')."""
    for status_type in _status_blocks(comp, ev):
        detail = _as_text(status_type.get("shortDetail"))
        if detail:
            return detail
    return None


def _competitors(
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


def _event_label(home: str | None, away: str | None) -> str | None:
    """Compose the conventional 'Away @ Home' event label."""
    if not home or not away:
        return None
    return f"{away} @ {home}"


def _live_score(comp: dict[str, Any]) -> str | None:
    """Compose the 'away - home' score string for a live competition.

    The score order matches the conventional ``"Away @ Home"`` event label
    so a record reads ``"Golden State Warriors @ Phoenix Suns" /
    "50 - 45"``.
    """
    _home, _away, home_score, away_score = _competitors(comp)
    if home_score is None or away_score is None:
        return None
    return f"{away_score} - {home_score}"


# ── Live scores mapping ────────────────────────────────────────────────
def _map_live_scores(payload: dict[str, Any], sport_slug: str) -> list[dict[str, Any]]:
    """Map one ESPN scoreboard payload onto in-progress score records."""
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
        if not _is_in_progress(comp, ev):
            continue
        home, away, home_score, away_score = _competitors(comp)
        if not home or not away:
            continue
        records.append(
            {
                "sport": sport_slug,
                "event": _event_label(home, away),
                "home": home,
                "away": away,
                "home_score": home_score,
                "away_score": away_score,
                "status": _status_description(comp, ev) or "In Progress",
                "clock": _clock_of(comp, ev),
                "last_update": None,
            }
        )
    return records


# ── Live odds mapping (ESPN) ───────────────────────────────────────────
def _map_espn_live_odds(payload: dict[str, Any], sport_slug: str) -> list[dict[str, Any]]:
    """Map the ``odds`` blocks of in-progress ESPN competitions."""
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
        if not _is_in_progress(comp, ev):
            continue
        home, away, _home_score, _away_score = _competitors(comp)
        event = _event_label(home, away)
        if not event:
            continue
        score = _live_score(comp)
        clock = _clock_of(comp, ev)
        odds_list = comp.get("odds")
        if not isinstance(odds_list, list):
            continue
        for odd in odds_list:
            if not isinstance(odd, dict):
                continue
            provider = odd.get("provider")
            book = _as_text(provider.get("name")) if isinstance(provider, dict) else None
            if not book:
                continue
            spread = _to_float(odd.get("spread"))
            total = _to_float(odd.get("overUnder"))
            if spread is not None:
                records.append(
                    {
                        "event": event,
                        "market": "spread",
                        "book": book,
                        "odds": spread,
                        "live_score": score,
                        "clock": clock,
                        "last_update": None,
                    }
                )
            if total is not None:
                records.append(
                    {
                        "event": event,
                        "market": "total",
                        "book": book,
                        "odds": total,
                        "live_score": score,
                        "clock": clock,
                        "last_update": None,
                    }
                )
    return records


# ── Live odds mapping (The Odds API) ───────────────────────────────────
def _map_odds_api_live(payload: list[Any]) -> list[dict[str, Any]]:
    """Map in-play The Odds API events (commence_time in the past) onto records."""
    now = datetime.now(UTC)
    records: list[dict[str, Any]] = []
    for raw in payload:
        if not isinstance(raw, dict):
            continue
        commence = _as_text(raw.get("commence_time"))
        if commence is None or _parse_iso(commence) >= now:
            continue  # only events that have started count as live
        home = _as_text(raw.get("home_team"))
        away = _as_text(raw.get("away_team"))
        event = _event_label(home, away)
        if not event:
            continue
        bookmakers = raw.get("bookmakers")
        if not isinstance(bookmakers, list):
            continue
        for bk in bookmakers:
            if not isinstance(bk, dict):
                continue
            book = _as_text(bk.get("title")) or _as_text(bk.get("key"))
            if not book:
                continue
            last_update = _as_text(bk.get("last_update")) or commence
            markets = bk.get("markets")
            if not isinstance(markets, list):
                continue
            for mkt in markets:
                if not isinstance(mkt, dict):
                    continue
                market = _as_text(mkt.get("key")) or "h2h"
                outcomes = mkt.get("outcomes")
                if not isinstance(outcomes, list):
                    continue
                for outcome in outcomes:
                    if not isinstance(outcome, dict):
                        continue
                    price = _to_float(outcome.get("price"))
                    if price is None:
                        continue
                    records.append(
                        {
                            "event": event,
                            "market": market,
                            "book": book,
                            "odds": price,
                            "live_score": None,
                            "clock": None,
                            "last_update": last_update,
                        }
                    )
    return records


# ── Public API ─────────────────────────────────────────────────────────
async def get_live_odds(sport: str = "all", limit: int = 20) -> list[dict[str, Any]]:
    """Fetch in-play betting odds across bookmakers.

    Args:
        sport: Sport name (see module docstring) or ``"all"`` (default).
        limit: Max records to return (1-100).

    Returns:
        A list of live-odds records (see module docstring). ``[]`` on
        failure or invalid sport. Never raises.
    """
    try:
        return await _get_live_odds(sport, limit)
    except Exception:
        logger.exception("sports_live_odds_crashed", extra={"sport": sport, "limit": limit})
        return []


async def _get_live_odds(sport: str, limit: int) -> list[dict[str, Any]]:
    slugs = _resolve_sports(sport)
    if not slugs:
        logger.warning("sports_live_odds_invalid_sport", extra={"sport": sport})
        return []
    clamped = max(1, min(int(limit), _MAX_LIMIT))
    key = _api_key()
    records: list[dict[str, Any]] = []
    for slug in slugs:
        payload = await _espn_scoreboard(slug)
        if payload is not None:
            records.extend(_map_espn_live_odds(payload, slug))
        if key:
            odds_key, _espn = _SPORTS[slug]
            url = f"{_ODDS_BASE}/{quote(odds_key)}/odds"
            params = {
                "apiKey": key,
                "regions": _ODDS_API_REGIONS,
                "markets": _ODDS_API_MARKETS,
                "oddsFormat": "decimal",
            }
            odds_payload = await _fetch_json(url, params)
            if isinstance(odds_payload, list):
                records.extend(_map_odds_api_live(odds_payload))
        if len(records) >= _MAX_LIMIT:
            break
    records.sort(key=lambda record: str(record.get("last_update") or ""), reverse=True)
    return records[:clamped]


async def get_live_scores(sport: str) -> list[dict[str, Any]]:
    """Fetch live (in-progress) scores.

    Args:
        sport: Sport name (see module docstring) or ``"all"`` (default).

    Returns:
        A list of live score records (see module docstring). ``[]`` on
        failure, invalid sport, or when nothing is in progress. Never raises.
    """
    try:
        return await _get_live_scores(sport)
    except Exception:
        logger.exception("sports_live_scores_crashed", extra={"sport": sport})
        return []


async def _get_live_scores(sport: str) -> list[dict[str, Any]]:
    slugs = _resolve_sports(sport)
    if not slugs:
        logger.warning("sports_live_scores_invalid_sport", extra={"sport": sport})
        return []
    records: list[dict[str, Any]] = []
    for slug in slugs:
        payload = await _espn_scoreboard(slug)
        if payload is not None:
            records.extend(_map_live_scores(payload, slug))
        if len(records) >= _MAX_LIMIT:
            break
    return records[:_MAX_LIMIT]
