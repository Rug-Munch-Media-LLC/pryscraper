"""Plan, signup, payment-confirmation, and email-verification routes."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

import logging
from typing import Any

from fastapi import Body, HTTPException, Query, Response

# FastAPI evaluates postponed endpoint annotations at runtime.
from pry.api.routers.commerce.hosting.models import (  # noqa: TC001
    HostingConfirmRequest,
    HostingSignupRequest,
    HostingVerifyRequest,
)
from pry.api.routers.commerce.hosting.router import router
from pry.commerce.hosting import (
    PlanNotFound,
    PlanNotPurchasable,
    Underpayment,
    WalletUnconfigured,
    confirm_hosting_payment,
    create_hosting_signup,
    list_plans,
)

logger = logging.getLogger(__name__)


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


@router.post(
    "/v1/hosting/signup/{invoice_id}/verify",
    summary="Verify the signup email for a hosting invoice",
    description=(
        "Confirms the signup email with the 6-char code sent at invoice "
        "creation. Payment confirm is refused until the email is verified "
        "(proof-of-ownership for the portal/receipt email). 400 on a wrong "
        "code, 404 for an unknown invoice."
    ),
)
async def hosting_signup_verify(
    invoice_id: str,
    payload: HostingVerifyRequest = Body(...),
) -> dict[str, Any]:
    """Mark a hosting invoice's signup email as verified."""
    from pry.commerce.hosting import verify_hosting_email

    try:
        result = verify_hosting_email(invoice_id, payload.code)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if not result["verified"]:
        return {"success": False, "data": result}
    return {"success": True, "data": result}


@router.get(
    "/v1/hosting/verify/{invoice_id}",
    summary="Email verification link target (human-friendly)",
    description=(
        "Verifies the signup email from the link in the verification email "
        "and renders a simple confirmation page (humans click links from "
        "mail clients). 404 for an unknown invoice."
    ),
    include_in_schema=False,
)
async def hosting_verify_link(invoice_id: str, code: str = Query("")) -> Response:
    from pry.commerce.hosting import verify_hosting_email

    try:
        result = verify_hosting_email(invoice_id, code)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if result["verified"]:
        body = (
            "<h1>✅ Email verified</h1><p>Your email is verified — you can now "
            "confirm your payment on the checkout page.</p>"
        )
    else:
        body = (
            "<h1>❌ Verification failed</h1><p>That verification code is not "
            "valid for this invoice. Check the link in your email.</p>"
        )
    html_page = (
        f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
        f"<title>Pry — email verification</title></head>"
        f'<body style="font-family:ui-sans-serif,system-ui,sans-serif;'
        f"background:#0b0e14;color:#e6e9f0;display:flex;justify-content:center;"
        f'padding:60px 16px"><div>{body}</div></body></html>'
    )
    return Response(content=html_page, media_type="text/html")
