"""Pry — IP data router (patents, trademarks, company registry).

Exposes compliance/IP intelligence backed by the ``ip_data`` subpackage
(built in parallel by other agents, so every import is guarded and degrades
to 502 while a module has not landed yet).

Endpoints:
- GET /v1/ip/patents/search      — Google Patents patent search
- GET /v1/ip/patents/{patent_id} — single patent detail
- GET /v1/ip/trademarks/search   — USPTO trademark search
- GET /v1/ip/companies/search    — state Secretary of State registry search
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

from fastapi import APIRouter, Path, Query

from pry.core.errors import ExternalServiceError, InvalidRequestError

logger = logging.getLogger(__name__)

router = APIRouter(tags=["IP Data"])


def _ip_module(module_name: str) -> Any:
    """Import an ``ip_data`` submodule with a guarded ImportError.

    The modules are created in parallel by other agents; return None when a
    module has not landed yet so callers can degrade gracefully.
    """
    try:
        return importlib.import_module(f"ip_data.{module_name}")
    except ImportError:
        logger.warning("ip_data_module_unavailable", extra={"module_name": module_name})
        return None


def _module_unavailable(module_name: str) -> None:
    raise ExternalServiceError(
        f"ip_data.{module_name} is not available yet (parallel build in progress)"
    )


@router.get(
    "/v1/ip/patents/search",
    tags=["IP Data"],
    summary="Search patents via Google Patents",
)
async def ip_patents_search(
    q: str = Query(..., min_length=1, max_length=300, description="Free-text patent query"),
    limit: int = Query(20, ge=1, le=100, description="Max results (default: 20)"),
) -> dict[str, Any]:
    """Search the patent register (Google Patents free XHR JSON API)."""
    mod = _ip_module("patents")
    if mod is None:
        _module_unavailable("patents")
    data = await mod.search_patents(q, limit=limit)
    return {"success": True, "data": data, "query": q, "limit": limit}


@router.get(
    "/v1/ip/patents/{patent_id}",
    tags=["IP Data"],
    summary="Get a single patent by publication number",
)
async def ip_patents_get(
    patent_id: str = Path(..., min_length=3, max_length=64, description="e.g. US9012345B2"),
) -> dict[str, Any]:
    """Fetch one patent record by its publication number."""
    mod = _ip_module("patents")
    if mod is None:
        _module_unavailable("patents")
    data = await mod.get_patent(patent_id)
    if not data:
        raise InvalidRequestError(f"patent not found: {patent_id}")
    return {"success": True, "data": data, "patent_id": patent_id}


@router.get(
    "/v1/ip/trademarks/search",
    tags=["IP Data"],
    summary="Search US trademarks via USPTO",
)
async def ip_trademarks_search(
    q: str = Query(..., min_length=1, max_length=300, description="Free-text trademark query"),
    limit: int = Query(20, ge=1, le=100, description="Max results (default: 20)"),
) -> dict[str, Any]:
    """Search the USPTO trademark register (free Trademark Search JSON API)."""
    mod = _ip_module("trademarks")
    if mod is None:
        _module_unavailable("trademarks")
    data = await mod.search_trademarks(q, limit=limit)
    return {"success": True, "data": data, "query": q, "limit": limit}


@router.get(
    "/v1/ip/companies/search",
    tags=["IP Data"],
    summary="Search a state company registry (Secretary of State)",
)
async def ip_companies_search(
    name: str = Query(..., min_length=1, max_length=300, description="Business name to search"),
    state: str = Query("NV", min_length=2, max_length=2, description="Two-letter state code"),
    limit: int = Query(20, ge=1, le=100, description="Max results (default: 20)"),
) -> dict[str, Any]:
    """Search a state Secretary of State company registry by business name."""
    mod = _ip_module("company_registry")
    if mod is None:
        _module_unavailable("company_registry")
    data = await mod.search_companies(name, limit=limit)
    return {"success": True, "data": data, "name": name, "state": state.upper(), "limit": limit}
