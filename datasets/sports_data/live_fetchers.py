"""HTTP fetchers for live scores/odds (ESPN scoreboards + The Odds API).

Split out of ``live.py`` (god-file reduction). The ``live.py`` facade
re-exports everything here so the surface is unchanged.

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

import httpx

from datasets.sports_data.live_common import (
    _ESPN_SCOREBOARD,
    _HEADERS,
    _RETRY_CONFIG,
    _TIMEOUT,
)
from datasets.sports_data.odds import _SPORTS
from pry.engine.retry import async_retry


async def _fetch_json(
    url: str, params: dict[str, str] | None = None
) -> dict[str, Any] | list[Any] | None:
    """GET ``url`` and return the parsed JSON (object or array), or ``None`` on failure."""

    async def _one() -> dict[str, Any] | list[Any]:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT, headers=_HEADERS, follow_redirects=True
        ) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            payload = response.json()
        if not isinstance(payload, (dict, list)):
            raise ValueError("sports live payload is not an object or array")
        return payload

    try:
        return await async_retry(_one, config=_RETRY_CONFIG)
    except (httpx.HTTPError, OSError, ValueError):
        return None


async def _espn_scoreboard(slug: str) -> dict[str, Any] | None:
    """Fetch one league's ESPN scoreboard (or ``None`` on failure/403)."""
    espn = _SPORTS[slug][1]
    if espn is None:
        return None
    espn_sport, espn_league = espn
    url = _ESPN_SCOREBOARD.format(sport=espn_sport, league=espn_league)
    payload = await _fetch_json(url)
    if isinstance(payload, dict):
        return payload
    return None
