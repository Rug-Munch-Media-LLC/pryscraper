"""Fetchers for freight rate sources (FBX, Drewry WCI, FMC agreements).

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

from datasets.freight_data.rates_common import (
    _DREWRY_INFOGRAM,
    _FBX_LANES,
    _FBX_PAGE,
    _FMC_INDEX,
    _MAX_LIMIT,
    _ROUTE_ALIASES,
    _fetch_text,
    _match_route,
)
from datasets.freight_data.rates_parsers import (
    _drewry_records_from_page,
    _fbx_records_from_page,
    _parse_fmc_html,
)

logger = logging.getLogger(__name__)


# ── Public: container rates ────────────────────────────────────────────
async def get_container_rates(route: str = "all", limit: int = 20) -> list[dict[str, Any]]:
    """Return container spot rates for 40ft containers.

    Args:
        route: Route filter — ``"all"`` (default) or a lane: an FBX ticker
            (``"FBX01"``), a route slug (``"china-us-west-coast"``), an
            origin/destination substring (``"china"``), or an alias
            (``"transpacific"``, ``"asia-europe"``, ``"transatlantic"``).
        limit: Max records to return (1-50).

    Returns:
        List of rate records (see module docstring). Freightos FBX is the
        primary source; Drewry WCI is used as a fallback when Freightos
        yields nothing. ``[]`` on total failure. Never raises.
    """
    try:
        return await _get_container_rates(route, limit)
    except Exception:
        logger.exception("freight_rates_crashed", extra={"route": route, "limit": limit})
        return []


async def _get_container_rates(route: str, limit: int) -> list[dict[str, Any]]:
    records = await _fbx_rates(route, limit)
    if not records:
        records = await _drewry_rates(route, limit)
    return records[:limit]


async def _fbx_rates(route: str, limit: int) -> list[dict[str, Any]]:
    text = await _fetch_text(_FBX_PAGE)
    if text is None:
        return []
    records = _fbx_records_from_page(text)
    return _filter_rate_records(records, route, limit)


async def _drewry_rates(route: str, limit: int) -> list[dict[str, Any]]:
    text = await _fetch_text(_DREWRY_INFOGRAM)
    if text is None:
        return []
    records = _drewry_records_from_page(text)
    return _filter_rate_records(records, route, limit)


def _filter_rate_records(
    records: list[dict[str, Any]], route: str, limit: int
) -> list[dict[str, Any]]:
    """Apply the route filter + limit to a list of rate records."""
    query = (route or "").strip().lower()
    alias_tickers = _ROUTE_ALIASES.get(query)
    matched: list[dict[str, Any]] = []
    for record in records:
        if alias_tickers is not None:
            # Alias matches FBX tickers; Drewry records never match aliases.
            if record.get("index_source") != "freightos_fbx":
                continue
            ticker = next(
                (label for label in _FBX_LANES if _FBX_LANES[label][2] == record.get("route")),
                None,
            )
            if ticker not in alias_tickers:
                continue
            matched.append(record)
            continue
        if _match_route(record, query):
            matched.append(record)
    matched.sort(key=lambda rec: rec.get("date") or "", reverse=True)
    return matched[: max(1, min(int(limit), _MAX_LIMIT))]


# ── Public: FMC contracts ──────────────────────────────────────────────
async def get_fmc_contracts(query: str, limit: int = 20) -> list[dict[str, Any]]:
    """Return FMC agreements matching a query.

    Args:
        query: Free-text filter matched against agreement number, carrier,
            origin and destination (case-insensitive substring).
        limit: Max records to return (1-50).

    Returns:
        List of agreement records (see module docstring). The FMC has no
        public JSON API for service contracts (contracts are confidential
        by law), so this reads the public Agreement Library index and maps
        each agreement row to the closest contract-shaped record.
        ``[]`` on failure. Never raises.
    """
    try:
        if not (query or "").strip():
            return []
        return await _get_fmc_contracts(query, limit)
    except Exception:
        logger.exception("fmc_contracts_crashed", extra={"query": query, "limit": limit})
        return []


async def _get_fmc_contracts(query: str, limit: int) -> list[dict[str, Any]]:
    records = await _fetch_fmc_records(query, limit)
    return records[:limit]


async def _fetch_fmc_records(query: str, limit: int) -> list[dict[str, Any]]:
    text = await _fetch_text(_FMC_INDEX)
    if text is None:
        return []
    records = _parse_fmc_html(text)
    needle = (query or "").strip().lower()
    if needle:
        records = [
            rec
            for rec in records
            if needle in (rec.get("id") or "").lower()
            or needle in (rec.get("carrier") or "").lower()
            or needle in (rec.get("origin") or "").lower()
            or needle in (rec.get("destination") or "").lower()
        ]
    return records[: max(1, min(int(limit), _MAX_LIMIT))]
