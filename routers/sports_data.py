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
- GET /v1/sports/historical      — historical closing/open odds for a date
- GET /v1/sports/betting-percentages — share of bets & money per side
- GET /v1/sports/sharp-consensus — sharp-book consensus lines w/ CLV
- GET /v1/sports/alerts          — money-printer alerts (line move/steam/CLV)
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import importlib
import logging
from typing import Any, NoReturn

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


def _module_unavailable(module_name: str) -> NoReturn:
    raise ExternalServiceError(
        f"sports_data.{module_name} is not available yet (parallel build in progress)"
    )


def _sports_module_first(*module_names: str) -> Any | None:
    """Import the first existing ``sports_data`` submodule among candidates.

    Parallel agents may land a module under a slightly different file name
    (e.g. ``plus_ev`` vs ``ev``); try each in order and return the first one
    that imports.
    """
    for module_name in module_names:
        mod = _sports_module(module_name)
        if mod is not None:
            return mod
    return None


def _sports_fn(mod: Any, *candidates: str) -> Any | None:
    """Resolve the first callable attribute among ``candidates`` on a module.

    The arbitrage / plus_ev / props / injuries / live_odds modules land in
    parallel from other agents, so their public function name is resolved
    defensively. Returns ``None`` when the module or every candidate is
    missing (callers degrade to 502).
    """
    if mod is None:
        return None
    for candidate in candidates:
        fn = getattr(mod, candidate, None)
        if callable(fn):
            return fn
    return None


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


@router.get(
    "/v1/sports/arbitrage",
    tags=["Sports Data"],
    summary="Arbitrage opportunities across bookmakers",
)
async def sports_arbitrage(
    sport: str = Query("all", description="Sport: nba, nfl, mlb, nhl, epl, ... or 'all' (default)"),
    min_yield_pct: float = Query(
        0.5, ge=0.0, le=100.0, description="Minimum guaranteed yield % (default: 0.5)"
    ),
) -> dict[str, Any]:
    """Scan sportsbook lines for guaranteed-profit arbitrage opportunities."""
    mod = _sports_module("arbitrage")
    fn = _sports_fn(mod, "get_arbitrage", "find_arbitrage", "scan_arbitrage")
    if fn is None:
        _module_unavailable("arbitrage")
    data = await fn(sport=sport, min_yield_pct=min_yield_pct)
    return {"success": True, "data": data, "sport": sport, "min_yield_pct": min_yield_pct}


@router.get(
    "/v1/sports/plus-ev",
    tags=["Sports Data"],
    summary="Positive-EV betting opportunities vs a sharp book",
)
async def sports_plus_ev(
    sharp_book: str = Query(
        "pinnacle", description="Sharp book to treat as the fair line reference (default: pinnacle)"
    ),
    min_ev_pct: float = Query(
        1.0, ge=0.0, le=100.0, description="Minimum expected value % (default: 1.0)"
    ),
) -> dict[str, Any]:
    """Find +EV bets where market odds beat the sharp book's fair line."""
    mod = _sports_module_first("plus_ev", "ev")
    fn = _sports_fn(mod, "get_plus_ev", "find_plus_ev", "scan_plus_ev")
    if fn is None:
        _module_unavailable("plus_ev")
    data = await fn(sharp_book=sharp_book, min_ev_pct=min_ev_pct)
    return {"success": True, "data": data, "sharp_book": sharp_book, "min_ev_pct": min_ev_pct}


@router.get(
    "/v1/sports/props",
    tags=["Sports Data"],
    summary="Player prop betting lines",
)
async def sports_props(
    player: str = Query("", max_length=200, description="Player name, e.g. 'LeBron James'"),
    sport: str = Query("all", description="Sport: nba, nfl, mlb, nhl, epl, ... or 'all' (default)"),
    market: str = Query(
        "", max_length=100, description="Prop market (e.g. 'points', 'passing_yards')"
    ),
) -> dict[str, Any]:
    """Fetch player prop betting lines for a player or sport."""
    mod = _sports_module("props")
    fn = _sports_fn(mod, "get_player_props", "get_props", "search_props", "player_props")
    if fn is None:
        _module_unavailable("props")
    data = await fn(player=player, sport=sport, market=market)
    return {"success": True, "data": data, "player": player, "sport": sport, "market": market}


@router.get(
    "/v1/sports/injuries",
    tags=["Sports Data"],
    summary="Injury report for a sport or team",
)
async def sports_injuries(
    sport: str = Query("all", description="Sport: nba, nfl, mlb, nhl, epl, ... or 'all' (default)"),
    team: str = Query("", max_length=200, description="Team name, e.g. 'Celtics'"),
) -> dict[str, Any]:
    """Fetch the current injury report for a sport or team."""
    mod = _sports_module("injuries")
    fn = _sports_fn(mod, "get_injuries", "list_injuries", "injury_report")
    if fn is None:
        _module_unavailable("injuries")
    data = await fn(sport=sport, team=team)
    return {"success": True, "data": data, "sport": sport, "team": team}


