"""Pry — research data router (scholarly search + domain intelligence).

Exposes the ``research_data`` subpackage (built in parallel by other
agents, so every import is guarded and degrades to 502 while a module
has not landed yet).

Endpoints:
- GET /v1/research/papers       — scholarly search (OpenAlex + Crossref)
- GET /v1/research/domain/{domain} — RDAP WHOIS lookup for a domain

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

from errors import ExternalServiceError, InvalidRequestError

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Research Data"])


def _research_module(module_name: str) -> Any:
    """Import a ``research_data`` submodule with a guarded ImportError.

    The modules are created in parallel by other agents; return None when
    a module has not landed yet so callers can degrade gracefully.
    """
    try:
        return importlib.import_module(f"research_data.{module_name}")
    except ImportError:
        logger.warning("research_data_module_unavailable", extra={"module_name": module_name})
        return None


def _module_unavailable(module_name: str) -> None:
    raise ExternalServiceError(
        f"research_data.{module_name} is not available yet (parallel build in progress)"
    )


@router.get(
    "/v1/research/papers",
    tags=["Research Data"],
    summary="Search scholarly papers (OpenAlex primary, Crossref fallback)",
)
async def research_papers(
    query: str = Query(
        ..., min_length=1, description="Search terms, e.g. 'attention is all you need'"
    ),
    limit: int = Query(20, ge=1, le=100, description="Max results (default: 20)"),
) -> dict[str, Any]:
    """Return scholarly works matching the query. Free, keyless sources."""
    if not query.strip():
        raise InvalidRequestError("query must not be blank")
    mod = _research_module("academic")
    if mod is None:
        _module_unavailable("academic")
    data = await mod.search_papers(query, limit=limit)
    return {
        "success": True,
        "data": data,
        "query": query,
        "limit": limit,
    }


@router.get(
    "/v1/research/domain/{domain}",
    tags=["Research Data"],
    summary="RDAP WHOIS lookup for a domain",
)
async def research_domain(domain: str) -> dict[str, Any]:
    """Return registration data (registrar, dates, status, nameservers)."""
    if not domain.strip() or "." not in domain:
        raise InvalidRequestError("domain must be a valid domain name")
    mod = _research_module("domain")
    if mod is None:
        _module_unavailable("domain")
    data = await mod.whois_lookup(domain)
    return {
        "success": True,
        "data": data,
        "domain": domain,
    }
