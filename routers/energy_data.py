"""Pry — energy markets data router (ISO LMP + EIA fuel prices).

Exposes the ``energy_data`` subpackage (built in parallel by other
agents, so every import is guarded and degrades to 502 while a module
has not landed yet).

Endpoints:
- GET /v1/energy/lmp         — ISO day-ahead locational marginal prices
  (NYISO keyless CSV; PJM / ERCOT / CAISO via optional ``PRY_PJM_API_KEY``
  / ``gridstatus``)
- GET /v1/energy/fuel-prices — weekly retail gasoline/diesel prices (EIA
  v2, free key via ``PRY_EIA_API_KEY``)

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

from pry.core.errors import ExternalServiceError

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Energy Data"])


def _energy_module(module_name: str) -> Any:
    """Import an ``energy_data`` submodule with a guarded ImportError.

    The modules are created in parallel by other agents; return None when
    a module has not landed yet so callers can degrade gracefully.
    """
    try:
        return importlib.import_module(f"energy_data.{module_name}")
    except ImportError:
        logger.warning("energy_data_module_unavailable", extra={"module_name": module_name})
        return None


def _module_unavailable(module_name: str) -> None:
    raise ExternalServiceError(
        f"energy_data.{module_name} is not available yet (parallel build in progress)"
    )


@router.get(
    "/v1/energy/lmp",
    tags=["Energy Data"],
    summary="ISO day-ahead locational marginal prices",
)
async def energy_lmp(
    region: str = Query(
        "all",
        min_length=1,
        description='ISO name — "nyiso", "pjm", "ercot", "caiso" — or "all"',
    ),
    date: str = Query(
        "today",
        min_length=1,
        description='"today" or "YYYY-MM-DD" (the trading day)',
    ),
) -> dict[str, Any]:
    """Return day-ahead LMP records for the requested ISO region(s)."""
    mod = _energy_module("lmp")
    if mod is None:
        _module_unavailable("lmp")
    data = await mod.get_lmp(region=region, date=date)
    return {
        "success": True,
        "data": data,
        "region": region,
        "date": date,
    }


@router.get(
    "/v1/energy/fuel-prices",
    tags=["Energy Data"],
    summary="Weekly retail fuel prices from EIA",
)
async def energy_fuel_prices(
    region: str = Query(
        "all",
        min_length=1,
        description='"us", "padd1".."padd5", or "all"',
    ),
) -> dict[str, Any]:
    """Return weekly retail gasoline/diesel prices for the requested region(s)."""
    mod = _energy_module("lmp")
    if mod is None:
        _module_unavailable("lmp")
    data = await mod.get_fuel_prices(region=region)
    return {
        "success": True,
        "data": data,
        "region": region,
    }
