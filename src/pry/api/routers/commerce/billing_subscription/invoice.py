"""Subscription invoice creation and payment-confirmation routes."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

from typing import Any

from fastapi import Body, HTTPException

from pry.api.routers.commerce.billing_subscription.models import (  # noqa: TC001
    SubscriptionConfirmRequest,
    SubscriptionInvoiceRequest,
)
from pry.api.routers.commerce.billing_subscription.router import logger, router
from pry.api.routers.commerce.billing_subscription.state import _ACTIVATED
from pry.commerce.billing import (
    activate_subscription,
    create_subscription_invoice,
    settle_subscription_payment,
    submit_subscription_payment,
    verify_subscription_payment,
)
from pry.payments.x402 import wallet_configured


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
