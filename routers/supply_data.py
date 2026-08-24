"""Pry — supply-chain + B2B lead-gen router (imports + firmographics).

Exposes the ``supply_data`` subpackage (built in parallel by other
agents, so every import is guarded and degrades to 502 while a module
has not landed yet).

Endpoints:
- GET /v1/supply/imports/{company}      — ImportYeti/Panjiva-style import
  records for a company (partner API via ``PRY_IMPORTS_API_KEY``).
- GET /v1/supply/firmographics/{company} — B2B firmographics (website,
  tech stack, industry, LinkedIn, hiring openings, funding/headcount).

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

router = APIRouter(tags=["Supply Data"])


def _supply_module(module_name: str) -> Any:
    """Import a ``supply_data`` submodule with a guarded ImportError.

    The modules are created in parallel by other agents; return None when
    a module has not landed yet so callers can degrade gracefully.
    """
    try:
        return importlib.import_module(f"datasets.supply_data.{module_name}")
    except ImportError:
        logger.warning("supply_data_module_unavailable", extra={"module_name": module_name})
        return None


def _module_unavailable(module_name: str) -> None:
    raise ExternalServiceError(
        f"supply_data.{module_name} is not available yet (parallel build in progress)"
    )


@router.get(
    "/v1/supply/imports/{company}",
    tags=["Supply Data"],
    summary="ImportYeti/Panjiva-style import records for a company",
)
async def supply_imports(
    company: str,
    limit: int = Query(20, ge=1, le=200, description="Max import records (1-200)"),
) -> dict[str, Any]:
    """Return bill-of-lading style import records for a company."""
    if not company.strip():
        raise InvalidRequestError("company must not be blank")
    mod = _supply_module("imports")
    if mod is None:
        _module_unavailable("imports")
    data = await mod.get_import_records(company, limit=limit)
    return {
        "success": True,
        "data": data,
        "company": company,
        "limit": limit,
    }


@router.get(
    "/v1/supply/firmographics/{company}",
    tags=["Supply Data"],
    summary="B2B firmographics for a company (website, tech stack, hiring, funding)",
)
async def supply_firmographics(company: str) -> dict[str, Any]:
    """Return firmographics for a company (name, headcount, funding, tech)."""
    if not company.strip():
        raise InvalidRequestError("company must not be blank")
    mod = _supply_module("firmographics")
    if mod is None:
        _module_unavailable("firmographics")
    data = await mod.get_company_firmographics(company)
    return {
        "success": True,
        "data": data,
        "company": company,
    }
