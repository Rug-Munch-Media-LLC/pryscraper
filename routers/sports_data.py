"""Pry — Sports + betting data router.

Exposes live odds, multi-book event odds, player stats and scores backed by
the ``sports_data`` subpackage. Every import is guarded and degrades to 502
while a module has not landed yet (parallel build pattern).

Endpoints:
- GET /v1/sports/odds            — live odds across bookmakers (The Odds API
  key via ``PRY_ODDS_API_KEY``, ESPN fallback otherwise)
- GET /v1/sports/odds/{event_id} — multi-sportsbook odds comparison for one
  event (accepts ``sport:event_id`` to skip the default-sport scan)
- GET /v1/sports/stats/{player}  — player stats (ESPN)
- GET /v1/sports/scores          — scores for a day (ESPN)
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import importlib
import logging
from typing import Any

from fastapi import APIRouter, Query

from errors import ExternalServiceError

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Sports Data"])


def _sports_module(module_name: str) -> Any:
    """Import a ``sports_data`` submodule with a guarded ImportError.

    The modules are created in parallel by other agents; return None when a
    module has not landed yet so callers can degrade gracefully.
    """
    try:
        return importlib.import_module(f"sports_data.{module_name}")
    except ImportError:
        logger.warning("sports_data_module_unavailable", extra={"module_name": module_name})
        return None


def _module_unavailable(module_name: str) -> None:
    raise ExternalServiceError(
        f"sports_data.{module_name} is not available yet (parallel build in progress)"
    )


@router.get(
    "/v1/sports/odds",
    tags=["Sports Data"],
    summary="Live betting odds across bookmakers",
)
async def sports_odds(
    event_query: str = Query(
        "", max_length=500, description="Substring filter on event (e.g. 'celtics')"
    ),
    sport: str = Query("all", description="Sport: nba, nfl, mlb, nhl, epl, ... or 'all' (default)"),
    limit: int = Query(20, ge=1, le=100, description="Max records (default: 20)"),
) -> dict[str, Any]:
    """Fetch live odds for upcoming events across bookmakers."""
    mod = _sports_module("odds")
    if mod is None:
        _module_unavailable("odds")
    data = await mod.get_odds(event_query=event_query, sport=sport, limit=limit)
    return {"success": True, "data": data, "sport": sport, "limit": limit}


@router.get(
    "/v1/sports/odds/{event_id}",
    tags=["Sports Data"],
    summary="Multi-sportsbook odds comparison for one event",
)
async def sports_event_odds(event_id: str) -> dict[str, Any]:
    """Fetch odds for a single event across all available bookmakers."""
    mod = _sports_module("odds")
    if mod is None:
        _module_unavailable("odds")
    data = await mod.get_event_odds(event_id)
    return {"success": True, "data": data, "event_id": event_id}


@router.get(
    "/v1/sports/stats/{player}",
    tags=["Sports Data"],
    summary="Player stats (ESPN)",
)
async def sports_player_stats(
    player: str,
    sport: str = Query("all", description="Sport: nba, nfl, mlb, nhl, epl, ... or 'all' (default)"),
) -> dict[str, Any]:
    """Fetch current-season stats for a player (name or ESPN athlete id)."""
    mod = _sports_module("stats")
    if mod is None:
        _module_unavailable("stats")
    data = await mod.get_player_stats(player, sport=sport)
    return {"success": True, "data": data, "player": player}


@router.get(
    "/v1/sports/scores",
    tags=["Sports Data"],
    summary="Scores for a day (ESPN)",
)
async def sports_scores(
    sport: str = Query("all", description="Sport: nba, nfl, mlb, nhl, epl, ... or 'all' (default)"),
    date: str = Query("today", description="Date: 'today' (default), YYYYMMDD, or YYYY-MM-DD"),
) -> dict[str, Any]:
    """Fetch scores for one or more sports on a given day."""
    mod = _sports_module("scores")
    if mod is None:
        _module_unavailable("scores")
    data = await mod.get_scores(sport, date=date)
    return {"success": True, "data": data, "sport": sport, "date": date}
