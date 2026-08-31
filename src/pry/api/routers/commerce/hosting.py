"""Pry — cloud hosting router (signup, checkout, instance management).

Exposes the hosted-pry signup + checkout surface over HTTP, modeled on the
billing packs / subscription routers:

- ``POST /v1/hosting/signup``                        — create a signup invoice
  and return the x402 402 payment manifest (treasury payTo). FREE control
  plane — the monetary gate is the manifest itself.
- ``POST /v1/hosting/signup/{invoice_id}/confirm``   — verify + settle the
  x402 payment, provision the hosted instance, mint an API key.
- ``GET  /v1/hosting/instances``                     — list the caller's
  instances (API-key auth via Bearer token).
- ``GET  /v1/hosting/instances/{id}``                — instance details.
- ``POST /v1/hosting/instances/{id}/renew``          — renewal x402 invoice.
- ``POST /v1/hosting/instances/{id}/cancel``         — cancel subscription.

Wallet fail-closed rule (mirrors the packs router): signup/renew NEVER emit a
placeholder payTo — an unconfigured wallet returns 503.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Body, Header, HTTPException
from pydantic import BaseModel, Field

from pry.commerce.hosting import (
    InstanceNotFound,
    PlanNotFound,
    PlanNotPurchasable,
    Underpayment,
    WalletUnconfigured,
    cancel_instance,
    confirm_hosting_payment,
    create_hosting_signup,
    get_instance,
    list_instances,
    list_plans,
    renew_instance,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["hosting"])


class HostingSignupRequest(BaseModel):
    """Start a hosted-instance signup (returns a 402 payment manifest)."""

    user_email: str = Field(..., description="Account email for the hosted instance")
    plan_tier: str = Field(..., description="Plan tier (pro / team)")


class HostingConfirmRequest(BaseModel):
    """Confirm the on-chain payment for a hosting invoice."""

    tx_hash: str = Field(..., description="On-chain transaction hash / signature")
    network: str = Field("", description="Network the payment was made on")
    asset: str = Field("", description="Asset paid")
    authorization: dict[str, Any] | None = Field(
        None, description="Optional EIP-3009 authorization object"
    )


def _resolve_user(bearer: str) -> str:
    """Resolve a Bearer API key to its owner user_id (401 on failure)."""
    from pry.api.api_keys_service import authenticate

    record = authenticate(bearer.strip())
    if record is None:
        raise HTTPException(status_code=401, detail="invalid or missing API key")
    return str(record["user_id"])


@router.get(
    "/v1/hosting/plans",
    summary="List hosted-instance plans",
    description="Returns the server-authoritative hosting plan catalog (Pro / Team / Enterprise).",
)
async def hosting_plans() -> dict[str, Any]:
    """List the available hosting plans."""
    return {"success": True, "data": {"plans": list_plans()}}


@router.post(
    "/v1/hosting/signup",
    status_code=200,
    summary="Create a hosting signup invoice (x402 402 payment manifest)",
    description=(
        "Returns a spec-compliant x402 PaymentRequired manifest with the real configured "
        "treasury as payToAddress. The client pays USDC on-chain, then calls "
        "POST /v1/hosting/signup/{invoice_id}/confirm to provision the instance. "
        "Fails closed (503) if no real receiving wallet is configured."
    ),
)
async def hosting_signup(payload: HostingSignupRequest) -> dict[str, Any]:
    """Create an x402 manifest for a hosted-instance signup."""
    try:
        invoice = create_hosting_signup(payload.user_email, payload.plan_tier)
    except PlanNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PlanNotPurchasable as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except WalletUnconfigured as exc:
        logger.error("hosting_signup_wallet_unconfigured", extra={"plan_tier": payload.plan_tier})
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {
        "success": True,
        "data": {"status_code": 402, "payment_required": invoice["payment_required"], **invoice},
    }


@router.post(
    "/v1/hosting/signup/{invoice_id}/confirm",
    summary="Verify a hosting payment and provision the instance",
    description=(
        "Verifies the on-chain payment via the x402 self-facilitator and settles it on-chain. "
        "On success provisions the hosted instance, mints an API key (plaintext shown once) "
        "and credits the prepaid ledger. Under-payments are rejected (never provisioned)."
    ),
)
async def hosting_signup_confirm(
    invoice_id: str,
    payload: HostingConfirmRequest = Body(...),
) -> dict[str, Any]:
    """Verify + settle a hosting signup, provisioning the instance."""
    try:
        result = await confirm_hosting_payment(
            invoice_id,
            payload.tx_hash,
            network=payload.network,
            asset=payload.asset,
            authorization=payload.authorization,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Underpayment as exc:
        logger.warning("hosting_underpayment_rejected", extra={"invoice_id": invoice_id})
        return {"success": False, "data": {"paid": False, "reason": exc.reason or str(exc)}}
    if not result["paid"]:
        return {"success": False, "data": result}
    return {"success": True, "data": result}


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


def _require_owner(instance_id: str, user_id: str) -> None:
    """Raise 404 unless *instance_id* exists and belongs to *user_id*."""
    from pry.commerce.hosting import list_instances

    owned = {i["instance_id"] for i in list_instances(user_id)}
    if instance_id not in owned:
        # Distinguish unknown vs foreign without leaking existence.
        try:
            get_instance(instance_id)
        except InstanceNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        raise HTTPException(status_code=404, detail="unknown hosted instance")


__all__ = ["router"]
