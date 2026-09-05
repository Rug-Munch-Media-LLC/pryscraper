"""ESPN season-average fallback for player props (no API key required).

When no Odds API key is configured (or the Odds API path yields nothing)
this module synthesizes a *projected line* from the player's current-season
per-game averages (e.g. points/rebounds/assists per game from ESPN's stats
feed). Estimates carry no odds (``over_odds``/``under_odds`` are ``None``)
and are labelled ``book="ESPN Estimate"``, ``source="espn_estimate"`` so
callers can always tell real bookmaker lines from projections.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

from typing import Any

from datasets.sports_data.odds import _SPORTS
from datasets.sports_data.props_http import (
    ESPN_SEARCH,
    ESPN_STATS,
    SEARCH_LIMIT,
    fetch_json,
)
from datasets.sports_data.props_tables import _ESTIMATE_RULES, _short_slug
from datasets.sports_data.props_util import _as_text, _round_half, _to_float


async def _espn_search_athlete(
    name: str, espn_sport: str, espn_league: str
) -> tuple[str, str | None] | None:
    """Resolve a player name to (athlete_id, team_name), or None."""
    payload = await fetch_json(
        ESPN_SEARCH,
        {
            "query": name,
            "type": "player",
            "sport": espn_sport,
            "league": espn_league,
            "limit": str(SEARCH_LIMIT),
        },
    )
    if not isinstance(payload, dict):
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
        team = None
        relationships = item.get("teamRelationships")
        if isinstance(relationships, list):
            for rel in relationships:
                if not isinstance(rel, dict):
                    continue
                team_name = _as_text(rel.get("displayName"))
                if team_name:
                    team = team_name
                    break
        return athlete_id, team
    return None


def _extract_stat_map(payload: dict[str, Any]) -> dict[str, str]:
    """Flatten an ESPN stats payload to a label -> displayValue map.

    Handles the ``categories[].statistics[]`` shape (parallel
    ``displayNames``/``stats`` arrays, most recent season last) and the
    simpler ``categories[].stats[]`` shape.
    """
    stats: dict[str, str] = {}
    categories = payload.get("categories")
    if not isinstance(categories, list):
        return stats
    for cat in categories:
        if not isinstance(cat, dict):
            continue
        display_names = cat.get("displayNames")
        if isinstance(display_names, list):
            statistics = cat.get("statistics")
            if isinstance(statistics, list) and statistics:
                latest = statistics[-1]
                if isinstance(latest, dict) and isinstance(latest.get("stats"), list):
                    for label, value in zip(display_names, latest["stats"], strict=False):
                        label_text = _as_text(label)
                        value_text = _as_text(value)
                        if label_text and value_text is not None:
                            stats[label_text] = value_text
        stat_list = cat.get("stats")
        if isinstance(stat_list, list):
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
    return stats


async def espn_estimate_props(
    player_q: str, slug: str, market_keys: list[str]
) -> list[dict[str, Any]]:
    """Synthesize projected prop lines from ESPN season averages (no key)."""
    short = _short_slug(slug)
    rules = _ESTIMATE_RULES.get(short)
    if not rules:
        return []
    espn = _SPORTS[slug][1]
    if espn is None:
        return []
    espn_sport, espn_league = espn
    found = await _espn_search_athlete(player_q, espn_sport, espn_league)
    if found is None:
        return []
    athlete_id, _team = found
    url = ESPN_STATS.format(sport=espn_sport, league=espn_league, id=athlete_id)
    payload = await fetch_json(url)
    if not isinstance(payload, dict):
        return []
    stats = _extract_stat_map(payload)
    records: list[dict[str, Any]] = []
    for fragment, market_key in rules:
        if market_key not in market_keys:
            continue
        line: float | None = None
        for label, value in stats.items():
            if fragment.casefold() in label.casefold():
                line = _to_float(value)
                break
        if line is None:
            continue
        records.append(
            {
                "player": player_q,
                "sport": short,
                "market": market_key,
                "line": _round_half(line),
                "over_odds": None,
                "under_odds": None,
                "book": "ESPN Estimate",
                "source": "espn_estimate",
            }
        )
    return records
