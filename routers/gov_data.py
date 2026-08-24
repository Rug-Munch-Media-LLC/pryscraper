"""Pry — Government data router.

Exposes federal procurement opportunities (SAM.gov) and product recalls
(CPSC / FDA openFDA) backed by the ``gov_data`` subpackage. Every import is
guarded and degrades to 502 while a module has not landed yet.

Endpoints:
- GET /v1/gov/procurement/search    — search SAM.gov contract opportunities
- GET /v1/gov/procurement/{id}      — one SAM.gov opportunity by notice id
- GET /v1/gov/recalls/search        — search CPSC + FDA product recalls
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

router = APIRouter(tags=["Government Data"])


def _gov_module(module_name: str) -> Any:
    """Import a ``gov_data`` submodule with a guarded ImportError.

    The modules are created in parallel by other agents; return None when a
    module has not landed yet so callers can degrade gracefully.
    """
    try:
        return importlib.import_module(f"gov_data.{module_name}")
    except ImportError:
        logger.warning("gov_data_module_unavailable", extra={"module_name": module_name})
        return None


def _module_unavailable(module_name: str) -> None:
    raise ExternalServiceError(
        f"gov_data.{module_name} is not available yet (parallel build in progress)"
    )


@router.get(
    "/v1/gov/procurement/search",
    tags=["Government Data"],
    summary="Search federal procurement opportunities (SAM.gov)",
)
async def gov_procurement_search(
    query: str = Query(
        ...,
        min_length=1,
        max_length=500,
        description="Keyword search (e.g. 'aircraft maintenance')",
    ),
    limit: int = Query(20, ge=1, le=200, description="Max results (default: 20)"),
) -> dict[str, Any]:
    """Search SAM.gov contract opportunities by keyword."""
    mod = _gov_module("procurement")
    if mod is None:
        _module_unavailable("procurement")
    data = await mod.search_opportunities(query=query, limit=limit)
    return {"success": True, "data": data, "query": query}


@router.get(
    "/v1/gov/procurement/{notice_id}",
    tags=["Government Data"],
    summary="Get one SAM.gov opportunity by notice id",
)
async def gov_procurement_get(notice_id: str) -> dict[str, Any]:
    """Fetch a single SAM.gov opportunity by its noticeId."""
    mod = _gov_module("procurement")
    if mod is None:
        _module_unavailable("procurement")
    data = await mod.get_opportunity(notice_id)
    return {"success": True, "data": data, "notice_id": notice_id}


@router.get(
    "/v1/gov/recalls/search",
    tags=["Government Data"],
    summary="Search CPSC + FDA product recalls",
)
async def gov_recalls_search(
    query: str = Query("", max_length=500, description="Keyword search (empty = recent recalls)"),
    agency: str = Query("all", description="'all' (default) | 'cpsc' | 'fda'"),
    limit: int = Query(20, ge=1, le=100, description="Max results (default: 20)"),
) -> dict[str, Any]:
    """Search product recalls across CPSC and/or FDA openFDA."""
    mod = _gov_module("recalls")
    if mod is None:
        _module_unavailable("recalls")
    data = await mod.search_recalls(query=query, agency=agency, limit=limit)
    return {"success": True, "data": data, "query": query, "agency": agency}
