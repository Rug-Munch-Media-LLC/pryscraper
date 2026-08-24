"""Pry — Local business data router (Google Maps / Yelp listings + reviews).

Endpoints backed by the ``local_data`` subpackage (``places``, ``reviews``),
which is built in parallel by other agents — every import is guarded and
degrades to 502 (ExternalServiceError) while a module has not landed yet.

Endpoints:
- GET /v1/local/places/search          — Google Maps business search
- GET /v1/local/places/{place_id}      — place detail (+ popular times)
- GET /v1/local/reviews/{place_id}     — Google Maps / Yelp review history

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
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

router = APIRouter(tags=["LocalData"])


def _local_data_module(module_name: str) -> Any:
    """Import a ``local_data`` submodule with a guarded ImportError.

    The modules are created in parallel by other agents; return None when a
    module has not landed yet so callers can degrade gracefully.
    """
    try:
        return importlib.import_module(f"local_data.{module_name}")
    except ImportError:
        # NOTE: ``extra`` must not use stdlib LogRecord-reserved keys (e.g.
        # "module"), which raise KeyError on plain stdlib loggers.
        logger.warning("local_data_module_unavailable", extra={"module_name": module_name})
        return None


def _module_unavailable(module_name: str) -> None:
    raise ExternalServiceError(
        f"local_data.{module_name} is not available yet (parallel build in progress)"
    )


@router.get(
    "/v1/local/places/search",
    tags=["LocalData"],
    summary="Search Google Maps for local businesses",
)
async def local_places_search(
    query: str = Query(..., min_length=1, description="Business type / keyword, e.g. 'taco'"),
    location: str = Query("", description="City / region, e.g. 'Austin TX'"),
    limit: int = Query(20, ge=1, le=100, description="Max results (default: 20)"),
) -> dict[str, Any]:
    """Return Google Maps business listings for a query + location."""
    mod = _local_data_module("places")
    if mod is None:
        _module_unavailable("places")
    data = await mod.search_places(query, location=location, limit=limit)
    return {
        "success": True,
        "data": data,
        "query": query,
        "location": location,
        "limit": limit,
    }


@router.get(
    "/v1/local/places/{place_id}",
    tags=["LocalData"],
    summary="Get a Google Maps place (detail + popular times)",
)
async def local_places_get(place_id: str) -> dict[str, Any]:
    """Return a single place record, including popular times when available."""
    mod = _local_data_module("places")
    if mod is None:
        _module_unavailable("places")
    data = await mod.get_place(place_id)
    return {"success": True, "data": data, "place_id": place_id}


@router.get(
    "/v1/local/reviews/{place_id}",
    tags=["LocalData"],
    summary="Get review history for a place (Google Maps / Yelp)",
)
async def local_reviews_get(
    place_id: str,
    source: str = Query(
        "google",
        pattern="^(google|yelp)$",
        description="Review source: 'google' (CID/slug) or 'yelp' (biz slug)",
    ),
    limit: int = Query(20, ge=1, le=100, description="Max reviews (default: 20)"),
) -> dict[str, Any]:
    """Return reviews for a place from Google Maps or Yelp."""
    mod = _local_data_module("reviews")
    if mod is None:
        _module_unavailable("reviews")
    data = await mod.get_reviews(place_id, source=source, limit=limit)
    return {
        "success": True,
        "data": data,
        "place_id": place_id,
        "source": source,
        "limit": limit,
    }
