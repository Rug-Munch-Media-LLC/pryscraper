"""Player props — live cross-book lines and whole-team prop boards.

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

from datasets.sports_data.odds import _SPORTS
from datasets.sports_data.player_common import (
    _median,
    _movement,
    _resolve_one,
    _resolve_team,
)
from datasets.sports_data.props_http import (
    MAX_EVENTS,
    ODDS_API_REGIONS,
    ODDS_BASE,
    api_key,
    fetch_json,
)
from datasets.sports_data.props_odds_api import (
    _over_under_from_group,
    _player_of_outcome,
)
from datasets.sports_data.props_tables import _PROP_MARKETS, _short_slug
from datasets.sports_data.props_util import _as_text, _to_float

logger = logging.getLogger(__name__)


def _annotate_movement(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Add a cross-book ``movement`` signal per (player, market, book) record.

    The consensus line for each (market, line-group) is the median of the
    lines quoted across books; a book quoting above/below the median is
    flagged ``up``/``down`` (its line is richer/shorter than consensus).
    """
    by_market: dict[str, list[float]] = {}
    for record in records:
        line = _to_float(record.get("line"))
        market = str(record.get("market") or "")
        if line is not None:
            by_market.setdefault(market, []).append(line)
    consensus: dict[str, float | None] = {
        market: _median(lines) for market, lines in by_market.items()
    }
    annotated: list[dict[str, Any]] = []
    for record in records:
        line = _to_float(record.get("line"))
        market = str(record.get("market") or "")
        record = dict(record)
        record["prop_type"] = market
        record["movement"] = _movement(line, consensus.get(market))
        annotated.append(record)
    return annotated


async def get_player_props_live(player_name: str, sport: str = "nba") -> list[dict[str, Any]]:
    """All live player props for one player across books, with line movement.

    Args:
        player_name: Player name (e.g. ``"LeBron James"``).
        sport: Sport slug (``nba``, ``nfl``, ...).

    Returns:
        A list of prop records, one per (market, book)::

            {
                "player": "LeBron James",
                "sport": "nba",
                "prop_type": "player_points",
                "market": "player_points",
                "line": 25.5,
                "over_odds": 1.91,
                "under_odds": 1.95,
                "book": "DraftKings",
                "movement": "up",   # up / down / steady vs consensus median
                "source": "the_odds_api",
            }

        With no Odds API key configured, falls back to ESPN season-average
        estimates (``book="ESPN Estimate"``, odds ``None``, ``steady``).
        ``[]`` on failure or unknown player. Never raises.
    """
    try:
        return await _get_player_props_live(player_name, sport)
    except Exception:
        logger.exception(
            "sports_player_intel_props_live_crashed",
            extra={"player": player_name, "sport": sport},
        )
        return []


async def _get_player_props_live(player_name: str, sport: str) -> list[dict[str, Any]]:
    name = str(player_name or "").strip()
    if not name:
        return []
    slug = _resolve_one(sport)
    if not slug:
        logger.warning("sports_player_intel_invalid_sport", extra={"sport": sport})
        return []
    market_keys = list(_PROP_MARKETS.get(_short_slug(slug), []))
    if not market_keys:
        return []
    records: list[dict[str, Any]] = []
    key = api_key()
    if key:
        records = await _scan_player_props_odds_api(slug, name, market_keys)
    if not records:
        records = await _espn_estimate_records(name, slug, market_keys)
    return _annotate_movement(records)


async def _scan_player_props_odds_api(
    slug: str, player_q: str, market_keys: list[str]
) -> list[dict[str, Any]]:
    """Scan upcoming events for one player's lines across all books."""
    odds_key, _espn = _SPORTS[slug]
    key = api_key()
    events = await fetch_json(f"{ODDS_BASE}/{quote(odds_key)}/events", {"apiKey": key})
    if not isinstance(events, list):
        return []
    scanned = 0
    for ev in events:
        if not isinstance(ev, dict):
            continue
        event_id = _as_text(ev.get("id"))
        if not event_id:
            continue
        scanned += 1
        if scanned > MAX_EVENTS:
            break
        payload = await fetch_json(
            f"{ODDS_BASE}/{quote(odds_key)}/events/{quote(event_id)}/odds",
            {
                "apiKey": key,
                "regions": ODDS_API_REGIONS,
                "markets": ",".join(market_keys),
                "oddsFormat": "decimal",
            },
        )
        if not isinstance(payload, dict):
            continue
        records = _map_player_props(payload, slug, player_q, market_keys)
        if records:
            return records
    return []


