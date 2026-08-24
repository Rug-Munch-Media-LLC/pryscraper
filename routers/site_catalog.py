"""Pry — site catalog router (assured-scrape capability registry).

Read-only lookups over the site capability catalog: every endpoint answers
"how do we scrape this site and how confident are we?" BEFORE any scrape is
attempted.

Endpoints:
- GET /v1/coverage                  — full catalog (all sites + methods)
- GET /v1/coverage/{site_id}        — one site: method + confidence + delivery schema
- GET /v1/coverage/recommend?url=…  — recommended method for a URL/domain

The ``site_catalog`` package is new and may not have landed when this router
is imported by other agents (parallel build), so the import is guarded and
the endpoints degrade to 503 while the package is missing.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Query

from pry.core.errors import ExternalServiceError, NotFoundError

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Site Catalog"])


def _catalog() -> Any:
    """Return a ``SiteCatalog`` instance, or None while the package is missing.

    Kept import-safe: ``import routers.site_catalog`` never fails even when
    ``site_catalog`` has not landed yet (parallel build).
    """
    try:
        from site_catalog.registry import SiteCatalog

        return SiteCatalog()
    except ImportError:
        logger.warning("site_catalog_unavailable", extra={"reason": "package not landed yet"})
        return None


def _require_catalog() -> Any:
    catalog = _catalog()
    if catalog is None:
        raise ExternalServiceError("site_catalog package is not available yet (parallel build)")
    return catalog


@router.get("/v1/coverage", summary="Full site capability catalog")
async def coverage() -> dict[str, Any]:
    """Return every catalogued site with its scrape method + confidence."""
    catalog = _require_catalog()
    data = catalog.coverage()
    return {"success": True, "data": data, "total": len(data)}


@router.get("/v1/coverage/recommend", summary="Recommended method for a URL or domain")
async def recommend(
    url: str = Query(
        ..., min_length=1, max_length=2048, description="URL or domain to recommend a method for"
    ),
) -> dict[str, Any]:
    """Best-known method + confidence for the target; generic fallback when unknown."""
    catalog = _require_catalog()
    rec = catalog.recommend_method(url)
    return {"success": True, "data": rec, "url": url}


@router.get("/v1/coverage/{site_id}", summary="One site capability entry")
async def get_site(site_id: str) -> dict[str, Any]:
    """Method + confidence + output (delivery) schema for a single site."""
    catalog = _require_catalog()
    entry = catalog.get_site(site_id)
    if entry is None:
        raise NotFoundError(f"site not in catalog: {site_id!r}")
    return {"success": True, "data": entry, "site_id": site_id}
