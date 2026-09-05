"""Live scores + in-play odds — ESPN live scoreboards + The Odds API.

Sources: ESPN public scoreboards (no key; in-progress competitions carry
live scores, a clock string, and an optional ``odds`` block per provider;
some egress IPs get 403 — every parse degrades to ``[]``) and The Odds API
(``PRY_ODDS_API_KEY``; events whose ``commence_time`` has passed are
treated as in-play and merged, with ``live_score``/``clock`` ``None``).

Contract: :func:`get_live_odds` — async, never raises, returns a ``list``
(``[]`` on failure), one record per (event, market, book);
:func:`get_live_scores` — async, never raises, returns a ``list`` (``[]``
on failure), one record per in-progress game. Record shapes: live-odds
records carry ``{event, market, book, odds, live_score, clock,
last_update}``; live-score records carry ``{sport, event, home, away,
home_score, away_score, status, clock, last_update}``. Sport names match
:mod:`sports_data.odds`. Internals live in the ``live_common`` /
``live_fetchers`` / ``live_parsers`` siblings; this module re-exports
them so the ``sports_data.live`` surface is unchanged.

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

from datasets.sports_data.live_common import (  # re-exported surface
    _API_KEY_ENV as _API_KEY_ENV,
    _ESPN_SCOREBOARD as _ESPN_SCOREBOARD,
    _HEADERS as _HEADERS,
    _MAX_LIMIT as _MAX_LIMIT,
    _ODDS_API_MARKETS as _ODDS_API_MARKETS,
    _ODDS_API_REGIONS as _ODDS_API_REGIONS,
    _ODDS_BASE as _ODDS_BASE,
    _RETRY_CONFIG as _RETRY_CONFIG,
    _TIMEOUT as _TIMEOUT,
    _api_key as _api_key,
    _as_text as _as_text,
    _clock_of as _clock_of,
    _competitors as _competitors,
    _event_label as _event_label,
    _is_in_progress as _is_in_progress,
    _live_score as _live_score,
    _parse_iso as _parse_iso,
    _status_blocks as _status_blocks,
    _status_description as _status_description,
    _to_float as _to_float,
)
from datasets.sports_data.live_fetchers import (  # re-exported surface
    _espn_scoreboard as _espn_scoreboard,
    _fetch_json as _fetch_json,
)
from datasets.sports_data.live_parsers import (  # re-exported surface
    _map_espn_live_odds as _map_espn_live_odds,
    _map_live_scores as _map_live_scores,
    _map_odds_api_live as _map_odds_api_live,
)
from datasets.sports_data.odds import _SPORTS, _resolve_sports

logger = logging.getLogger(__name__)


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
