"""Pry — climate data router (NOAA weather + USDA crop prices).

Exposes the ``climate_data`` subpackage (built in parallel by other
agents, so every import is guarded and degrades to 502 while a module
has not landed yet).

Endpoints:
- GET /v1/climate/forecast   — NOAA NWS forecast + alerts for "lat,lon"
- GET /v1/climate/agri       — USDA NASS crop prices received

This router is NOT wired into api.py yet (the lead wires new routers
after the parallel build lands). It is import-safe standalone.
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

from pry.core.errors import ExternalServiceError, InvalidRequestError

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Climate Data"])


def _climate_module(module_name: str) -> Any:
    """Import a ``climate_data`` submodule with a guarded ImportError.

    The modules are created in parallel by other agents; return None when
    a module has not landed yet so callers can degrade gracefully.
    """
    try:
        return importlib.import_module(f"climate_data.{module_name}")
    except ImportError:
        logger.warning("climate_data_module_unavailable", extra={"module_name": module_name})
        return None


def _module_unavailable(module_name: str) -> None:
    raise ExternalServiceError(
        f"climate_data.{module_name} is not available yet (parallel build in progress)"
    )


@router.get(
    "/v1/climate/forecast",
    tags=["Climate Data"],
    summary="NOAA NWS forecast, current conditions and alerts for a lat/lon point",
)
async def climate_forecast(
    location: str = Query(
        ..., min_length=3, description='Point as "lat,lon" decimal degrees, e.g. "38.9072,-77.0369"'
    ),
    days: int = Query(7, ge=1, le=14, description="Max forecast days to return (1-14)"),
) -> dict[str, Any]:
    """Return current conditions + daily forecast + alerts for a point."""
    mod = _climate_module("weather")
    if mod is None:
        _module_unavailable("weather")
    data = await mod.get_forecast(location, days=days)
    return {
        "success": True,
        "data": data,
        "location": location,
        "days": days,
    }


@router.get(
    "/v1/climate/agri",
    tags=["Climate Data"],
    summary="USDA NASS crop prices received",
)
async def climate_agri(
    commodity: str = Query(
        ..., min_length=1, description='Commodity name, e.g. "wheat", "corn", "soybeans"'
    ),
    state: str = Query("all", description='State name or "all" for national aggregates'),
    limit: int = Query(20, ge=1, le=200, description="Max records (default: 20)"),
) -> dict[str, Any]:
    """Return recent prices-received records for a crop commodity."""
    if not commodity.strip():
        raise InvalidRequestError("commodity must not be blank")
    mod = _climate_module("agri")
    if mod is None:
        _module_unavailable("agri")
    data = await mod.get_crop_prices(commodity, state=state, limit=limit)
    return {
        "success": True,
        "data": data,
        "commodity": commodity,
        "state": state,
        "limit": limit,
    }
