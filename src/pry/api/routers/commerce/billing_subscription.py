"""Pry — hosted subscription billing router (monthly Pro/Team tiers, x402 checkout).

Exposes the hosted-pry subscription monetization surface over HTTP. The
library functions in :mod:`pry.commerce.billing.subscription` (invoice
creation / verification / activation) previously had NO route — this router
wires them up, modeled on the bulk scrape-credit packs router
(:mod:`pry.api.routers.commerce.billing_packs`):

- ``POST /v1/billing/subscription/invoice``            — create a subscription
  invoice (tier + api_key + months) and return the x402 payment manifest data
  (chain, atomic amount, asset, expiry) quoting the configured treasury payTo.
- ``POST /v1/billing/subscription/invoice/{id}/confirm`` — verify the reported
  on-chain payment via the self-facilitator and, only when verified, activate
  the subscription (credit the account with *months* of *tier*).

Wallet fail-closed rule (mirrors the packs router): the create route NEVER
emits a placeholder payTo. ``create_subscription_invoice`` resolves the
receiving wallet family-aware and can return an empty address when the
operator has not configured a real wallet — the route returns 503 with a
clear message instead of minting a manifest with an empty payToAddress.

Idempotency: a confirm that already activated an invoice (in this process)
returns the stored activation without re-activating — the subscription
library's ``activate_subscription`` extends from the current expiry on a
same-tier renewal, so double-activating the same invoice would double-credit.

NOTE [REVIEW]: ``verify_subscription_payment`` is a SYNC function that runs
the async self-facilitator via ``asyncio.run`` — this confirm route is a sync
``def`` (FastAPI runs it in a threadpool with no running event loop), so the
library contract is respected. The library does not (yet) export an async
verify variant.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import logging
import math
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel, Field

from pry.commerce.billing import (
    activate_subscription,
    create_subscription_invoice,
    get_tier,
    settle_subscription_payment,
    submit_subscription_payment,
    subscription_status,
    verify_subscription_payment,
)
from pry.payments.x402 import wallet_configured

logger = logging.getLogger(__name__)

router = APIRouter(tags=["billing"])

#: Invoice ids already activated in this process (idempotency guard). Mirrors
#: the in-memory contract of the subscription library's own registries.
_ACTIVATED: dict[str, dict[str, Any]] = {}

#: Auto-renewal flags per api_key (default True). Mirrors the in-memory
#: contract of the subscription library's own registries — cancel flips the
#: flag; access is kept until the paid period ends.
_AUTO_RENEW: dict[str, bool] = {}

#: Pending tier changes per api_key (downgrades applied at next renewal).
_PENDING_TIER: dict[str, str] = {}


class SubscriptionInvoiceRequest(BaseModel):
    """Create a hosted-pry subscription invoice for a monthly tier."""

    tier: str = Field(..., description="Tier id (pro / team)")
    api_key: str = Field(..., description="API key whose account is subscribed")
    months: int = Field(1, description="Number of months to subscribe (>= 1)")


class SubscriptionConfirmRequest(BaseModel):
    """Report the on-chain payment for a subscription invoice and verify it."""

    tx_hash: str = Field(..., description="On-chain transaction hash / signature")
    network: str = Field("", description="Network the payment was made on")
    asset: str = Field("", description="Asset paid")
    authorization: dict[str, Any] | None = Field(
        None, description="Optional EIP-3009 authorization object"
    )


@router.post(
    "/v1/billing/subscription/invoice",
    status_code=200,
    summary="Create a hosted subscription invoice (x402 PaymentRequired manifest)",
    description=(
        "Creates a subscription invoice for *months* of *tier* and returns the x402 payment "
        "manifest data quoting the configured treasury payTo. The client pays on-chain, then "
        "calls POST /v1/billing/subscription/invoice/{invoice_id}/confirm to activate the "
        "subscription once the payment verifies. Fails closed (503) if no real receiving "
        "wallet is configured."
    ),
)
def billing_subscription_invoice(payload: SubscriptionInvoiceRequest) -> dict[str, Any]:
    """Create an x402 manifest for a hosted-pry subscription."""
    try:
        invoice = create_subscription_invoice(payload.tier, payload.api_key, payload.months)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    pay_to = invoice.get("payment_address") or ""
    if not wallet_configured(pay_to):
        logger.error("subscription_invoice_wallet_unconfigured", extra={"tier": payload.tier})
        raise HTTPException(
            status_code=503,
            detail="no real receiving wallet configured — refusing to emit a placeholder payTo",
        )

    return {
        "success": True,
        "data": {
            "status_code": 402,
            "invoice_id": invoice["invoice_id"],
            "tier": invoice["tier"],
            "months": payload.months,
            "amount_usd": invoice["amount_usd"],
            "amount_atomic": invoice["amount_asset"],
            "chain": invoice["chain"],
            "pay_to": pay_to,
            "asset": invoice["asset"],
            "expires_at": invoice["expires_at"],
            "payment_method": invoice["payment_method"],
        },
    }


@router.post(
    "/v1/billing/subscription/invoice/{invoice_id}/confirm",
    summary="Verify a subscription payment and activate the subscription",
    description=(
        "Verifies the on-chain payment via the x402 self-facilitator. Only on a successful "
        "verify does the route activate the subscription (credit the account with the paid "
        "months of tier). Unverified / expired payments are never activated. Re-confirming "
        "an already-activated invoice is idempotent (returns the stored activation)."
    ),
)
def billing_subscription_confirm(
    invoice_id: str,
    payload: SubscriptionConfirmRequest = Body(...),
) -> dict[str, Any]:
    """Verify + activate a subscription, crediting the account only on success."""
    try:
        # Returns the full invoice record (tier / api_key / months) so activation
        # targets exactly what was paid for — the client never supplies the tier.
        record = submit_subscription_payment(
            invoice_id,
            payload.tx_hash,
            network=payload.network,
            asset=payload.asset,
            authorization=payload.authorization,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    result = verify_subscription_payment(invoice_id)
    if not result["paid"]:
        logger.warning("subscription_payment_not_verified", extra={"invoice_id": invoice_id})
        return {
            "success": False,
            "data": {
                "paid": False,
                "reason": result.get("reason") or "not verified",
            },
        }

    # Idempotency: never re-activate (renewal rollover would double-credit).
    if invoice_id in _ACTIVATED:
        return {
            "success": True,
            "data": {
                "paid": True,
                "idempotent": True,
                "tx_hash": result.get("tx_hash"),
                "confirmed_at": result.get("confirmed_at"),
                "subscription": _ACTIVATED[invoice_id],
            },
        }

    # Settlement gate: verify only ecrecovers the EIP-3009 authorization —
    # funds must actually move on-chain before the subscription activates.
    settlement = settle_subscription_payment(invoice_id)
    if not settlement["settled"]:
        logger.warning("subscription_settlement_failed", extra={"invoice_id": invoice_id})
        return {
            "success": False,
            "data": {
                "paid": False,
                "reason": settlement.get("reason") or "settlement failed",
            },
        }

    activation = activate_subscription(record["api_key"], record["tier"], int(record["months"]))
    _ACTIVATED[invoice_id] = activation
    return {
        "success": True,
        "data": {
            "paid": True,
            "idempotent": False,
            "tx_hash": result.get("tx_hash"),
            "confirmed_at": result.get("confirmed_at"),
            "api_key": record["api_key"],
            "tier": record["tier"],
            "months": record["months"],
            "subscription": activation,
        },
    }


class SubscriptionCancelRequest(BaseModel):
    """Cancel a subscription (stops auto-renewal, keeps access until period end)."""

    api_key: str = Field(..., description="API key whose subscription is cancelled")


class SubscriptionRenewRequest(BaseModel):
    """Create a renewal invoice for the next subscription period."""

    api_key: str = Field(..., description="API key whose subscription is renewed")
    months: int = Field(1, description="Number of months to renew (>= 1)")


class SubscriptionChangeTierRequest(BaseModel):
    """Change the subscription tier (upgrades prorate; downgrades defer)."""

    api_key: str = Field(..., description="API key whose subscription changes tier")
    new_tier: str = Field(..., description="Target tier id (pro / team)")


@router.get(
    "/v1/billing/subscription/status",
    summary="Get the current subscription status for an API key",
    description=(
        "Reports the subscription tier, lifecycle status (active / cancelled / expired), "
        "current period end, months remaining, and auto-renewal flag. Unknown keys "
        "report the FREE tier with no expiry."
    ),
)
def billing_subscription_status(api_key: str) -> dict[str, Any]:
    """Report subscription state for *api_key*."""
    state = subscription_status(api_key)
    expires_at = state.get("expires_at")
    active = bool(state.get("active"))
    auto_renew = _AUTO_RENEW.get(api_key, True)

    if not active:
        status = "expired"
    elif not auto_renew:
        status = "cancelled"
    else:
        status = "active"

    months_remaining = 0
    if expires_at and active:
        try:
            remaining = datetime.fromisoformat(str(expires_at)) - datetime.now(UTC)
            months_remaining = max(0, math.ceil(remaining.total_seconds() / (30 * 24 * 3600)))
        except ValueError:
            months_remaining = 0

    return {
        "success": True,
        "data": {
            "tier": state.get("tier", "free"),
            "status": status,
            "current_period_end": expires_at,
            "months_remaining": months_remaining,
            "auto_renew": auto_renew,
        },
    }


@router.post(
    "/v1/billing/subscription/cancel",
    summary="Cancel a subscription (stops auto-renewal, keeps access until period end)",
    description=(
        "Flips the auto-renewal flag off for the subscription. Access to the paid tier "
        "is preserved until the current period ends; no refund is issued."
    ),
)
def billing_subscription_cancel(payload: SubscriptionCancelRequest) -> dict[str, Any]:
    """Cancel auto-renewal for *api_key*, keeping access until period end."""
    state = subscription_status(payload.api_key)
    if not state.get("active"):
        raise HTTPException(status_code=404, detail="no active subscription for this api_key")

    _AUTO_RENEW[payload.api_key] = False
    access_until = state.get("expires_at")
    logger.info("subscription_cancelled", extra={"api_key": payload.api_key})
    return {
        "success": True,
        "data": {
            "success": True,
            "message": "auto-renewal stopped — access continues until the period ends",
            "access_until": access_until,
        },
    }


@router.post(
    "/v1/billing/subscription/renew",
    summary="Create a renewal invoice for the next subscription period",
    description=(
        "Creates a new x402 invoice for the next period of the CURRENT tier (same "
        "response shape as POST /v1/billing/subscription/invoice). The client pays "
        "on-chain, then confirms via the invoice confirm route to extend the expiry."
    ),
)
def billing_subscription_renew(payload: SubscriptionRenewRequest) -> dict[str, Any]:
    """Create a renewal invoice for the current tier of *api_key*."""
    state = subscription_status(payload.api_key)
    tier = str(state.get("tier", "free"))
    resolved = get_tier(tier)
    if resolved.price_usd_monthly is None:
        raise HTTPException(
            status_code=400,
            detail=f"tier {tier!r} has no fixed monthly price — cannot renew",
        )

    try:
        invoice = create_subscription_invoice(tier, payload.api_key, payload.months)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    pay_to = invoice.get("payment_address") or ""
    if not wallet_configured(pay_to):
        logger.error("subscription_renew_wallet_unconfigured", extra={"tier": tier})
        raise HTTPException(
            status_code=503,
            detail="no real receiving wallet configured — refusing to emit a placeholder payTo",
        )

    return {
        "success": True,
        "data": {
            "status_code": 402,
            "invoice_id": invoice["invoice_id"],
            "tier": invoice["tier"],
            "months": payload.months,
            "amount_usd": invoice["amount_usd"],
            "amount_atomic": invoice["amount_asset"],
            "chain": invoice["chain"],
            "pay_to": pay_to,
            "asset": invoice["asset"],
            "expires_at": invoice["expires_at"],
            "payment_method": invoice["payment_method"],
        },
    }


@router.post(
    "/v1/billing/subscription/change-tier",
    summary="Change the subscription tier",
    description=(
        "Upgrades take effect immediately: the remaining paid time is converted to "
        "months of the new tier and the price difference is prorated (positive "
        "``price_adjustment`` = additional charge due). Downgrades are deferred: they "
        "apply at the next renewal with no immediate charge."
    ),
)
def billing_subscription_change_tier(payload: SubscriptionChangeTierRequest) -> dict[str, Any]:
    """Change the subscription tier for *api_key*."""
    state = subscription_status(payload.api_key)
    if not state.get("active"):
        raise HTTPException(status_code=404, detail="no active subscription for this api_key")

    current_tier = str(state.get("tier", "free"))
    current = get_tier(current_tier)
    new = get_tier(payload.new_tier)
    if new.price_usd_monthly is None:
        raise HTTPException(
            status_code=400,
            detail=f"tier {new.name!r} has no fixed monthly price — cannot change to it",
        )
    if new.name == current.name:
        raise HTTPException(status_code=400, detail="already subscribed to this tier")

    expires_at = state.get("expires_at")
    months_remaining = 1
    if expires_at:
        try:
            remaining = datetime.fromisoformat(str(expires_at)) - datetime.now(UTC)
            months_remaining = max(1, math.ceil(remaining.total_seconds() / (30 * 24 * 3600)))
        except ValueError:
            months_remaining = 1

    if (new.price_usd_monthly or 0.0) > (current.price_usd_monthly or 0.0):
        # Upgrade: prorate the difference over the remaining period and switch
        # immediately (activation restarts the expiry from now on tier change,
        # so we credit the converted remaining months of the new tier).
        price_adjustment = round(
            ((new.price_usd_monthly or 0.0) - (current.price_usd_monthly or 0.0))
            * months_remaining,
            2,
        )
        activation = activate_subscription(payload.api_key, new.name, months_remaining)
        _PENDING_TIER.pop(payload.api_key, None)
        logger.info(
            "subscription_tier_upgraded",
            extra={"api_key": payload.api_key, "tier": new.name},
        )
        return {
            "success": True,
            "data": {
                "success": True,
                "message": (
                    f"upgraded to {new.name} — prorated charge of "
                    f"${price_adjustment:.2f} due for {months_remaining} month(s)"
                ),
                "new_tier": new.name,
                "price_adjustment": price_adjustment,
                "expires_at": activation["expires_at"],
            },
        }

    # Downgrade: defer to next renewal — no immediate charge, no immediate switch.
    _PENDING_TIER[payload.api_key] = new.name
    logger.info(
        "subscription_tier_downgrade_scheduled",
        extra={"api_key": payload.api_key, "tier": new.name},
    )
    return {
        "success": True,
        "data": {
            "success": True,
            "message": (f"downgrade to {new.name} scheduled — applies at the next renewal"),
            "new_tier": new.name,
            "price_adjustment": 0.0,
        },
    }
