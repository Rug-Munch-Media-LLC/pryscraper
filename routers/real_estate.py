"""Pry — real-estate listings & property-records router.

Exposes Zillow listing lookups, location searches (Zillow SRP page with a
Redfin GIS fallback), and county assessor property records (free public
ArcGIS REST FeatureServers) backed by the ``real_estate`` subpackage. That
package is built in parallel by other agents, so every import is guarded
and degrades to 502 while a module has not landed yet.

Endpoints:
- GET /v1/realestate/listing/{zillow_id}        — single listing by zpid
- GET /v1/realestate/search                     — listings by location/status
- GET /v1/realestate/property/{county}/{parcel_id} — county property record
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

from pry.core.errors import ExternalServiceError

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Real Estate"])


def _real_estate_module() -> Any:
    """Import the ``real_estate`` package with a guarded ImportError.

    The package is created in parallel by other agents; return None when
    it has not landed yet so callers can degrade gracefully.
    """
    try:
        return importlib.import_module("real_estate")
    except ImportError:
        logger.warning("real_estate_module_unavailable")
        return None


def _module_unavailable() -> None:
    raise ExternalServiceError("real_estate is not available yet (parallel build in progress)")


@router.get(
    "/v1/realestate/listing/{zillow_id}",
    tags=["Real Estate"],
    summary="Look up a single real-estate listing by Zillow id",
)
async def real_estate_listing(zillow_id: str) -> dict[str, Any]:
    """Return address, price, zestimate, beds/baths, sqft, and history."""
    mod = _real_estate_module()
    if mod is None:
        _module_unavailable()
    data = await mod.get_listing(zillow_id)
    return {"success": bool(data), "data": data}


@router.get(
    "/v1/realestate/search",
    tags=["Real Estate"],
    summary="Search real-estate listings by location",
)
async def real_estate_search(
    location: str = Query(..., description="City or neighborhood, e.g. 'Austin, TX'"),
    status: str = Query("for_sale", description="'for_sale' | 'for_rent' | 'sold'"),
    limit: int = Query(20, ge=1, le=50, description="Max listings (default: 20)"),
) -> dict[str, Any]:
    """Search listings; Zillow SRP first, Redfin GIS API as fallback."""
    mod = _real_estate_module()
    if mod is None:
        _module_unavailable()
    data = await mod.search_listings(location, status=status, limit=limit)
    return {
        "success": True,
        "data": data,
        "location": location,
        "status": status,
        "count": len(data),
    }


@router.get(
    "/v1/realestate/property/{county}/{parcel_id}",
    tags=["Real Estate"],
    summary="Look up a county property record by parcel id",
)
async def real_estate_property(county: str, parcel_id: str) -> dict[str, Any]:
    """Return owner, assessed value, tax, and sale history (ArcGIS REST)."""
    mod = _real_estate_module()
    if mod is None:
        _module_unavailable()
    data = await mod.get_property(parcel_id, county)
    return {"success": bool(data), "data": data}
