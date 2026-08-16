"""Pry — grocery prices + restaurant menu router.

Exposes grocery prices by ZIP (Kroger API + Walmart store-scrape fallback)
and restaurant menus (JSON-LD / HTML scrape) backed by the ``food_data``
subpackage (built in parallel by other agents, so every import is guarded
and degrades to 502 while a module has not landed yet).

Endpoints:
- GET /v1/food/grocery        — grocery prices for ``query`` in ``zip_code``
- GET /v1/food/restaurant/{name} — restaurant menu for ``name`` (optional
  ``location`` hint)

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

from errors import ExternalServiceError, InvalidRequestError

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Food Data"])


def _food_module(module_name: str) -> Any:
    """Import a ``food_data`` submodule with a guarded ImportError.

    The modules are created in parallel by other agents; return None when
    a module has not landed yet so callers can degrade gracefully.
    """
    try:
        return importlib.import_module(f"food_data.{module_name}")
    except ImportError:
        logger.warning("food_data_module_unavailable", extra={"module_name": module_name})
        return None


def _module_unavailable(module_name: str) -> None:
    raise ExternalServiceError(
        f"food_data.{module_name} is not available yet (parallel build in progress)"
    )


@router.get(
    "/v1/food/grocery",
    tags=["Food Data"],
    summary="Grocery prices for a product query in a ZIP code",
)
async def food_grocery(
    query: str = Query(
        ..., min_length=1, max_length=200, description='Product query, e.g. "milk", "bananas"'
    ),
    zip_code: str = Query(
        ..., min_length=5, max_length=10, description="US ZIP code (5 digits or ZIP+4)"
    ),
    limit: int = Query(20, ge=1, le=100, description="Max price records (default: 20)"),
) -> dict[str, Any]:
    """Return grocery prices (Kroger API, Walmart scrape fallback)."""
    if not query.strip():
        raise InvalidRequestError("query must not be blank")
    if not zip_code.strip():
        raise InvalidRequestError("zip_code must not be blank")
    mod = _food_module("grocery")
    if mod is None:
        _module_unavailable("grocery")
    data = await mod.get_grocery_prices(query, zip_code, limit=limit)
    return {
        "success": True,
        "data": data,
        "query": query,
        "zip_code": zip_code,
        "limit": limit,
    }


@router.get(
    "/v1/food/restaurant/{name}",
    tags=["Food Data"],
    summary="Restaurant menu for a restaurant name",
)
async def food_restaurant(
    name: str,
    location: str = Query(
        "", max_length=200, description='Optional location hint, e.g. "Cincinnati, OH"'
    ),
) -> dict[str, Any]:
    """Return a restaurant menu (JSON-LD extraction, HTML fallback)."""
    if not name.strip():
        raise InvalidRequestError("name must not be blank")
    mod = _food_module("restaurants")
    if mod is None:
        _module_unavailable("restaurants")
    data = await mod.get_restaurant_menu(name, location=location)
    return {
        "success": True,
        "data": data,
        "name": name,
        "location": location,
    }
