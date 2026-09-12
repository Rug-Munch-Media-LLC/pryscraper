"""First-half / second-half and quarter (period) betting markets.

Books publish same-game markets for discrete game segments — first half,
second half and (for basketball) quarters — as moneyline, spread and
over/under markets. This module exposes them through a single event-driven
call.

Source
------
Only **The Odds API** publishes period markets in the schema this module
reads (``h1``, ``h2``, ``q1``..``q4`` plus their ``_spreads``/``_totals``
variants), via the v4 per-event odds endpoint. It requires a free API key
(https://the-odds-api.com) via the ``PRY_ODDS_API_KEY`` env var. ESPN
publishes no half/quarter odds feed, so without a key this module returns
``[]`` rather than fabricating lines — the same degradation contract as
:func:`sports_data.props.get_game_props`. Each requested period market
counts against the Odds API free-tier quota, so the per-sport market sets
(``_PERIOD_MARKETS``) are kept to the keys books actually price.

Contract
--------
* :func:`get_half_quarters` — async, never raises, returns a ``list``
  (``[]`` on failure / no key / no period markets for the sport). One record
  per (event, period, book, market).

Result shapes
-------------
``get_half_quarters`` returns a list of:

    {
        "event": "Celtics @ Lakers",
        "event_id": "nba:eid123",
        "sport": "nba",
        "period": "first_half",   # first_half | second_half | q1..q4
        "market": "h1_totals",    # raw Odds API market key
        "home_odds": 1.91,        # moneyline/spread price or Over price
        "away_odds": 1.95,        # moneyline/spread price or Under price
        "total": 112.5,           # totals markets only, else None
        "line": None,             # spread markets only (home perspective)
        "book": "draftkings",
        "source": "the_odds_api",
    }

The ``period`` values are normalized: ``h1`` -> ``first_half``, ``h2`` ->
``second_half``, ``q1``..``q4`` unchanged.

Backoff: 1 retry, exponential (0.1s -> 0.4s). Free-API terms:
https://the-odds-api.com.

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

from datasets.sports_data.halves_common import (  # noqa: F401
    _PERIOD_LABELS,
    _PERIOD_MARKETS,
    _RETRY_CONFIG,
    _SPORTS,
    _api_key,
    _as_text,
    _bookmaker_params,
    _canonical_book,
    _canonical_key,
    _event_label,
    _period_label,
    _period_markets_for,
    _resolve_event,
    _resolve_sports,
    _to_float,
)
from datasets.sports_data.halves_fetchers import (  # noqa: F401
    _fetch_json,
    _half_quarters_odds_api,
)
from datasets.sports_data.halves_parsers import (  # noqa: F401
    _map_period_event,
    _parse_period_outcomes,
)

logger = logging.getLogger(__name__)


async def get_half_quarters(event_id: str, book: str = "all") -> list[dict[str, Any]]:
    """Fetch first-half/second-half and quarter markets for one event.

    Args:
        event_id: The event id. Accepts an optional ``sport:event_id`` prefix
            (e.g. ``nba:eid123`` or ``basketball_nba:...``) to skip the
            default-sport scan.
        book: Optional single-book filter (e.g. ``"draftkings"``). Default
            ``"all"``.

    Returns:
        A list of period records (see module docstring). ``[]`` on failure,
        when no Odds API key is configured, or when the sport has no period
        markets. Never raises.
    """
    try:
        return await _get_half_quarters(event_id, book)
    except Exception:
        logger.exception("sports_half_quarters_crashed", extra={"event_id": event_id})
        return []


async def _get_half_quarters(event_id: str, book: str) -> list[dict[str, Any]]:
    if not event_id or not str(event_id).strip():
        return []
    slugs, target_id = _resolve_event(event_id)
    if not slugs:
        logger.warning("sports_half_quarters_invalid_sport", extra={"event_id": event_id})
        return []
    if not _api_key():
        # ESPN publishes no period/quarter odds feed — return empty rather
        # than fabricate lines (same contract as props.get_game_props).
        return []
    book_slug = None
    if _canonical_book is not None and str(book or "").strip().lower() not in {"", "all"}:
        book_slug = _canonical_book(book)
    for slug in slugs:
        records = await _half_quarters_odds_api(target_id, slug, book_slug)
        if records:
            return records
    return []
