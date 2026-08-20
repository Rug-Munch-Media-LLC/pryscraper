"""Pry — GDPR router (remaining api.py routes).

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

router = APIRouter(tags=["GDPR"])


@router.post("/v1/gdpr/consent", tags=["GDPR"], summary="Record user consent for data processing")
async def record_consent_endpoint(
    user_id: str = Body(...),
    purpose: str = Body("data_collection"),
    consent_given: bool = Body(True),
    ip_address: str = Body(""),
    user_agent: str = Body(""),
) -> dict[str, Any]:
    """Record a user's consent for data processing (GDPR Art. 7).

    Stores: user hash, purpose, timestamp, IP, user agent.
    Consent expires after 365 days.
    """
    from gdpr import record_consent

    result = await record_consent(user_id, purpose, consent_given, ip_address, user_agent)
    return {"success": result["success"], "data": result}


@router.get("/v1/gdpr/consent/{user_id}", tags=["GDPR"], summary="Check user consent status")
async def check_consent_endpoint(
    user_id: str,
    purpose: str = "data_collection",
) -> dict[str, Any]:
    """Check if a user has given valid consent for data processing."""
    from gdpr import check_consent

    result = check_consent(user_id, purpose)
    return {"success": True, "data": result}


@router.post("/v1/gdpr/consent/revoke", tags=["GDPR"], summary="Revoke user consent")
async def revoke_consent_endpoint(
    user_id: str = Body(...),
    purpose: str = Body("data_collection"),
) -> dict[str, Any]:
    """Revoke a user's consent for a processing purpose (GDPR Art. 7(3))."""
    from gdpr import revoke_consent

    result = revoke_consent(user_id, purpose)
    return {"success": True, "data": result}


@router.post(
    "/v1/gdpr/deletion/request", tags=["GDPR"], summary="Request data deletion (right to erasure)"
)
async def request_deletion_endpoint(
    user_id: str = Body(...),
    reason: str = Body("user_request"),
) -> dict[str, Any]:
    """Request deletion of all data associated with a user (GDPR Art. 17).

    Creates a deletion request that can be executed immediately or
    after a holding period.
    """
    from gdpr import request_deletion

    result = await request_deletion(user_id, reason)
    return {"success": "error" not in result, "data": result}


@router.post("/v1/gdpr/deletion/execute", tags=["GDPR"], summary="Execute data deletion request")
async def execute_deletion_endpoint(
    request_id: str = Body(...),
) -> dict[str, Any]:
    """Execute a pending deletion request, removing all user data."""
    from gdpr import execute_deletion

    result = await execute_deletion(request_id)
    if "error" in result:
        raise NotFoundError(result["error"])
    return {"success": True, "data": result}


@router.get("/v1/gdpr/retention", tags=["GDPR"], summary="Get data retention policy")
async def get_retention_policy_endpoint() -> dict[str, Any]:
    """Get the current data retention policy."""
    from gdpr import get_retention_policy

    return {"success": True, "data": get_retention_policy()}


@router.post(
    "/v1/gdpr/retention/apply",
    tags=["GDPR"],
    summary="Apply retention policy to remove expired data",
)
async def apply_retention() -> dict[str, Any]:
    """Apply the retention policy, removing all expired data."""
    from gdpr import apply_retention_policy

    result = await apply_retention_policy()
    return {"success": True, "data": result}


@router.get("/v1/gdpr/audit", tags=["GDPR"], summary="Get compliance audit log")
async def get_audit_log_endpoint(days_back: int = 7) -> dict[str, Any]:
    """Get the compliance audit log for the specified period."""
    from gdpr import get_audit_log

    events = get_audit_log(days_back)
    return {"success": True, "data": {"events": events, "total": len(events)}}
