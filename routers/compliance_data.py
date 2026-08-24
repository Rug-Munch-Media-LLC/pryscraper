"""Pry — Regulatory/compliance data router.

Exposes enforcement actions and consumer complaints from FDA (openFDA),
FTC, CFPB, and SEC backed by the ``compliance_data`` subpackage. Every
import is guarded and degrades to 502 while a module has not landed yet.

Endpoints:
- GET /v1/compliance/enforcement              — search enforcement actions
- GET /v1/compliance/enforcement/{agency}/{id} — one action by prefixed id
- GET /v1/compliance/watch/{company}          — company compliance screening
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

from pry.core.errors import ExternalServiceError

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Compliance Data"])


def _compliance_module(module_name: str) -> Any:
    """Import a ``compliance_data`` submodule with a guarded ImportError.

    The modules are created in parallel by other agents; return None when a
    module has not landed yet so callers can degrade gracefully.
    """
    try:
        return importlib.import_module(f"datasets.compliance_data.{module_name}")
    except ImportError:
        logger.warning("compliance_data_module_unavailable", extra={"module_name": module_name})
        return None


def _module_unavailable(module_name: str) -> None:
    raise ExternalServiceError(
        f"compliance_data.{module_name} is not available yet (parallel build in progress)"
    )


@router.get(
    "/v1/compliance/enforcement",
    tags=["Compliance Data"],
    summary="Search regulatory enforcement actions (FDA/FTC/CFPB/SEC)",
)
async def compliance_enforcement_search(
    agency: str = Query(
        "all",
        min_length=1,
        max_length=50,
        description="'all' (default) | 'fda' | 'ftc' | 'cfpb' | 'sec'",
    ),
    query: str = Query(
        "",
        max_length=500,
        description="Keyword search (empty = recent enforcement actions)",
    ),
    limit: int = Query(20, ge=1, le=100, description="Max results (default: 20)"),
) -> dict[str, Any]:
    """Search enforcement actions across the configured agencies."""
    mod = _compliance_module("enforcement")
    if mod is None:
        _module_unavailable("enforcement")
    data = await mod.search_enforcement(agency=agency, query=query, limit=limit)
    return {"success": True, "data": data, "agency": agency, "query": query}


@router.get(
    "/v1/compliance/enforcement/{agency}/{action_id}",
    tags=["Compliance Data"],
    summary="Get one enforcement action by agency + prefixed id",
)
async def compliance_enforcement_get(
    agency: str = Path(..., min_length=1, max_length=50, description="Agency code"),
    action_id: str = Path(..., min_length=1, max_length=300, description="Prefixed id"),
) -> dict[str, Any]:
    """Fetch a single enforcement action by its prefixed id."""
    mod = _compliance_module("enforcement")
    if mod is None:
        _module_unavailable("enforcement")
    data = await mod.get_action(agency=agency, id=action_id)
    return {"success": True, "data": data, "agency": agency, "id": action_id}


@router.get(
    "/v1/compliance/watch/{company}",
    tags=["Compliance Data"],
    summary="Company compliance screening (enforcement/complaint matches)",
)
async def compliance_watch(
    company: str = Path(..., min_length=1, max_length=200, description="Company name"),
    agencies: str = Query(
        "all",
        min_length=1,
        max_length=100,
        description="'all' (default) or comma-separated subset (e.g. 'fda,sec')",
    ),
) -> dict[str, Any]:
    """Return enforcement/complaint matches for a specific company."""
    mod = _compliance_module("enforcement")
    if mod is None:
        _module_unavailable("enforcement")
    data = await mod.watch_company(company=company, agencies=agencies)
    return {"success": True, "data": data, "company": company, "agencies": agencies}
