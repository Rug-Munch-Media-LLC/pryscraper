"""Pry — Government contract bidding data router.

Exposes government contract solicitations / awards and federal grant
opportunities backed by the ``bidding_data`` subpackage. Every import is
guarded and degrades to 502 while a module has not landed yet.

Endpoints:
- GET /v1/bidding/contracts      — search contracts across SAM.gov, TED,
  NY Contract Reporter and FedConnect
- GET /v1/bidding/contracts/{id} — one contract by source-prefixed id
  (sam: / ted: / ny: / fedconnect:; bare ids default to SAM.gov)
- GET /v1/bidding/grants         — search federal grants (Grants.gov)
- GET /v1/bidding/grants/{id}    — one grant by Grants.gov opp id
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

router = APIRouter(tags=["Bidding Data"])


def _bidding_module(module_name: str) -> Any:
    """Import a ``bidding_data`` submodule with a guarded ImportError.

    The modules are created in parallel by other agents; return None when a
    module has not landed yet so callers can degrade gracefully.
    """
    try:
        return importlib.import_module(f"datasets.bidding_data.{module_name}")
    except ImportError:
        logger.warning("bidding_module_unavailable", extra={"module_name": module_name})
        return None


def _module_unavailable(module_name: str) -> None:
    raise ExternalServiceError(
        f"bidding_data.{module_name} is not available yet (parallel build in progress)"
    )


@router.get(
    "/v1/bidding/contracts",
    tags=["Bidding Data"],
    summary="Search government contract solicitations + awards",
)
async def bidding_contracts_search(
    query: str = Query(
        ...,
        min_length=1,
        max_length=500,
        description="Keyword search (e.g. 'aircraft maintenance')",
    ),
    limit: int = Query(20, ge=1, le=200, description="Max results (default: 20)"),
) -> dict[str, Any]:
    """Search contract opportunities across SAM.gov, TED, NY and FedConnect."""
    mod = _bidding_module("contracts")
    if mod is None:
        _module_unavailable("contracts")
    data = await mod.search_contracts(query=query, limit=limit)
    return {"success": True, "data": data, "query": query}


@router.get(
    "/v1/bidding/contracts/{contract_id}",
    tags=["Bidding Data"],
    summary="Get one contract by source-prefixed id",
)
async def bidding_contracts_get(contract_id: str) -> dict[str, Any]:
    """Fetch a single contract by its source-prefixed id (sam:/ted:/ny:/fedconnect:)."""
    mod = _bidding_module("contracts")
    if mod is None:
        _module_unavailable("contracts")
    data = await mod.get_contract(contract_id)
    return {"success": True, "data": data, "contract_id": contract_id}


@router.get(
    "/v1/bidding/grants",
    tags=["Bidding Data"],
    summary="Search federal grant opportunities (Grants.gov)",
)
async def bidding_grants_search(
    query: str = Query(
        ...,
        min_length=1,
        max_length=500,
        description="Keyword search (e.g. 'community development')",
    ),
    limit: int = Query(20, ge=1, le=100, description="Max results (default: 20)"),
) -> dict[str, Any]:
    """Search federal grant opportunities from Grants.gov."""
    mod = _bidding_module("grants")
    if mod is None:
        _module_unavailable("grants")
    data = await mod.search_grants(query=query, limit=limit)
    return {"success": True, "data": data, "query": query}


@router.get(
    "/v1/bidding/grants/{grant_id}",
    tags=["Bidding Data"],
    summary="Get one grant by Grants.gov opp id",
)
async def bidding_grants_get(grant_id: str) -> dict[str, Any]:
    """Fetch a single grant by its Grants.gov opp id."""
    mod = _bidding_module("grants")
    if mod is None:
        _module_unavailable("grants")
    data = await mod.get_grant(grant_id)
    return {"success": True, "data": data, "grant_id": grant_id}
