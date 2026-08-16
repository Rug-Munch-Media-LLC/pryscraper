"""Scores — ESPN public scoreboards (no auth, no quota, high-frequency safe).

ESPN's scoreboard endpoint (``site.api.espn.com/apis/site/v2/sports/...``)
is the sole source here: it is free, has no API key, and tolerates
frequent polling, which matches the latency-sensitive use case better than
quota-charged odds feeds. A per-day ``dates=YYYYMMDD`` parameter makes
historical looks cheap too.

Contract
--------
* :func:`get_scores` — async, never raises, returns a ``list`` (``[]`` on
  failure). One record per game.

Result shapes
-------------
``get_scores`` returns a list of:

    {
        "sport": "nba",
        "home": "Los Angeles Lakers",
        "away": "Boston Celtics",
        "home_score": "102",
        "away_score": "98",
        "status": "Final",
    }

``status`` comes from ESPN's ``status.type.description`` (e.g. ``"Final"``,
``"In Progress"``, ``"Scheduled"``, ``"Postponed"``); unknown/absent states
fall back to ``"Scheduled"``. Scores are strings (ESPN emits them as such);
upcoming games have ``None`` scores.

Sport names match :mod:`sports_data.odds` (``nba``, ``nfl``, ..., or the
Odds API key style). ``sport="all"`` (default) merges the most popular
sports. ``date`` accepts ``"today"`` (default), ``YYYYMMDD`` or
``YYYY-MM-DD``; anything else falls back to today.

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
from datetime import UTC, datetime
from typing import Any

import httpx

from retry import RetryConfig, async_retry
from sports_data.odds import _SPORTS, _resolve_sports

logger = logging.getLogger(__name__)

_ESPN_SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/scoreboard"

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


def _as_text(value: Any) -> str | None:
    """Coerce a JSON value to str/None ('' -> None)."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalize_date(date: str) -> str:
    """Return an ESPN-compatible ``YYYYMMDD`` date string.

    ``"today"`` (or empty/garbage) → today; ``YYYYMMDD`` and ``YYYY-MM-DD``
    are passed through/parsed; any other value falls back to today.
    """
    raw = str(date or "").strip()
    if raw and raw.lower() != "today":
        digits = "".join(ch for ch in raw if ch.isdigit())
        if len(digits) == 8:
            return digits
    return datetime.now(UTC).strftime("%Y%m%d")


# ── Fetching ───────────────────────────────────────────────────────────
async def _fetch_json(url: str, params: dict[str, str] | None = None) -> dict[str, Any] | None:
    """GET ``url`` and return the parsed JSON object, or ``None`` on failure."""

    async def _one() -> dict[str, Any]:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT, headers=_HEADERS, follow_redirects=True
        ) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("ESPN scoreboard payload is not an object")
        return payload

    try:
        return await async_retry(_one, config=_RETRY_CONFIG)
    except (httpx.HTTPError, OSError, ValueError):
        return None


# ── Mapping ────────────────────────────────────────────────────────────
def _status_of(ev: dict[str, Any], comp: dict[str, Any]) -> str | None:
    """Extract ESPN's status.description from event or competition level."""
    for source in (comp, ev):
        status = source.get("status")
        if not isinstance(status, dict):
            continue
        status_type = status.get("type")
        if isinstance(status_type, dict):
            description = _as_text(status_type.get("description"))
            if description:
                return description
    return None


def _map_scoreboard(payload: dict[str, Any], sport_slug: str) -> list[dict[str, Any]]:
    """Map one ESPN scoreboard payload onto canonical score records."""
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
        home = away = home_score = away_score = None
        competitors = comp.get("competitors")
        if not isinstance(competitors, list):
            continue
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
        if not home or not away:
            continue
        records.append(
            {
                "sport": sport_slug,
                "home": home,
                "away": away,
                "home_score": home_score,
                "away_score": away_score,
                "status": _status_of(ev, comp) or "Scheduled",
            }
        )
    return records


# ── Public API ─────────────────────────────────────────────────────────
async def get_scores(sport: str, date: str = "today") -> list[dict[str, Any]]:
    """Fetch scores for one or more sports on a given day.

    Args:
        sport: Sport name (see module docstring) or ``"all"`` (default).
        date: ``"today"`` (default), ``YYYYMMDD``, or ``YYYY-MM-DD``.

    Returns:
        A list of score records (see module docstring). ``[]`` on failure or
        invalid sport. Never raises.
    """
    try:
        return await _get_scores(sport, date)
    except Exception:
        logger.exception("sports_scores_crashed", extra={"sport": sport, "date": date})
        return []


async def _get_scores(sport: str, date: str) -> list[dict[str, Any]]:
    slugs = _resolve_sports(sport)
    if not slugs:
        logger.warning("sports_scores_invalid_sport", extra={"sport": sport})
        return []
    day = _normalize_date(date)
    records: list[dict[str, Any]] = []
    for slug in slugs:
        espn = _SPORTS[slug][1]
        if espn is None:
            continue
        espn_sport, espn_league = espn
        url = _ESPN_SCOREBOARD.format(sport=espn_sport, league=espn_league)
        payload = await _fetch_json(url, {"dates": day})
        if payload is not None:
            records.extend(_map_scoreboard(payload, slug))
        if len(records) >= _MAX_LIMIT:
            break
    return records[:_MAX_LIMIT]
