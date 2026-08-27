"""Pry — Healthcare data router.

Exposes clinical-trial search (clinicaltrials.gov), US drug pricing
(NADAC + GoodRx), and car/home insurance quote feasibility backed by the
``healthcare_data`` subpackage (built in parallel by other agents, so every
import is guarded and degrades to 502 while a module has not landed yet).

Endpoints:
- GET /v1/health/trials/search       — search clinical trials by keyword
- GET /v1/health/trials/{nct_id}     — one clinical trial by NCT id
- GET /v1/health/drug/{drug}         — US drug price by name
- GET /v1/health/insurance/quotes    — car/home insurance quote feasibility
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

router = APIRouter(tags=["Healthcare Data"])


def _healthcare_module(module_name: str) -> Any:
    """Import a ``healthcare_data`` submodule with a guarded ImportError.

    The modules are created in parallel by other agents; return None when a
    module has not landed yet so callers can degrade gracefully.
    """
    try:
        return importlib.import_module(f"datasets.healthcare_data.{module_name}")
    except ImportError:
        logger.warning("healthcare_data_module_unavailable", extra={"module_name": module_name})
        return None


def _module_unavailable(module_name: str) -> None:
    raise ExternalServiceError(
        f"healthcare_data.{module_name} is not available yet (parallel build in progress)"
    )


@router.get(
    "/v1/health/trials/search",
    tags=["Healthcare Data"],
    summary="Search clinical trials by keyword (clinicaltrials.gov)",
)
async def health_trials_search(
    query: str = Query(
        ...,
        min_length=1,
        max_length=500,
        description="Keyword search (e.g. 'alzheimer', 'covid vaccine')",
    ),
    limit: int = Query(20, ge=1, le=100, description="Max results (default: 20)"),
) -> dict[str, Any]:
    """Search clinical trials by keyword."""
    mod = _healthcare_module("clinical_trials")
    if mod is None:
        _module_unavailable("clinical_trials")
    data = await mod.search_trials(query=query, limit=limit)
    return {"success": True, "data": data, "query": query, "limit": limit}


@router.get(
    "/v1/health/trials/{nct_id}",
    tags=["Healthcare Data"],
    summary="Get one clinical trial by NCT id",
)
async def health_trials_get(nct_id: str) -> dict[str, Any]:
    """Fetch a single clinical trial by its NCT id."""
    mod = _healthcare_module("clinical_trials")
    if mod is None:
        _module_unavailable("clinical_trials")
    data = await mod.get_trial(nct_id)
    return {"success": True, "data": data, "nct_id": nct_id}


@router.get(
    "/v1/health/drug/{drug}",
    tags=["Healthcare Data"],
    summary="Get a US drug price by name (NADAC + GoodRx)",
)
async def health_drug_price(drug: str) -> dict[str, Any]:
    """Fetch a US drug price by name (brand or generic)."""
    mod = _healthcare_module("drug_pricing")
    if mod is None:
        _module_unavailable("drug_pricing")
    data = await mod.get_drug_price(drug)
    return {"success": True, "data": data, "drug": drug}


@router.get(
    "/v1/health/insurance/quotes",
    tags=["Healthcare Data"],
    summary="Car/home insurance quote feasibility + public rate tables",
)
async def health_insurance_quotes(
    coverage_type: str = Query(
        "auto",
        description="'auto' (default) | 'home'",
    ),
    zip: str = Query("", max_length=10, description="US zip code for the quote request"),
) -> dict[str, Any]:
    """Probe insurance quote forms; returns documented feasibility payload."""
    mod = _healthcare_module("insurance")
    if mod is None:
        _module_unavailable("insurance")
    profile: dict[str, Any] = {"coverage_type": coverage_type}
    if zip:
        profile["zip"] = zip
    data = await mod.get_insurance_quotes(profile)
    return {"success": True, "data": data, "coverage_type": coverage_type}