@router.get(
    "/v1/sports/live",
    tags=["Sports Data"],
    summary="Live in-play odds",
)
async def sports_live_odds(
    sport: str = Query("all", description="Sport: nba, nfl, mlb, nhl, epl, ... or 'all' (default)"),
    limit: int = Query(20, ge=1, le=100, description="Max records (default: 20)"),
) -> dict[str, Any]:
    """Fetch live in-play odds that update during games."""
    mod = _sports_module_first("live_odds", "live")
    fn = _sports_fn(mod, "get_live_odds", "live_odds")
    if fn is None:
        _module_unavailable("live_odds")
    data = await fn(sport=sport, limit=limit)
    return {"success": True, "data": data, "sport": sport, "limit": limit}


@router.get(
    "/v1/sports/historical",
    tags=["Sports Data"],
    summary="Historical betting odds for past events",
)
async def sports_historical_odds(
    sport: str = Query("all", description="Sport: nba, nfl, mlb, nhl, epl, ... or 'all' (default)"),
    date: str = Query("today", description="Date: 'today' (default), YYYYMMDD, or YYYY-MM-DD"),
    limit: int = Query(20, ge=1, le=100, description="Max records (default: 20)"),
) -> dict[str, Any]:
    """Fetch historical (closing/open) odds for events on a given date."""
    mod = _sports_module_first("historical", "historical_odds")
    fn = _sports_fn(mod, "get_historical_odds", "historical_odds", "get_historical")
    if fn is None:
        _module_unavailable("historical")
    data = await fn(sport=sport, date=date, limit=limit)
    return {"success": True, "data": data, "sport": sport, "date": date, "limit": limit}


@router.get(
    "/v1/sports/betting-percentages",
    tags=["Sports Data"],
    summary="Public betting percentages (bets & money share)",
)
async def sports_betting_percentages(
    sport: str = Query("all", description="Sport: nba, nfl, mlb, nhl, epl, ... or 'all' (default)"),
    event: str = Query("", max_length=200, description="Event substring filter, e.g. 'Chiefs'"),
    limit: int = Query(20, ge=1, le=100, description="Max records (default: 20)"),
) -> dict[str, Any]:
    """Fetch the share of bets and money on each side of a game."""
    mod = _sports_module_first("percentages", "betting_percentages")
    fn = _sports_fn(mod, "get_betting_percentages", "betting_percentages", "get_percentages")
    if fn is None:
        _module_unavailable("percentages")
    kwargs: dict[str, Any] = {"sport": sport, "limit": limit}
    if event:
        kwargs["event"] = event
    data = await fn(**kwargs)
    return {"success": True, "data": data, "sport": sport, "event": event, "limit": limit}


@router.get(
    "/v1/sports/sharp-consensus",
    tags=["Sports Data"],
    summary="Sharp consensus lines (CLV-aware)",
)
async def sports_sharp_consensus(
    sport: str = Query("all", description="Sport: nba, nfl, mlb, nhl, epl, ... or 'all' (default)"),
    sharp_books: str = Query(
        "", max_length=200, description="Comma-separated sharp books, e.g. 'pinnacle,circa'"
    ),
    limit: int = Query(20, ge=1, le=100, description="Max records (default: 20)"),
) -> dict[str, Any]:
    """Fetch consensus lines aggregated from sharp books with CLV estimates."""
    mod = _sports_module_first("consensus", "sharp_consensus")
    fn = _sports_fn(mod, "get_sharp_consensus", "sharp_consensus", "get_consensus")
    if fn is None:
        _module_unavailable("consensus")
    kwargs: dict[str, Any] = {"sport": sport, "limit": limit}
    if sharp_books:
        kwargs["sharp_books"] = [b.strip() for b in sharp_books.split(",") if b.strip()]
    data = await fn(**kwargs)
    return {"success": True, "data": data, "sport": sport, "limit": limit}


@router.get(
    "/v1/sports/alerts",
    tags=["Sports Data"],
    summary="Money-printer alerts (line moves, steam, CLV)",
)
async def sports_alerts(
    alert_type: str = Query(
        "",
        max_length=50,
        description="Alert category: line_move, steam, clv, injury, or empty for all",
    ),
    sport: str = Query("all", description="Sport: nba, nfl, mlb, nhl, epl, ... or 'all' (default)"),
    limit: int = Query(20, ge=1, le=100, description="Max records (default: 20)"),
) -> dict[str, Any]:
    """Fetch significant betting alerts: line moves, sharp steam, CLV spikes."""
    mod = _sports_module_first("alerts", "alert")
    fn = _sports_fn(mod, "get_alerts", "list_alerts", "alerts")
    if fn is None:
        _module_unavailable("alerts")
    kwargs: dict[str, Any] = {"sport": sport, "limit": limit}
    if alert_type:
        kwargs["alert_type"] = alert_type
    data = await fn(**kwargs)
    return {"success": True, "data": data, "sport": sport, "alert_type": alert_type, "limit": limit}