def _map_player_props(
    raw: dict[str, Any], slug: str, player_q: str, market_keys: list[str]
) -> list[dict[str, Any]]:
    """Map one Odds API event payload to prop records for one player."""
    needle = player_q.casefold()
    bookmakers = raw.get("bookmakers")
    if not isinstance(bookmakers, list):
        return []
    records: list[dict[str, Any]] = []
    for bk in bookmakers:
        if not isinstance(bk, dict):
            continue
        book = _as_text(bk.get("title")) or _as_text(bk.get("key"))
        markets = bk.get("markets")
        if not book or not isinstance(markets, list):
            continue
        for mkt in markets:
            if not isinstance(mkt, dict):
                continue
            market_key = _as_text(mkt.get("key")) or ""
            if market_key not in market_keys:
                continue
            outcomes = mkt.get("outcomes")
            if not isinstance(outcomes, list):
                continue
            matched = [
                o
                for o in outcomes
                if isinstance(o, dict)
                and (
                    needle in str(o.get("description") or "").casefold()
                    or needle in str(o.get("name") or "").casefold()
                )
            ]
            if not matched:
                continue
            player_name = _player_of_outcome(matched[0]) or player_q
            point: float | None = None
            for outcome in matched:
                point = _to_float(outcome.get("point"))
                if point is not None:
                    break
            over, under = _over_under_from_group(matched)
            records.append(
                {
                    "player": player_name,
                    "sport": _short_slug(slug),
                    "prop_type": market_key,
                    "market": market_key,
                    "line": point,
                    "over_odds": over,
                    "under_odds": under,
                    "book": book,
                    "source": "the_odds_api",
                }
            )
    return records


async def _espn_estimate_records(
    player_q: str, slug: str, market_keys: list[str]
) -> list[dict[str, Any]]:
    """ESPN season-average projected lines (no Odds API key needed)."""
    from datasets.sports_data.props_espn import espn_estimate_props

    return await espn_estimate_props(player_q, slug, market_keys)


# ── Team-wide props ────────────────────────────────────────────────────
async def get_team_player_props(team: str, sport: str = "nba") -> list[dict[str, Any]]:
    """All player props for every player on a team's next event.

    Args:
        team: Team name (e.g. ``"Lakers"``).
        sport: Sport slug (``nba``, ``nfl``, ...).

    Returns:
        A list of prop records for every player on the team with a live
        line, one per (player, market, book)::

            {
                "player": "LeBron James",
                "team": "Los Angeles Lakers",
                "sport": "nba",
                "prop_type": "player_points",
                "line": 25.5,
                "over_odds": 1.91,
                "under_odds": 1.95,
                "book": "DraftKings",
                "movement": "steady",
                "source": "the_odds_api",
            }

        ``[]`` on failure, unknown team, or no Odds API key (ESPN publishes
        no team-level props feed). Never raises.
    """
    try:
        return await _get_team_player_props(team, sport)
    except Exception:
        logger.exception(
            "sports_player_intel_team_props_crashed", extra={"team": team, "sport": sport}
        )
        return []


async def _get_team_player_props(team: str, sport: str) -> list[dict[str, Any]]:
    name = str(team or "").strip()
    if not name:
        return []
    slug = _resolve_one(sport)
    if not slug:
        logger.warning("sports_player_intel_invalid_sport", extra={"sport": sport})
        return []
    key = api_key()
    if not key:
        return []
    resolved = await _resolve_team(name, slug)
    if resolved is None:
        return []
    event, competitor, _espn_sport, _espn_league = resolved
    event_id = _as_text(event.get("id"))
    if not event_id:
        return []
    team_obj = competitor.get("team")
    team_name = _as_text(team_obj.get("displayName")) if isinstance(team_obj, dict) else None
    market_keys = list(_PROP_MARKETS.get(_short_slug(slug), []))
    if not market_keys:
        return []
    odds_key, _espn = _SPORTS[slug]
    payload = await fetch_json(
        f"{ODDS_BASE}/{quote(odds_key)}/events/{quote(event_id)}/odds",
        {
            "apiKey": key,
            "regions": ODDS_API_REGIONS,
            "markets": ",".join(market_keys),
            "oddsFormat": "decimal",
        },
    )
    if not isinstance(payload, dict):
        return []
    records = _map_all_player_props(payload, slug, team_name)
    return _annotate_movement(records)


def _map_all_player_props(
    raw: dict[str, Any], slug: str, team_name: str | None
) -> list[dict[str, Any]]:
    """Map one Odds API event payload to prop records for every player."""
    bookmakers = raw.get("bookmakers")
    if not isinstance(bookmakers, list):
        return []
    records: list[dict[str, Any]] = []
    for bk in bookmakers:
        if not isinstance(bk, dict):
            continue
        book = _as_text(bk.get("title")) or _as_text(bk.get("key"))
        markets = bk.get("markets")
        if not book or not isinstance(markets, list):
            continue
        for mkt in markets:
            if not isinstance(mkt, dict):
                continue
            market_key = _as_text(mkt.get("key")) or ""
            if not market_key.startswith("player_"):
                continue
            outcomes = mkt.get("outcomes")
            if not isinstance(outcomes, list):
                continue
            groups: dict[tuple[str, float | None], list[dict[str, Any]]] = {}
            for outcome in outcomes:
                if not isinstance(outcome, dict):
                    continue
                player_name = _player_of_outcome(outcome)
                if not player_name:
                    continue
                point = _to_float(outcome.get("point"))
                groups.setdefault((player_name, point), []).append(outcome)
            for (player_name, point), group in groups.items():
                over, under = _over_under_from_group(group)
                records.append(
                    {
                        "player": player_name,
                        "team": team_name,
                        "sport": _short_slug(slug),
                        "prop_type": market_key,
                        "market": market_key,
                        "line": point,
                        "over_odds": over,
                        "under_odds": under,
                        "book": book,
                        "source": "the_odds_api",
                    }
                )
    return records
