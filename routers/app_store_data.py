"""Pry — app-store intelligence router (Apple App Store + Google Play).

Exposes the ``app_store_data`` subpackage (built in parallel by other
agents, so every import is guarded and degrades to 502 while a module
has not landed yet).

Endpoints:
- GET /v1/appstore/search       — keyword search across Apple + Google Play
- GET /v1/appstore/apple/{app_id}       — Apple App Store app details
- GET /v1/appstore/apple/{app_id}/reviews — Apple App Store recent reviews
- GET /v1/appstore/play/{package}       — Google Play app details

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

router = APIRouter(tags=["App Store Data"])


def _appstore_module(module_name: str) -> Any:
    """Import an ``app_store_data`` submodule with a guarded ImportError.

    The modules are created in parallel by other agents; return None when
    a module has not landed yet so callers can degrade gracefully.
    """
    try:
        return importlib.import_module(f"app_store_data.{module_name}")
    except ImportError:
        logger.warning("appstore_module_unavailable", extra={"module_name": module_name})
        return None


def _module_unavailable(module_name: str) -> None:
    raise ExternalServiceError(
        f"app_store_data.{module_name} is not available yet (parallel build in progress)"
    )


@router.get(
    "/v1/appstore/search",
    tags=["App Store Data"],
    summary="Search apps on the Apple App Store and Google Play",
)
async def appstore_search(
    query: str = Query(..., min_length=1, description="Search terms, e.g. 'crypto wallet'"),
    store: str = Query(
        "auto",
        pattern="^(auto|apple|play)$",
        description="Store to search: 'apple', 'play', or 'auto' (both)",
    ),
    limit: int = Query(20, ge=1, le=100, description="Max results per store (default: 20)"),
) -> dict[str, Any]:
    """Return app records matching the query from the chosen store(s)."""
    if not query.strip():
        raise InvalidRequestError("query must not be blank")
    apple_mod = _appstore_module("apple")
    if apple_mod is None:
        _module_unavailable("apple")
    results: list[dict[str, Any]] = []
    if store in ("auto", "apple"):
        apple_hits = await apple_mod.search_apps(query, limit=limit)
        for hit in apple_hits:
            hit = dict(hit)
            hit["store"] = "apple"
            results.append(hit)
    if store in ("auto", "play"):
        play_mod = _appstore_module("google_play")
        if play_mod is None:
            _module_unavailable("google_play")
        play_hits = await play_mod.search_apps(query, limit=limit)
        for hit in play_hits:
            hit = dict(hit)
            hit["store"] = "play"
            results.append(hit)
    return {
        "success": True,
        "data": results,
        "query": query,
        "store": store,
        "limit": limit,
    }


@router.get(
    "/v1/appstore/apple/{app_id}",
    tags=["App Store Data"],
    summary="Apple App Store app details by numeric App Store id",
)
async def appstore_apple_details(app_id: str) -> dict[str, Any]:
    """Return details (rating, price, description, screenshots, ...)."""
    if not app_id.strip() or not app_id.isdigit():
        raise InvalidRequestError("app_id must be a numeric App Store id")
    mod = _appstore_module("apple")
    if mod is None:
        _module_unavailable("apple")
    data = await mod.get_app_details(app_id)
    return {
        "success": True,
        "data": data,
        "app_id": app_id,
    }


@router.get(
    "/v1/appstore/apple/{app_id}/reviews",
    tags=["App Store Data"],
    summary="Most recent Apple App Store customer reviews",
)
async def appstore_apple_reviews(
    app_id: str,
    limit: int = Query(50, ge=1, le=200, description="Max reviews (default: 50)"),
) -> dict[str, Any]:
    """Return recent customer reviews (author, rating, body, version)."""
    if not app_id.strip() or not app_id.isdigit():
        raise InvalidRequestError("app_id must be a numeric App Store id")
    mod = _appstore_module("apple")
    if mod is None:
        _module_unavailable("apple")
    data = await mod.get_reviews(app_id, limit=limit)
    return {
        "success": True,
        "data": data,
        "app_id": app_id,
        "limit": limit,
    }


@router.get(
    "/v1/appstore/play/{package}",
    tags=["App Store Data"],
    summary="Google Play app details by Android package id",
)
async def appstore_play_details(package: str) -> dict[str, Any]:
    """Return details (rating, price, installs, description, ...)."""
    if not package.strip() or "." not in package:
        raise InvalidRequestError("package must be a valid Android package id")
    mod = _appstore_module("google_play")
    if mod is None:
        _module_unavailable("google_play")
    data = await mod.get_app_details(package)
    return {
        "success": True,
        "data": data,
        "package": package,
    }
