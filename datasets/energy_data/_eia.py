"""EIA v2 weekly retail fuel prices (gasoline / diesel).

Requires ``PRY_EIA_API_KEY`` (free registration at
https://www.eia.gov/opendata/register.php).

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

from typing import Any

import httpx

from datasets.energy_data._common import _HEADERS, _TIMEOUT, _as_float, _as_text
from pry.engine.retry import RetryConfig, async_retry

_EIA_BASE = "https://api.eia.gov/v2/petroleum/pri/gnd/data/"

# EIA v2 `pri/gnd` area facet codes (weekly retail gasoline/diesel prices).
_EIA_AREA_BY_REGION = {
    "us": "NUS",
    "padd1": "R10",
    "padd2": "R20",
    "padd3": "R30",
    "padd4": "R40",
    "padd5": "R50",
}
_EIA_ALL_AREAS = ("NUS", "R10", "R20", "R30", "R40", "R50")
# (product facet code, canonical fuel label)
_EIA_PRODUCTS = (
    ("EPM0", "gasoline"),
    ("EPD0", "premium gasoline"),
    ("EDI0", "diesel"),
)
_MAX_FUEL_ROWS = 60


def _fuel_areas(region: str) -> list[str]:
    """Resolve a fuel-price region to EIA duoarea facet codes ([] = unknown)."""
    text = (region or "").strip().lower()
    if not text:
        return []
    if text == "all":
        return list(_EIA_ALL_AREAS)
    if text in _EIA_AREA_BY_REGION:
        return [_EIA_AREA_BY_REGION[text]]
    return []


def _area_label(area: str) -> str:
    """Map an EIA duoarea code back to the canonical region label."""
    for label, code in _EIA_AREA_BY_REGION.items():
        if code == area:
            return label
    return area.lower()


def _parse_eia_payload(area: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Parse one EIA v2 response into fuel-price records.

    Rows are sorted newest-first by period; keep the latest period per
    product facet code.
    """
    rows = payload.get("response", {}).get("data")
    if not isinstance(rows, list):
        return []
    latest_by_product: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        product = _as_text(row.get("product"))
        if not product or product in latest_by_product:
            continue
        latest_by_product[product] = row
    records: list[dict[str, Any]] = []
    for product_code, fuel in _EIA_PRODUCTS:
        row = latest_by_product.get(product_code)
        if not row:
            continue
        price = _as_float(row.get("value"))
        date = _as_text(row.get("period"))
        if price is None or not date:
            continue
        records.append(
            {
                "region": _area_label(area),
                "fuel": fuel,
                "price": price,
                "unit": _as_text(row.get("units")) or "$/GAL",
                "date": date,
            }
        )
    return records


async def _fetch_eia_area(
    area: str, api_key: str, retry_config: RetryConfig
) -> list[dict[str, Any]]:
    """Fetch the latest weekly gasoline/diesel prices for one EIA area.

    ``retry_config`` is injected by the orchestrator so the retry policy
    stays patchable in one place (``lmp._RETRY_CONFIG``).
    """
    params: dict[str, str] = {
        "frequency": "weekly",
        "data[0]": "value",
        "facets[process][]": "PTE",
        "facets[duoarea][]": area,
        "sort[0][column]": "period",
        "sort[0][direction]": "desc",
        "length": str(_MAX_FUEL_ROWS),
        "api_key": api_key,
    }

    async def _one() -> dict[str, Any]:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT, headers=_HEADERS, follow_redirects=True
        ) as client:
            response = await client.get(_EIA_BASE, params=params)
            response.raise_for_status()
            payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("EIA payload is not an object")
        return payload

    try:
        payload = await async_retry(_one, config=retry_config)
    except (httpx.HTTPError, OSError, ValueError):
        return []
    return _parse_eia_payload(area, payload)
