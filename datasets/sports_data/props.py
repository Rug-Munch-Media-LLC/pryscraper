"""Player props — The Odds API player-props markets + ESPN season-average fallback.

Two sources are aggregated here:

* **The Odds API** (``api.the-odds-api.com``) — real bookmaker player props
  (points, rebounds, assists, passing/rushing/receiving yards, anytime-TD,
  hits, saves, ...) via the v4 ``/sports/{key}/events/{id}/odds`` endpoint
  with ``markets=player_*``. Requires a free API key
  (https://the-odds-api.com) via the ``PRY_ODDS_API_KEY`` env var. The free
  tier is 500 requests/month and each requested market/region/sport counts
  against it, so per-sport market sets are kept small (see
  ``data/props.json``) and at most 3 events are scanned per sport until the
  target player is found.
* **ESPN public endpoints** (``site.web.api.espn.com``) — no key, no quota.
  When no key is configured (or the Odds API path yields nothing) the module
  synthesizes a *projected line* from the player's current-season per-game
  averages (e.g. points/rebounds/assists per game from ESPN's stats feed).
  Estimates carry no odds (``over_odds``/``under_odds`` are ``None``) and
  are labelled ``book="ESPN Estimate"``, ``source="espn_estimate"`` so
  callers can always tell real bookmaker lines from projections.

Contract
--------
* :func:`get_player_props` — async, never raises, returns a ``list``
  (``[]`` on failure). One record per (player, market, bookmaker).
* :func:`get_game_props` — async, never raises, returns a ``list``. Flattens
  *all* player props for one event; requires an Odds API key (ESPN publishes
  no game-level props feed), ``[]`` without one.
* :func:`get_prop_markets` — async, never raises, returns a ``list`` of the
  player-prop markets available for one event (market key, label, distinct
  player count, publishing books). Also requires an Odds API key, ``[]``
  without one.

Result shapes
-------------
``get_player_props`` returns a list of:

    {
        "player": "LeBron James",
        "sport": "nba",
        "market": "player_points",
        "line": 25.5,
        "over_odds": 1.91,
        "under_odds": 1.95,
        "book": "DraftKings",
        "source": "the_odds_api",
    }

The ESPN fallback emits the same keys with ``over_odds``/``under_odds`` =
``None`` and ``book="ESPN Estimate"``.

Market names accepted by ``market``: ``points``, ``rebounds``, ``assists``,
``threes``, ``pass_yds``, ``rush_yds``, ``recv_yds``, ``anytime_td``,
``home_runs``, ``hits``, ``rbis``, ``total_bases``, ``shots_on_goal``,
``shots_on_target``, ``tackles``, ``saves``, ``sacks``, ``kills``, ``aces``,
``double_double``, ``triple_double``, ``pra``, ``recv_tds``, ``rush_tds``,
``interceptions``, ``solo_tackles``, ``goals`` (or any raw Odds API
``player_*`` key, e.g. ``player_sacks`` — unknown ``player_*`` keys pass
through so new upstream markets work without a code change). A comma or
pipe separated list (e.g. ``"points,rebounds"``) requests multiple markets
in one call. ``"all"`` (default) uses the per-sport default set in
``data/props.json``.

Sport names match :mod:`sports_data.odds`. Backoff: 1 retry, exponential
(0.1s -> 0.4s). Free-API terms: https://the-odds-api.com.

Implementation is split across focused modules:

* :mod:`sports_data.props_http` — shared HTTP client, retry config, keys.
* :mod:`sports_data.props_tables` — JSON-loaded market tables + resolution.
* :mod:`sports_data.props_util` — small JSON coercion helpers.
* :mod:`sports_data.props_odds_api` — Odds API fetching + payload mapping.
* :mod:`sports_data.props_espn` — ESPN season-average estimate fallback.

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

from datasets.sports_data.odds import _resolve_sports
from datasets.sports_data.props_espn import espn_estimate_props as _espn_estimate_props
from datasets.sports_data.props_http import (
    MAX_LIMIT as _MAX_LIMIT,
    RETRY_CONFIG as _RETRY_CONFIG,  # noqa: F401 — monkeypatched by tests
    api_key as _api_key,
)
from datasets.sports_data.props_odds_api import (
    game_props_for_event,
    prop_markets_for_event,
    props_for_player_odds_api as _props_for_player_odds_api,
)
from datasets.sports_data.props_tables import _market_keys_for

logger = logging.getLogger(__name__)

__all__ = ["get_game_props", "get_player_props", "get_prop_markets"]


# ── Public API ─────────────────────────────────────────────────────────
async def get_player_props(
    player: str, sport: str = "all", market: str = "all", limit: int = 20
) -> list[dict[str, Any]]:
    """Fetch player props across bookmakers for one or more sports.

    Args:
        player: Player name (e.g. ``"LeBron James"``).
        sport: Sport name (see module docstring) or ``"all"`` (default).
        market: Prop market name (see module docstring) or ``"all"``
            (default, per-sport default set).
        limit: Max records to return (1-100).

    Returns:
        A list of prop records (see module docstring). ``[]`` on failure,
        invalid sport, or unknown player. Never raises.
    """
    try:
        return await _get_player_props(player, sport, market, limit)
    except Exception:
        logger.exception(
            "sports_player_props_crashed",
            extra={"player": player, "sport": sport, "market": market},
        )
        return []


async def _get_player_props(
    player: str, sport: str, market: str, limit: int
) -> list[dict[str, Any]]:
    name = str(player or "").strip()
    if not name:
        return []
    slugs = _resolve_sports(sport)
    if not slugs:
        logger.warning("sports_props_invalid_sport", extra={"sport": sport})
        return []
    clamped = max(1, min(int(limit), _MAX_LIMIT))
    key = _api_key()
    records: list[dict[str, Any]] = []
    for slug in slugs:
        market_keys = _market_keys_for(slug, market)
        if not market_keys:
            continue
        if key:
            records.extend(await _props_for_player_odds_api(slug, name, market_keys))
        else:
            records.extend(await _espn_estimate_props(name, slug, market_keys))
    records.sort(key=lambda record: str(record.get("book") or ""))
    return records[:clamped]


async def get_game_props(event_id: str) -> list[dict[str, Any]]:
    """Fetch all player props for a single event.

    Args:
        event_id: The event id. Accepts an optional ``sport:event_id`` prefix
            (e.g. ``nba:eid123`` or ``basketball_nba:...``) to skip the
            default-sport scan.

    Returns:
        A list of prop records for every player with a line in the event.
        ``[]`` on failure or when no Odds API key is configured (ESPN
        publishes no game-level props feed). Never raises.
    """
    try:
        return await game_props_for_event(event_id)
    except Exception:
        logger.exception("sports_game_props_crashed", extra={"event_id": event_id})
        return []


async def get_prop_markets(event_id: str) -> list[dict[str, Any]]:
    """Discover which player-prop markets are available for one event.

    Args:
        event_id: The event id. Accepts an optional ``sport:event_id`` prefix
            (e.g. ``nba:eid123`` or ``basketball_nba:...``) to skip the
            default-sport scan.

    Returns:
        A list of market records (see below), one per player-prop market
        published by at least one bookmaker in the event, sorted by market
        key. ``[]`` on failure or when no Odds API key is configured (ESPN
        publishes no game-level props feed). Never raises.

        Each record::

            {
                "event_id": "eid123",
                "event": "Celtics @ Lakers",
                "sport": "nba",
                "market": "player_points",
                "label": "Player Points",
                "player_count": 8,
                "book": "DraftKings",
                "books": ["DraftKings", "FanDuel"],
                "source": "the_odds_api",
            }
    """
    try:
        return await prop_markets_for_event(event_id)
    except Exception:
        logger.exception("sports_prop_markets_crashed", extra={"event_id": event_id})
        return []
