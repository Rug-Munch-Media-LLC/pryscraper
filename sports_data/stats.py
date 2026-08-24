"""Player stats — ESPN public endpoints (no auth, no quota).

ESPN's public API (``site.web.api.espn.com``) powers this module entirely:

1. **Search** — ``/apis/common/v3/search`` resolves a player name to an ESPN
   athlete id (``items[].id``) scoped by sport/league.
2. **Stats** — ``/apis/common/v3/sports/{sport}/{league}/athletes/{id}/stats``
   returns per-season stat categories. The parser handles both the
   confirmed career-stats shape (``categories[].statistics[]`` with parallel
   ``displayNames``/``stats`` arrays, most recent season last) and a simpler
   ``categories[].stats[]`` variant for robustness.

A purely-numeric ``player`` argument is treated as an ESPN athlete id
directly (skips the search request) — handy for callers that already know
the id.

Contract
--------
* :func:`get_player_stats` — async, never raises, returns a ``dict``
  (``{}`` on failure, unknown player, or network error).

Result shape
------------
    {
        "player": "LeBron James",
        "sport": "nba",
        "team": "Los Angeles Lakers",
        "position": "F",
        "season": "2025-26",
        "stats": {"Games Played": "70", "Points Per Game": "24.4", ...},
        "source": "espn",
    }

Sport names match :mod:`sports_data.odds` (``nba``, ``nfl``, ..., or the
Odds API key style). ``sport="all"`` (default) probes the most popular
sports in order and returns the first match. Backoff: 1 retry, exponential
(0.1s -> 0.4s).

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

from pry.engine.retry import RetryConfig, async_retry
from sports_data.odds import _SPORTS, _resolve_sports

logger = logging.getLogger(__name__)

_ESPN_SEARCH = "https://site.web.api.espn.com/apis/common/v3/search"
_ESPN_STATS = (
    "https://site.web.api.espn.com/apis/common/v3/sports/{sport}/{league}/athletes/{id}/stats"
)

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

_SEARCH_LIMIT = 5
_CURRENT_YEAR = datetime.now(UTC).year


def _as_text(value: Any) -> str | None:
    """Coerce a JSON value to str/None ('' -> None)."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


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
            raise ValueError("ESPN stats payload is not an object")
        return payload

    try:
        return await async_retry(_one, config=_RETRY_CONFIG)
    except (httpx.HTTPError, OSError, ValueError):
        return None


# ── Search ─────────────────────────────────────────────────────────────
def _search_team(item: dict[str, Any]) -> str | None:
    """Extract the team display name from a search item's teamRelationships."""
    relationships = item.get("teamRelationships")
    if not isinstance(relationships, list):
        return None
    for rel in relationships:
        if not isinstance(rel, dict):
            continue
        name = _as_text(rel.get("displayName"))
        if name:
            return name
    return None


async def _search_athlete(
    name: str, espn_sport: str, espn_league: str
) -> tuple[str, str | None] | None:
    """Resolve a player name to (athlete_id, team_name), or None."""
    payload = await _fetch_json(
        _ESPN_SEARCH,
        {
            "query": name,
            "type": "player",
            "sport": espn_sport,
            "league": espn_league,
            "limit": str(_SEARCH_LIMIT),
        },
    )
    if payload is None:
        return None
    items = payload.get("items")
    if not isinstance(items, list):
        return None
    for item in items:
        if not isinstance(item, dict):
            continue
        if str(item.get("type") or "").lower() not in {"player", "athlete"}:
            continue
        athlete_id = _as_text(item.get("id"))
        if not athlete_id:
            continue
        return athlete_id, _search_team(item)
    return None


# ── Stats parsing ──────────────────────────────────────────────────────
def _parse_team_stats(
    payload: dict[str, Any],
) -> tuple[dict[str, Any], str | None, str | None, str | None]:
    """Parse the confirmed ESPN career-stats shape.

    Returns ``(stats, team, season, position)``. Each category carries
    parallel ``displayNames`` / ``statistics[]`` arrays; the last
    ``statistics`` entry is the most recent season (ESPN orders ascending).
    """
    stats: dict[str, Any] = {}
    team: str | None = None
    season: str | None = None
    position: str | None = None
    categories = payload.get("categories")
    if not isinstance(categories, list):
        return stats, team, season, position
    teams = payload.get("teams")
    for cat in categories:
        if not isinstance(cat, dict):
            continue
        display_names = cat.get("displayNames")
        if not isinstance(display_names, list):
            continue
        statistics = cat.get("statistics")
        if not isinstance(statistics, list) or not statistics:
            continue
        latest = statistics[-1]
        if not isinstance(latest, dict):
            continue
        values = latest.get("stats")
        if not isinstance(values, list):
            continue
        for label, value in zip(display_names, values, strict=False):
            label_text = _as_text(label)
            if not label_text:
                continue
            value_text = _as_text(value)
            if value_text is not None:
                stats[label_text] = value_text
        if team is None:
            slug = _as_text(latest.get("teamSlug"))
            if slug and isinstance(teams, dict):
                team_info = teams.get(slug)
                if isinstance(team_info, dict):
                    team = _as_text(team_info.get("displayName"))
            team = team or slug
        if season is None:
            season_obj = latest.get("season")
            if isinstance(season_obj, dict):
                season = _as_text(season_obj.get("displayName")) or _as_text(season_obj.get("year"))
        if position is None:
            position = _as_text(latest.get("position"))
    return stats, team, season, position


