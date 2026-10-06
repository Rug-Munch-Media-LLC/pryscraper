"""Subscription renewal and tier-change routes."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException

from pry.api.routers.commerce.billing_subscription.models import (  # noqa: TC001
    SubscriptionChangeTierRequest,
    SubscriptionRenewRequest,
)
from pry.api.routers.commerce.billing_subscription.router import logger, router
from pry.api.routers.commerce.billing_subscription.state import (
    _PENDING_TIER,
)
from pry.commerce.billing import (
    activate_subscription,
    create_subscription_invoice,
    get_tier,
    subscription_status,
)
from pry.payments.x402 import wallet_configured


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
            logger.warning("renewals_exception_handler", exc_info=True)
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
