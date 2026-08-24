"""Pry — Legal / public-records router.

Exposes docket search (CourtListener), SEC EDGAR filing search / insider
trades, and OFAC SDN sanctions screening backed by the ``legal_docs``
subpackage (built in parallel, so every import is guarded and degrades to
502 while a module has not landed yet).

Endpoints:
- GET /v1/legal/dockets/search      — CourtListener docket search
- GET /v1/legal/dockets/{docket_id} — single docket lookup
- GET /v1/legal/sec/search          — SEC EDGAR filing search by ticker/form
- GET /v1/legal/sec/insider/{ticker}— Form 4 insider-trade signals
- GET /v1/legal/sanctions/{name}    — OFAC SDN name screening
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

router = APIRouter(tags=["Legal & Public Records"])


def _legal_module(module_name: str) -> Any:
    """Import a ``legal_docs`` submodule with a guarded ImportError.

    The modules are created in parallel by other agents; return None when a
    module has not landed yet so callers can degrade gracefully.
    """
    try:
        return importlib.import_module(f"legal_docs.{module_name}")
    except ImportError:
        logger.warning("legal_docs_module_unavailable", extra={"module_name": module_name})
        return None


def _module_unavailable(module_name: str) -> None:
    raise ExternalServiceError(
        f"legal_docs.{module_name} is not available yet (parallel build in progress)"
    )


@router.get(
    "/v1/legal/dockets/search",
    tags=["Legal & Public Records"],
    summary="Search U.S. court dockets (CourtListener)",
)
async def legal_dockets_search(
    query: str = Query(
        ..., min_length=1, max_length=500, description="Full-text docket search query"
    ),
    limit: int = Query(20, ge=1, le=100, description="Max results (default: 20)"),
) -> dict[str, Any]:
    """Search CourtListener dockets by full-text query."""
    mod = _legal_module("dockets")
    if mod is None:
        _module_unavailable("dockets")
    data = await mod.search_dockets(query=query, limit=limit)
    return {"success": True, "data": data, "query": query}


@router.get(
    "/v1/legal/dockets/{docket_id}",
    tags=["Legal & Public Records"],
    summary="Get one court docket by CourtListener id",
)
async def legal_dockets_get(docket_id: int) -> dict[str, Any]:
    """Fetch a single docket by its CourtListener integer id."""
    mod = _legal_module("dockets")
    if mod is None:
        _module_unavailable("dockets")
    data = await mod.get_docket(docket_id)
    return {"success": True, "data": data, "docket_id": docket_id}


@router.get(
    "/v1/legal/sec/search",
    tags=["Legal & Public Records"],
    summary="Search SEC EDGAR filings by ticker and form type",
)
async def legal_sec_search(
    ticker: str = Query(..., min_length=1, max_length=10, description="Company ticker (e.g. AAPL)"),
    form_type: str = Query(
        "8-K", min_length=1, max_length=20, description="SEC form type (default: 8-K)"
    ),
    limit: int = Query(20, ge=1, le=100, description="Max results (default: 20)"),
) -> dict[str, Any]:
    """Search EDGAR filings for a ticker by form type."""
    mod = _legal_module("sec_filings")
    if mod is None:
        _module_unavailable("sec_filings")
    data = await mod.search_filings(ticker=ticker, form_type=form_type, limit=limit)
    return {"success": True, "data": data, "ticker": ticker.upper(), "form_type": form_type}


@router.get(
    "/v1/legal/sec/insider/{ticker}",
    tags=["Legal & Public Records"],
    summary="Get recent Form 4 insider-trade filings for a ticker",
)
async def legal_sec_insider(
    ticker: str,
    limit: int = Query(20, ge=1, le=100, description="Max results (default: 20)"),
) -> dict[str, Any]:
    """List recent Form 4 (insider transaction) filings for a ticker."""
    mod = _legal_module("sec_filings")
    if mod is None:
        _module_unavailable("sec_filings")
    data = await mod.insider_trades(ticker=ticker, limit=limit)
    return {"success": True, "data": data, "ticker": ticker.upper()}


@router.get(
    "/v1/legal/sanctions/{name}",
    tags=["Legal & Public Records"],
    summary="Screen a name against the OFAC SDN sanctions list",
)
async def legal_sanctions(name: str) -> dict[str, Any]:
    """Screen a name against the OFAC Specially Designated Nationals list."""
    mod = _legal_module("sanctions")
    if mod is None:
        _module_unavailable("sanctions")
    data = await mod.screen_name(name=name)
    return {"success": True, "data": data, "name": name}