def _parse_simple_stats(
    payload: dict[str, Any],
) -> tuple[dict[str, Any], str | None, str | None, str | None]:
    """Parse the simpler ``categories[].stats[]`` variant (defensive)."""
    stats: dict[str, Any] = {}
    team: str | None = None
    season: str | None = None
    categories = payload.get("categories")
    if not isinstance(categories, list):
        categories = _season_types_categories(payload)
    if isinstance(categories, list):
        for cat in categories:
            if not isinstance(cat, dict):
                continue
            stat_list = cat.get("stats")
            if not isinstance(stat_list, list):
                continue
            for entry in stat_list:
                if not isinstance(entry, dict):
                    continue
                label = _as_text(entry.get("displayName")) or _as_text(entry.get("name"))
                if not label:
                    continue
                value = entry.get("displayValue")
                if value is None:
                    value = entry.get("value")
                value_text = _as_text(value)
                if value_text is not None:
                    stats[label] = value_text
    athlete = payload.get("athlete")
    if isinstance(athlete, dict):
        team_obj = athlete.get("team")
        if isinstance(team_obj, dict):
            team = _as_text(team_obj.get("displayName"))
        season = _as_text(athlete.get("season"))
    if not season:
        season = str(_CURRENT_YEAR)
    return stats, team, season, None


def _season_types_categories(payload: dict[str, Any]) -> list[Any] | None:
    """Fall back to the first regular-season category group, if present."""
    season_types = payload.get("seasonTypes")
    if not isinstance(season_types, list) or not season_types:
        return None
    first = season_types[0]
    if isinstance(first, dict):
        return first.get("categories")
    return None


def _parse_stats(
    payload: dict[str, Any],
) -> tuple[dict[str, Any], str | None, str | None, str | None]:
    """Parse a stats payload across supported shapes."""
    stats, team, season, position = _parse_team_stats(payload)
    if stats:
        return stats, team, season, position
    return _parse_simple_stats(payload)


async def _stats_for_athlete(
    athlete_id: str, espn_sport: str, espn_league: str
) -> tuple[dict[str, Any], str | None, str | None, str | None]:
    """Fetch + parse stats for one athlete id."""
    url = _ESPN_STATS.format(sport=espn_sport, league=espn_league, id=athlete_id)
    payload = await _fetch_json(url)
    if payload is None:
        return {}, None, None, None
    return _parse_stats(payload)


# ── Public API ─────────────────────────────────────────────────────────
async def get_player_stats(player: str, sport: str = "all") -> dict[str, Any]:
    """Fetch current-season player stats.

    Args:
        player: Player name (e.g. ``"LeBron James"``) or a numeric ESPN
            athlete id (e.g. ``"1966"`` — skips the search request).
        sport: Sport name (see module docstring) or ``"all"`` (default,
            probes popular sports in order and returns the first match).

    Returns:
        A stats record (see module docstring) or ``{}`` on failure
        (unknown player, invalid sport, network error). Never raises.
    """
    try:
        return await _get_player_stats(player, sport)
    except Exception:
        logger.exception("sports_player_stats_crashed", extra={"player": player, "sport": sport})
        return {}


async def _get_player_stats(player: str, sport: str) -> dict[str, Any]:
    name = str(player or "").strip()
    if not name:
        return {}
    slugs = _resolve_sports(sport)
    if not slugs:
        logger.warning("sports_stats_invalid_sport", extra={"sport": sport})
        return {}
    if name.isdigit():
        # Treat a purely numeric player as an ESPN athlete id. With "all" we
        # only probe the first default sport — an id belongs to one league.
        for slug in slugs[:1] if len(slugs) > 1 else slugs:
            espn = _SPORTS[slug][1]
            if espn is None:
                continue
            espn_sport, espn_league = espn
            stats, team, season, position = await _stats_for_athlete(name, espn_sport, espn_league)
            if stats:
                return {
                    "player": name,
                    "sport": slug,
                    "team": team,
                    "position": position,
                    "season": season or str(_CURRENT_YEAR),
                    "stats": stats,
                    "source": "espn",
                }
        return {}
    for slug in slugs:
        espn = _SPORTS[slug][1]
        if espn is None:
            continue
        espn_sport, espn_league = espn
        found = await _search_athlete(name, espn_sport, espn_league)
        if found is None:
            continue
        athlete_id, search_team = found
        stats, team, season, position = await _stats_for_athlete(
            athlete_id, espn_sport, espn_league
        )
        if not stats:
            continue
        return {
            "player": name,
            "sport": slug,
            "team": team or search_team,
            "position": position,
            "season": season or str(_CURRENT_YEAR),
            "stats": stats,
            "source": "espn",
        }
    return {}
