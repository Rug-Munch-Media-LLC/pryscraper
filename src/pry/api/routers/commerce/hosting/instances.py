"""Hosted-instance listing, detail, renewal, and cancellation routes."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

import logging
from typing import Any

from fastapi import Header, HTTPException

from pry.api.routers.commerce.hosting.auth import _require_owner, _resolve_user
from pry.api.routers.commerce.hosting.router import router
from pry.commerce.hosting import (
    PlanNotPurchasable,
    WalletUnconfigured,
    cancel_instance,
    get_instance,
    list_instances,
    renew_instance,
)

logger = logging.getLogger(__name__)


@router.get(
    "/v1/hosting/instances",
    summary="List the caller's hosted instances",
    description="Returns all hosted instances owned by the authenticated API key's account.",
)
async def hosting_instances(
    authorization: str = Header("", alias="Authorization"),
) -> dict[str, Any]:
    """List hosted instances for the Bearer key's owner."""
    bearer = authorization.removeprefix("Bearer ").strip()
    user_id = _resolve_user(bearer)
    return {"success": True, "data": {"instances": list_instances(user_id)}}


@router.get(
    "/v1/hosting/instances/{instance_id}",
    summary="Hosted instance details",
    description="Returns instance details + status (API-key auth; scoped to the key's owner).",
)
async def hosting_instance_detail(
    instance_id: str,
    authorization: str = Header("", alias="Authorization"),
) -> dict[str, Any]:
    """Instance details, scoped to the authenticated owner."""
    bearer = authorization.removeprefix("Bearer ").strip()
    user_id = _resolve_user(bearer)
    detail = get_instance(instance_id)
    if detail["user_id"] != user_id:
        raise HTTPException(status_code=404, detail="unknown hosted instance")
    return {"success": True, "data": {"instance": detail}}


@router.post(
    "/v1/hosting/instances/{instance_id}/renew",
    summary="Create a renewal invoice for a hosted instance",
    description=(
        "Generates a new x402 invoice bound to the instance; confirming it extends the "
        "expiry (renewal rollover) instead of provisioning a new instance."
    ),
)
async def hosting_instance_renew(
    instance_id: str,
    authorization: str = Header("", alias="Authorization"),
) -> dict[str, Any]:
    """Renewal invoice for an owned instance."""
    bearer = authorization.removeprefix("Bearer ").strip()
    user_id = _resolve_user(bearer)
    _require_owner(instance_id, user_id)
    try:
        invoice = renew_instance(instance_id)
    except PlanNotPurchasable as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except WalletUnconfigured as exc:
        logger.error("hosting_renew_wallet_unconfigured", extra={"instance_id": instance_id})
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {
        "success": True,
        "data": {"status_code": 402, "payment_required": invoice["payment_required"], **invoice},
    }


@router.post(
    "/v1/hosting/instances/{instance_id}/cancel",
    summary="Cancel a hosted subscription",
    description="Cancels the instance's subscription (stops renewal; status → cancelled).",
)
async def hosting_instance_cancel(
    instance_id: str,
    authorization: str = Header("", alias="Authorization"),
) -> dict[str, Any]:
    """Cancel an owned instance's subscription."""
    bearer = authorization.removeprefix("Bearer ").strip()
    user_id = _resolve_user(bearer)
    _require_owner(instance_id, user_id)
    return {"success": True, "data": {"instance": cancel_instance(instance_id)}}
