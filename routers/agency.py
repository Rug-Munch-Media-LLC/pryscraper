"""Pry — Agency router (remaining api.py routes).

Auto-extracted from api.py during the router-split refactor.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Body

from errors import NotFoundError

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Agency"])


@router.post("/v1/agency/create", tags=["Agency"], summary="Create a white-label agency profile")
async def create_agency_endpoint(
    name: str = Body(...),
    owner_email: str = Body(...),
    custom_domain: str = Body(""),
    brand_color: str = Body("#f59e0b"),
    logo_url: str = Body(""),
) -> dict[str, Any]:
    """Create a white-label agency profile for reselling Pry.

    Agencies get:
    - Custom branding (colors, logo, domain)
    - Client management with sub-accounts
    - Usage analytics and quota management
    - API key management for each client
    """
    from agency import create_agency

    result = create_agency(name, owner_email, custom_domain, brand_color, logo_url)
    return {"success": result["success"], "data": result}


@router.get("/v1/agency/{agency_id}", tags=["Agency"], summary="Get agency profile")
async def get_agency_endpoint(agency_id: str) -> dict[str, Any]:
    """Get agency profile details."""
    from agency import get_agency

    result = get_agency(agency_id)
    if not result:
        raise NotFoundError(f"Agency not found: {agency_id}")
    return {"success": True, "data": result}


@router.put("/v1/agency/{agency_id}/branding", tags=["Agency"], summary="Update agency branding")
async def update_branding(
    agency_id: str,
    name: str | None = Body(None),
    brand_color: str | None = Body(None),
    logo_url: str | None = Body(None),
    custom_domain: str | None = Body(None),
) -> dict[str, Any]:
    """Update white-label branding for an agency."""
    from agency import update_agency_branding

    result = update_agency_branding(agency_id, name, brand_color, logo_url, custom_domain)
    return {"success": result["success"], "data": result}


@router.post(
    "/v1/agency/{agency_id}/clients", tags=["Agency"], summary="Create a client sub-account"
)
async def create_client_endpoint(
    agency_id: str,
    client_name: str = Body(...),
    client_email: str = Body(...),
    monthly_quota: int = Body(10000),
) -> dict[str, Any]:
    """Create a client sub-account under an agency.

    Each client gets their own API key and usage quota.
    """
    from agency import create_client

    result = create_client(agency_id, client_name, client_email, monthly_quota)
    return {"success": result["success"], "data": result}


@router.get("/v1/agency/{agency_id}/clients", tags=["Agency"], summary="List agency clients")
async def list_clients_endpoint(agency_id: str) -> dict[str, Any]:
    """List all clients under an agency."""
    from agency import list_clients

    clients = list_clients(agency_id)
    return {"success": True, "data": {"clients": clients, "total": len(clients)}}


@router.get(
    "/v1/agency/{agency_id}/analytics", tags=["Agency"], summary="Get agency usage analytics"
)
async def get_analytics(agency_id: str) -> dict[str, Any]:
    """Get aggregate usage analytics for an agency."""
    from agency import get_agency_analytics

    result = get_agency_analytics(agency_id)
    return {"success": True, "data": result}


@router.get("/v1/client/{client_id}/quota", tags=["Agency"], summary="Check client quota usage")
async def check_quota(client_id: str) -> dict[str, Any]:
    """Check a client's current quota usage and remaining capacity."""
    from agency import check_client_quota

    result = check_client_quota(client_id)
    return {"success": result["success"], "data": result}
