"""ERCOT real-time system-wide prices — keyless public dashboard feed.

Honest flag: the dashboard endpoint is *unofficial* (ERCOT's documented
API requires a free subscription key) and only exposes a system-wide
hub-bus average for the current real-time window; the requested date is
best-effort.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

from typing import Any

import httpx

from datasets.energy_data._common import _HEADERS, _TIMEOUT, _as_float, _as_text, _ct_ts_to_utc

_ERCOT_RT_URL = "https://www.ercot.com/api/1/services/read/dashboards/systemWidePrices.json"


def _parse_ercot_payload(payload: Any) -> list[dict[str, Any]]:
    """Parse the ERCOT system-wide real-time price dashboard feed.

    The ``systemWidePrices.json`` dashboard returns ``rtSppData`` rows with
    ``interval`` (CT wall-clock) and ``hbBusAvg`` ($/MWh system-wide).
    """
    if not isinstance(payload, dict):
        return []
    rows = payload.get("rtSppData")
    if not isinstance(rows, list):
        return []
    records: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        ts = _as_text(row.get("interval"))
        price = _as_float(row.get("hbBusAvg"))
        if not ts or price is None:
            continue
        records.append(
            {
                "region": "ercot",
                "node": "HB_BUS_AVG",
                "timestamp": _ct_ts_to_utc(ts),
                "price_usd_mwh": price,
                "lmp_type": "RTM",
            }
        )
    return records


async def _fetch_ercot(start_date: str) -> list[dict[str, Any]]:
    """Fetch ERCOT system-wide real-time prices from the public dashboard.

    Keyless and unauthenticated. The feed only exposes the current
    real-time window, so ``start_date`` is best-effort (the requested day
    is included only if the feed happens to cover it).
    """
    try:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT, headers=_HEADERS, follow_redirects=True
        ) as client:
            response = await client.get(_ERCOT_RT_URL)
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, OSError, ValueError):
        return []
    return _parse_ercot_payload(payload)
