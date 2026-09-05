"""Shared HTTP + config plumbing for the player-props modules.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

import os
from typing import Any

import httpx

from pry.engine.retry import RetryConfig, async_retry

# The Odds API endpoints. Player props live on the per-event odds endpoint —
# the events list is only used to discover event ids to scan.
ODDS_BASE = "https://api.the-odds-api.com/v4/sports"
# ESPN endpoints used by the season-average fallback.
ESPN_SEARCH = "https://site.web.api.espn.com/apis/common/v3/search"
ESPN_STATS = (
    "https://site.web.api.espn.com/apis/common/v3/sports/{sport}/{league}/athletes/{id}/stats"
)

API_KEY_ENV = "PRY_ODDS_API_KEY"
TIMEOUT = httpx.Timeout(10.0)
RETRY_CONFIG = RetryConfig(
    max_retries=1,
    base_delay=0.1,
    max_delay=0.4,
    retryable_exceptions=(httpx.HTTPError,),
)
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; pryscraper-sports/1.0; "
        "+https://git.rugmunch.io/RugMunchMedia/pryscraper)"
    ),
    "Accept": "application/json",
}

MAX_LIMIT = 100
MAX_EVENTS = 3
ODDS_API_REGIONS = "us"
SEARCH_LIMIT = 5


def api_key() -> str:
    """Return the configured The Odds API key (or '' when unset)."""
    return os.environ.get(API_KEY_ENV, "").strip()


async def fetch_json(
    url: str, params: dict[str, str] | None = None
) -> dict[str, Any] | list[Any] | None:
    """GET ``url`` and return the parsed JSON (object or array), or ``None`` on failure."""

    async def _one() -> dict[str, Any] | list[Any]:
        async with httpx.AsyncClient(
            timeout=TIMEOUT, headers=HEADERS, follow_redirects=True
        ) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            payload = response.json()
        if not isinstance(payload, (dict, list)):
            raise ValueError("sports props payload is not an object or array")
        return payload

    try:
        return await async_retry(_one, config=RETRY_CONFIG)
    except (httpx.HTTPError, OSError, ValueError):
        return None
