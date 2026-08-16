"""Pry — travel router.

Exposes flight search + cheap-date grid (Google Flights scraping) and hotel
rate lookups (Google Hotels / Booking.com) backed by the ``travel``
subpackage (built in parallel by other agents, so every import is guarded
and degrades to 502 while a module has not landed yet).

Endpoints:
- GET /v1/travel/flights/grid   — cheapest flight per day over a date range
- GET /v1/travel/flights/search — one-way flight options for a single date
- GET /v1/travel/hotels/rates   — per-night hotel rates for a stay window
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import importlib
import logging
from typing import Any

from fastapi import APIRouter, Query

from errors import ExternalServiceError

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Travel"])

_DATE_PATTERN = r"^\d{4}-\d{2}-\d{2}$"


def _travel_module(module_name: str) -> Any:
    """Import a ``travel`` submodule with a guarded ImportError.

    The modules are created in parallel by other agents; return None when
    a module has not landed yet so callers can degrade gracefully.
    """
    try:
        return importlib.import_module(f"travel.{module_name}")
    except ImportError:
        logger.warning("travel_module_unavailable", extra={"module_name": module_name})
        return None


def _module_unavailable(module_name: str) -> None:
    raise ExternalServiceError(
        f"travel.{module_name} is not available yet (parallel build in progress)"
    )


@router.get(
    "/v1/travel/flights/grid",
    tags=["Travel"],
    summary="Cheapest flight per day over a date range (Google Flights)",
)
async def travel_flights_grid(
    origin: str = Query(..., min_length=3, max_length=3, description="IATA origin code, e.g. JFK"),
    dest: str = Query(
        ..., min_length=3, max_length=3, description="IATA destination code, e.g. CDG"
    ),
    start_date: str = Query(..., pattern=_DATE_PATTERN, description="First date (YYYY-MM-DD)"),
    end_date: str = Query(..., pattern=_DATE_PATTERN, description="Last date (YYYY-MM-DD)"),
) -> dict[str, Any]:
    """Return the cheapest flight option per day between start_date and end_date."""
    mod = _travel_module("flights")
    if mod is None:
        _module_unavailable("flights")
    data = await mod.cheapest_date_grid(origin, dest, start_date, end_date)
    return {
        "success": True,
        "data": data,
        "origin": origin.upper(),
        "dest": dest.upper(),
        "start_date": start_date,
        "end_date": end_date,
    }


@router.get(
    "/v1/travel/flights/search",
    tags=["Travel"],
    summary="Search one-way flights for a single date (Google Flights)",
)
async def travel_flights_search(
    origin: str = Query(..., min_length=3, max_length=3, description="IATA origin code, e.g. JFK"),
    dest: str = Query(
        ..., min_length=3, max_length=3, description="IATA destination code, e.g. CDG"
    ),
    date: str = Query(..., pattern=_DATE_PATTERN, description="Departure date (YYYY-MM-DD)"),
    limit: int = Query(20, ge=1, le=200, description="Max results (default: 20)"),
) -> dict[str, Any]:
    """Return one-way flight options for origin → dest on date, cheapest first."""
    mod = _travel_module("flights")
    if mod is None:
        _module_unavailable("flights")
    data = await mod.search_flights(origin, dest, date, limit=limit)
    return {
        "success": True,
        "data": data,
        "origin": origin.upper(),
        "dest": dest.upper(),
        "date": date,
        "limit": limit,
    }


@router.get(
    "/v1/travel/hotels/rates",
    tags=["Travel"],
    summary="Per-night hotel rates for a stay window (Google Hotels / Booking.com)",
)
async def travel_hotels_rates(
    hotel_name: str = Query(..., min_length=2, description="Hotel name or location query"),
    checkin: str = Query(..., pattern=_DATE_PATTERN, description="Check-in date (YYYY-MM-DD)"),
    checkout: str = Query(..., pattern=_DATE_PATTERN, description="Check-out date (YYYY-MM-DD)"),
) -> dict[str, Any]:
    """Return per-night rates for a hotel across scraped sources."""
    mod = _travel_module("hotels")
    if mod is None:
        _module_unavailable("hotels")
    data = await mod.get_hotel_rates(hotel_name, checkin, checkout)
    return {"success": True, "data": data}
