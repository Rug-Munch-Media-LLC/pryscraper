"""Pry — GDPR router: consent, erasure, retention, audit and domain purge."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Body

from pry.core.domain_blocks import _DDL, is_domain_blocked, purge_domain  # noqa: F401
from pry.core.errors import InvalidRequestError, NotFoundError

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
    """Record consent (GDPR Art. 7); consent expires after 365 days."""
    from pry.compliance.gdpr import record_consent

    result = await record_consent(user_id, purpose, consent_given, ip_address, user_agent)
    return {"success": result["success"], "data": result}


@router.get("/v1/gdpr/consent/{user_id}", tags=["GDPR"], summary="Check user consent status")
async def check_consent_endpoint(user_id: str, purpose: str = "data_collection") -> dict[str, Any]:
    from pry.compliance.gdpr import check_consent

    return {"success": True, "data": check_consent(user_id, purpose)}


@router.post("/v1/gdpr/consent/revoke", tags=["GDPR"], summary="Revoke user consent")
async def revoke_consent_endpoint(
    user_id: str = Body(...), purpose: str = Body("data_collection")
) -> dict[str, Any]:
    from pry.compliance.gdpr import revoke_consent

    return {"success": True, "data": revoke_consent(user_id, purpose)}


@router.post(
    "/v1/gdpr/deletion/request", tags=["GDPR"], summary="Request data deletion (right to erasure)"
)
async def request_deletion_endpoint(
    user_id: str = Body(...), reason: str = Body("user_request")
) -> dict[str, Any]:
    from pry.compliance.gdpr import request_deletion

    result = await request_deletion(user_id, reason)
    return {"success": "error" not in result, "data": result}


@router.post("/v1/gdpr/deletion/execute", tags=["GDPR"], summary="Execute data deletion request")
async def execute_deletion_endpoint(request_id: str = Body(...)) -> dict[str, Any]:
    from pry.compliance.gdpr import execute_deletion

    result = await execute_deletion(request_id)
    if "error" in result:
        raise NotFoundError(result["error"])
    return {"success": True, "data": result}


@router.get("/v1/gdpr/retention", tags=["GDPR"], summary="Get data retention policy")
async def get_retention_policy_endpoint() -> dict[str, Any]:
    from pry.compliance.gdpr import get_retention_policy

    return {"success": True, "data": get_retention_policy()}


@router.post(
    "/v1/gdpr/retention/apply",
    tags=["GDPR"],
    summary="Apply retention policy to remove expired data",
)
async def apply_retention() -> dict[str, Any]:
    from pry.compliance.gdpr import apply_retention_policy

    return {"success": True, "data": await apply_retention_policy()}


@router.post(
    "/v1/gdpr/domain/purge",
    tags=["GDPR"],
    summary="Purge all stored data for a domain (dry-run by default)",
)
async def purge_domain_endpoint(
    domain: str = Body(...), dry_run: bool = Body(True)
) -> dict[str, Any]:
    try:
        result = purge_domain(domain, dry_run)
    except ValueError as exc:
        raise InvalidRequestError(str(exc)) from exc
    return {"success": True, "data": result}


@router.get("/v1/gdpr/audit", tags=["GDPR"], summary="Get compliance audit log")
async def get_audit_log_endpoint(days_back: int = 7) -> dict[str, Any]:
    from pry.compliance.gdpr import get_audit_log

    events = get_audit_log(days_back)
    return {"success": True, "data": {"events": events, "total": len(events)}}
