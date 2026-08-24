"""USDA NASS crop prices — free QuickStats API (key optional).

The USDA National Agricultural Statistics Service publishes crop prices
through the QuickStats API (https://quickstats.nass.usda.gov). A free API
key (https://quickstats.nass.usda.gov/api) may be set via the
``PRY_NASS_API_KEY`` env var; without a key every function degrades to
``[]`` (never raises) — the module still works fully when a key is set.

Contract
--------
* :func:`get_crop_prices` — async, never raises, returns a ``list``
  (``[]`` on failure). Searches prices-received records for a commodity.

Result shapes
-------------
``get_crop_prices`` returns a list of::

    {
        "commodity": "CORN",
        "state": "IOWA",
        "year": 2025,
        "price": 4.32,
        "unit": "$ / BU",
        "short_desc": "CORN - PRICE RECEIVED, MEASURED IN $ / BU",
        "source": "usda_nass",
    }

``price`` is a float or ``None`` when NASS withholds the value (``(D)`` /
``(NA)`` placeholders). Backoff: 2 retries, exponential (0.4s -> 1.6s).

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
import os
from datetime import UTC, datetime
from typing import Any

import httpx

from pry.engine.retry import RetryConfig, async_retry

logger = logging.getLogger(__name__)

_BASE_URL = "https://quickstats.nass.usda.gov/api/api_GET/"
_TIMEOUT = httpx.Timeout(20.0)
_RETRY_CONFIG = RetryConfig(
    max_retries=2,
    base_delay=0.4,
    max_delay=1.6,
    retryable_exceptions=(httpx.HTTPError,),
)
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; pryscraper-climate/1.0; "
        "+https://git.rugmunch.io/RugMunchMedia/pryscraper)"
    ),
    "Accept": "application/json",
}

# Free API key: https://quickstats.nass.usda.gov/api
_API_KEY_ENV = "PRY_NASS_API_KEY"
_MAX_LIMIT = 500  # keep requests light; NASS caps at 50_000
_RECENT_YEARS = 6


def _api_key() -> str:
    """Return the configured NASS API key, or '' when missing."""
    return os.environ.get(_API_KEY_ENV, "").strip()


def _as_text(value: Any) -> str | None:
    """Coerce a JSON value to str/None ('' -> None)."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _as_price(value: Any) -> float | None:
    """Parse a NASS ``Value`` field to float; None for withheld/NA marks."""
    text = _as_text(value)
    if not text:
        return None
    if text.startswith("(") or text.upper() in {"NA", "D", "Z", "S"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _map_price_row(raw: dict[str, Any]) -> dict[str, Any]:
    """Map a NASS QuickStats row onto the canonical price record."""
    year = _as_text(raw.get("year"))
    return {
        "commodity": _as_text(raw.get("commodity_desc")),
        "state": _as_text(raw.get("state_name")),
        "year": int(year) if year and year.isdigit() else None,
        "price": _as_price(raw.get("Value")),
        "unit": _as_text(raw.get("unit_desc")),
        "short_desc": _as_text(raw.get("short_desc")),
        "source": "usda_nass",
    }


async def _fetch_prices(params: dict[str, str]) -> list[dict[str, Any]] | None:
    """GET the NASS QuickStats search and return the ``data`` list.

    Returns ``None`` on any failure (network, non-2xx, malformed payload).
    """

    async def _one() -> list[dict[str, Any]]:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT, headers=_HEADERS, follow_redirects=True
        ) as client:
            response = await client.get(_BASE_URL, params=params)
            response.raise_for_status()
            payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("NASS payload is not an object")
        data = payload.get("data")
        if not isinstance(data, list):
            raise ValueError("NASS payload missing data list")
        return data

    try:
        return await async_retry(_one, config=_RETRY_CONFIG)
    except (httpx.HTTPError, OSError, ValueError):
        return None


# ── Public API ─────────────────────────────────────────────────────────
async def get_crop_prices(
    commodity: str, state: str = "all", limit: int = 20
) -> list[dict[str, Any]]:
    """Return recent prices-received records for a crop commodity.

    Args:
        commodity: Commodity name, case-insensitive (e.g. ``"wheat"``,
            ``"corn"``, ``"soybeans"``, ``"milk"``).
        state: State name or ``"all"`` (e.g. ``"Iowa"``). National
            aggregates are returned for ``"all"``.
        limit: Max records to return (1-500).

    Returns:
        List of price records (see module docstring). ``[]`` on failure
        (no API key, network error, bad payload). Never raises.
    """
    try:
        return await _get_crop_prices(commodity, state, limit)
    except Exception:
        logger.exception("usda_nass_crop_prices_crashed", extra={"commodity": commodity})
        return []


async def _get_crop_prices(commodity: str, state: str, limit: int) -> list[dict[str, Any]]:
    name = (commodity or "").strip().upper()
    if not name:
        return []
    key = _api_key()
    if not key:
        logger.warning("usda_nass_api_key_missing")
        return []
    params: dict[str, str] = {
        "key": key,
        "commodity_desc": name,
        "statisticcat_desc": "PRICES RECEIVED",
        "year__GE": str(datetime.now(UTC).year - _RECENT_YEARS),
        "format": "JSON",
        "limit": str(max(1, min(int(limit), _MAX_LIMIT))),
    }
    state_name = (state or "").strip().title()
    if state_name and state_name.lower() != "all":
        params["state_name"] = state_name
    data = await _fetch_prices(params)
    if data is None:
        return []
    return [_map_price_row(raw) for raw in data if isinstance(raw, dict)]
