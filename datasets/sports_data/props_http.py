"""Shared HTTP + config plumbing for the player-props modules.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

import json
import logging
import os
from typing import Any

import httpx

from datasets.shape_error import UpstreamPayloadError
from pry.engine.retry import RetryConfig, async_retry

logger = logging.getLogger(__name__)

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
            try:
                payload = response.json()
            except json.JSONDecodeError as exc:
                raise UpstreamPayloadError("sports props payload is not valid JSON") from exc
        if not isinstance(payload, (dict, list)):
            raise UpstreamPayloadError("sports props payload is not an object or array")
        return payload

    try:
        return await async_retry(_one, config=RETRY_CONFIG)
    except (httpx.HTTPError, OSError, UpstreamPayloadError) as exc:
        logger.warning(
            "sports_props_fetch_failed",
            extra={"url": url[:120], "error": str(exc)[:160]},
        )
        return None
