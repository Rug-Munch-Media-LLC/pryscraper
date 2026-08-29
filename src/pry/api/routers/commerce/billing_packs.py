"""Pry — billing packs router (bulk scrape credits, crypto checkout + signup).

Exposes the crypto monetization surface on Pry's own x402 self-facilitation
rail (USDC). No email, no third-party processor, no KYC:

- ``POST /v1/billing/packs``            — list the credit-pack catalog
- ``POST /v1/billing/purchase``         — create an x402 PaymentRequired manifest
- ``POST /v1/billing/purchase/{id}/confirm`` — verify + credit balance (mint key on first purchase)
- ``POST /v1/billing/signup``           — issue a key + starter credits (no email)
- ``GET  /v1/billing/balance``          — read an account's prepaid balance

Wallet fail-closed rule: ``POST /v1/billing/purchase`` NEVER emits a placeholder
payTo. If the operator has not configured a real receiving wallet for the
resolved network, the route returns 503 with a clear message instead of
minting a fake manifest.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel, Field

from pry.commerce.billing import (
    PackNotFound,
    PackWalletUnconfigured,
    Underpayment,
    confirm_pack_purchase_async,
    create_pack_invoice,
    list_packs,
    signup_crypto,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["billing"])


class PurchaseRequest(BaseModel):
    """Initiate a crypto purchase of a bulk scrape-credit pack."""

    pack_id: str = Field(..., description="Credit-pack id (starter / growth / bulk)")
    user_id: str = Field(
        "", description="Optional account to credit (defaults to key owner / primary)"
    )
    api_key: str = Field("", description="Optional existing API key whose owner is credited")
    network: str = Field(
        "", description="CAIP-2 or legacy x402 network (defaults to the configured default)"
    )
    asset: str = Field("", description="Asset to pay in (defaults to USDC)")


class ConfirmRequest(BaseModel):
    """Confirm an on-chain payment for a pack purchase."""

    tx_hash: str = Field(..., description="On-chain transaction hash / signature")
    network: str = Field("", description="Network the payment was made on")
    asset: str = Field("", description="Asset paid")
    user_id: str = Field(
        "", description="Optional account to credit (defaults to key owner / primary)"
    )
    api_key: str = Field("", description="Optional existing API key whose owner is credited")
    authorization: dict[str, Any] | None = Field(
        None, description="Optional EIP-3009 authorization object"
    )


class SignupRequest(BaseModel):
    """Crypto signup — issue a key + starter credits (no email)."""

    user_id: str = Field("", description="Optional account id (defaults to implicit primary)")
    api_key: str = Field("", description="Optional existing active key to return as-is")


class BalanceRequest(BaseModel):
    """Read an account balance by key or user id (used by the ``pry_balance`` MCP tool)."""

    api_key: str = Field("", description="API key whose owner's balance to read")
    user_id: str = Field("", description="Explicit account id (takes precedence over api_key)")


@router.post(
    "/v1/billing/packs",
    summary="List bulk scrape-credit packs",
    description="Returns the server-authoritative credit-pack catalog with USD and atomic-unit prices.",
)
async def billing_packs() -> dict[str, Any]:
    """List the available bulk scrape-credit packs."""
    return {"success": True, "data": {"packs": list_packs()}}


@router.post(
    "/v1/billing/purchase",
    status_code=200,
    summary="Initiate a crypto-pack purchase (x402 PaymentRequired manifest)",
    description=(
        "Returns a spec-compliant x402 PaymentRequired manifest with the real configured "
        "receiving wallet as payToAddress. The client pays USDC (or the quoted asset) "
        "on-chain, then calls POST /v1/billing/purchase/{invoice_id}/confirm to credit the "
        "balance. Fails closed (503) if no real receiving wallet is configured."
    ),
)
async def billing_purchase(payload: PurchaseRequest) -> dict[str, Any]:
    """Create an x402 manifest for buying a scrape-credit pack."""
    try:
        invoice = create_pack_invoice(
            payload.pack_id,
            user_id=payload.user_id,
            api_key=payload.api_key,
            network=payload.network,
            asset=payload.asset,
        )
    except PackNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PackWalletUnconfigured as exc:
        logger.error("pack_purchase_wallet_unconfigured", extra={"pack_id": payload.pack_id})
        raise HTTPException(
            status_code=503,
            detail=str(exc),
        ) from exc
    return {
        "success": True,
        "data": {
            "status_code": 402,
            "payment_required": invoice["payment_required"],
            "invoice_id": invoice["invoice_id"],
            "pack_id": invoice["pack_id"],
            "amount_usd": invoice["amount_usd"],
            "amount_atomic": invoice["amount_atomic"],
            "credits": invoice["credits"],
            "chain": invoice["chain"],
            "pay_to": invoice["pay_to"],
            "asset": invoice["asset"],
            "expires_at": invoice["expires_at"],
        },
    }


@router.post(
    "/v1/billing/purchase/{invoice_id}/confirm",
    summary="Verify a pack payment and credit the balance",
    description=(
        "Verifies the on-chain payment via the x402 self-facilitator. On success credits the "
        "pack's USD value to the account ledger and mints an API key on first purchase "
        "(crypto signup — no email). Under-payments / invalid transfers are rejected (never "
        "credited)."
    ),
)
async def billing_purchase_confirm(
    invoice_id: str,
    payload: ConfirmRequest = Body(...),
) -> dict[str, Any]:
    """Verify + settle a pack purchase, crediting the ledger and minting a key."""
    try:
        result = await confirm_pack_purchase_async(
            invoice_id,
            payload.tx_hash,
            network=payload.network,
            asset=payload.asset,
            user_id=payload.user_id,
            api_key=payload.api_key,
            mint_key=True,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Underpayment as exc:
        logger.warning("pack_underpayment_rejected", extra={"invoice_id": invoice_id})
        return {"success": False, "data": {"paid": False, "reason": exc.reason or str(exc)}}
    if not result["paid"]:
        return {"success": False, "data": result}
    return {"success": True, "data": result}


@router.post(
    "/v1/billing/signup",
    summary="Crypto signup — issue an API key + starter credits (no email)",
    description=(
        "Issues a Pry API key and grants starter scrape credits. No email, no KYC. "
        "Idempotent per account: an existing active key (or an already-consumed signup "
        "grant) is not duplicated."
    ),
)
async def billing_signup(payload: SignupRequest) -> dict[str, Any]:
    """Sign up in crypto: mint a key + starter credits with no email."""
    result = signup_crypto(user_id=payload.user_id, api_key=payload.api_key)
    return {"success": True, "data": result}


@router.post(
    "/v1/billing/balance",
    summary="Read an account's prepaid balance",
    description=(
        "Returns the prepaid USD balance + low-balance flag for an account, resolved from an "
        "API key or an explicit user id. Used by the ``pry_balance`` MCP tool so an agent can "
        "check its balance before buying a pack or spending credits."
    ),
)
async def billing_balance(payload: BalanceRequest) -> dict[str, Any]:
    """Read the prepaid balance for the account identified by key or user id."""
    from pry.api.api_keys_service import PRIMARY_USER_ID, authenticate
    from pry.commerce.billing_service import get_balance

    user_id = payload.user_id
    if not user_id and payload.api_key:
        record = authenticate(payload.api_key.strip())
        user_id = record["user_id"] if record else PRIMARY_USER_ID
    user_id = user_id or PRIMARY_USER_ID
    balance = get_balance(user_id)
    return {"success": True, "data": {"balance": balance}}
