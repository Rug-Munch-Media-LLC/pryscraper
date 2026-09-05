"""Transport and Odds API fetchers for period (half/quarter) markets.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

from typing import Any
from urllib.parse import quote

import httpx

from datasets.sports_data.halves_common import (
    _HEADERS,
    _ODDS_API_REGIONS,
    _ODDS_BASE,
    _RETRY_CONFIG,
    _SPORTS,
    _TIMEOUT,
    _api_key,
    _bookmaker_params,
    _period_markets_for,
)
from pry.engine.retry import async_retry


async def _fetch_json(
    url: str, params: dict[str, str] | None = None
) -> dict[str, Any] | list[Any] | None:
    """GET ``url`` and return the parsed JSON (object or array), or ``None``."""

    async def _one() -> dict[str, Any] | list[Any]:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT, headers=_HEADERS, follow_redirects=True
        ) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            payload = response.json()
        if not isinstance(payload, (dict, list)):
            raise ValueError("sports period payload is not an object or array")
        return payload

    try:
        return await async_retry(_one, config=_RETRY_CONFIG)
    except (httpx.HTTPError, OSError, ValueError):
        return None


async def _half_quarters_odds_api(
    event_id: str, sport_slug: str, book_slug: str | None
) -> list[dict[str, Any]]:
    """Fetch real period markets from The Odds API for one event."""
    key = _api_key()
    if not key:
        return []
    market_keys = _period_markets_for(sport_slug)
    if not market_keys:
        return []
    odds_key, _espn = _SPORTS[sport_slug]
    url = f"{_ODDS_BASE}/{quote(odds_key)}/events/{quote(event_id)}/odds"
    params: dict[str, str] = {
        "apiKey": key,
        "regions": _ODDS_API_REGIONS,
        "markets": ",".join(market_keys),
        "oddsFormat": "decimal",
    }
    if book_slug is not None and _bookmaker_params is not None:
        api_book = _bookmaker_params(book_slug)
        if api_book:
            params["bookmakers"] = api_book
    payload = await _fetch_json(url, params)
    if not isinstance(payload, dict):
        return []
    from datasets.sports_data.halves_parsers import _map_period_event

    return _map_period_event(payload, sport_slug, book_slug)
