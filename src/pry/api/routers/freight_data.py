"""Pry — freight / logistics data router.

Exposes container freight rates (Freightos FBX + Drewry WCI fallback) and
FMC agreements backed by the ``freight_data`` subpackage (built in parallel
by other agents, so every import is guarded and degrades to 502 while a
module has not landed yet).

Endpoints:
- GET /v1/freight/rates        — 40ft container spot rates per trade lane
- GET /v1/freight/fmc/contracts — agreements on file at the FMC

This router is NOT wired into api.py yet (the lead wires new routers after
the parallel build lands). It is import-safe standalone.
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

router = APIRouter(tags=["Freight Data"])


def _freight_module(module_name: str) -> Any:
    """Import a ``freight_data`` submodule with a guarded ImportError.

    The modules are created in parallel by other agents; return None when a
    module has not landed yet so callers can degrade gracefully.
    """
    try:
        return importlib.import_module(f"datasets.freight_data.{module_name}")
    except ImportError:
        logger.warning("freight_data_module_unavailable", extra={"module_name": module_name})
        return None


def _module_unavailable(module_name: str) -> None:
    raise ExternalServiceError(
        f"freight_data.{module_name} is not available yet (parallel build in progress)"
    )


@router.get(
    "/v1/freight/rates",
    tags=["Freight Data"],
    summary="Container spot rates (40ft) per trade lane — Freightos FBX + Drewry WCI fallback",
)
async def freight_rates(
    route: str = Query(
        "all",
        min_length=1,
        description=(
            'Lane filter: "all", an FBX ticker ("FBX01"), a route slug '
            '("china-us-west-coast"), an origin/destination substring '
            '("china"), or an alias ("transpacific", "asia-europe", '
            '"transatlantic")'
        ),
    ),
    limit: int = Query(20, ge=1, le=200, description="Max records (default: 20)"),
) -> dict[str, Any]:
    """Return 40ft container spot rates per trade lane."""
    mod = _freight_module("rates")
    if mod is None:
        _module_unavailable("rates")
    data = await mod.get_container_rates(route=route, limit=limit)
    return {
        "success": True,
        "data": data,
        "route": route,
        "limit": limit,
    }


@router.get(
    "/v1/freight/fmc/contracts",
    tags=["Freight Data"],
    summary="Federal Maritime Commission agreements matching a query",
)
async def fmc_contracts(
    query: str = Query(
        ...,
        min_length=1,
        description='Free-text filter, e.g. "Evergreen", "201353", "North Europe"',
    ),
    limit: int = Query(20, ge=1, le=200, description="Max records (default: 20)"),
) -> dict[str, Any]:
    """Return FMC agreements matching a free-text query."""
    if not query.strip():
        raise InvalidRequestError("query must not be blank")
    mod = _freight_module("rates")
    if mod is None:
        _module_unavailable("rates")
    data = await mod.get_fmc_contracts(query, limit=limit)
    return {
        "success": True,
        "data": data,
        "query": query,
        "limit": limit,
    }
