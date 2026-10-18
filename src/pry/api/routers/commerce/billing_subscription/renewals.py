"""Subscription renewal and tier-change routes."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException
from fastapi.responses import JSONResponse

from pry.api.routers.commerce.billing_subscription.models import (  # noqa: TC001
    SubscriptionChangeTierRequest,
    SubscriptionRenewRequest,
)
from pry.api.routers.commerce.billing_subscription.router import logger, router
from pry.api.routers.commerce.billing_subscription.state import (
    _PENDING_TIER,
    _TIER_CHANGE_INVOICES,
)
from pry.commerce.billing import (
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
        "Upgrades do NOT take effect until paid: the remaining paid time is converted "
        "to months of the new tier and the price difference is prorated into an x402 "
        "invoice. The route returns HTTP 402 with the payment fields and leaves the "
        "current tier active; repeat calls reuse the same pending invoice. Downgrades "
        "are deferred: they apply at the next renewal with no immediate charge."
    ),
)
def billing_subscription_change_tier(payload: SubscriptionChangeTierRequest) -> dict[str, Any]:
    """Change the subscription tier for *api_key*."""
    state = subscription_status(payload.api_key)
    if not state.get("active"):
        raise HTTPException(status_code=404, detail="no active subscription for this api_key")

    current = get_tier(str(state.get("tier", "free")))
    new = get_tier(payload.new_tier)
    if new.price_usd_monthly is None:
        raise HTTPException(
            status_code=400,
            detail=f"tier {new.name!r} has no fixed monthly price — cannot change to it",
        )
    if new.name == current.name:
        raise HTTPException(status_code=400, detail="already subscribed to this tier")

    if (new.price_usd_monthly or 0.0) > (current.price_usd_monthly or 0.0):
        return _require_tier_change_payment(payload.api_key, current, new, state)

    # Downgrade: defer to next renewal — no immediate charge, no immediate switch.
    _PENDING_TIER[payload.api_key] = new.name
    _TIER_CHANGE_INVOICES.pop(payload.api_key, None)
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


def _months_remaining(expires_at: Any) -> int:
    """Whole calendar months left in the paid period (minimum 1).

    Calendar arithmetic, not ``ceil(days / 30)``: a fresh 1-month term is
    31 days (Oct 18 -> Nov 18), which the day-based formula rounded up to 2
    and overcharged the prorated upgrade by a whole month.
    """
    if not expires_at:
        return 1
    try:
        expires = datetime.fromisoformat(str(expires_at))
    except ValueError:
        logger.warning("renewals_exception_handler", exc_info=True)
        return 1
    now = datetime.now(UTC)
    whole = (expires.year - now.year) * 12 + (expires.month - now.month)
    if expires.day > now.day:
        whole += 1
    return max(1, whole)


def _cached_tier_invoice(api_key: str, new_tier: str) -> dict[str, Any] | None:
    """Return the still-valid pending invoice detail for this upgrade."""
    cached = _TIER_CHANGE_INVOICES.get(api_key)
    if not cached or cached.get("new_tier") != new_tier:
        return None
    detail = cached.get("detail")
    try:
        expires = datetime.fromisoformat(str(detail["expires_at"]))
    except (KeyError, TypeError, ValueError):
        _TIER_CHANGE_INVOICES.pop(api_key, None)
        return None
    if expires <= datetime.now(UTC):
        _TIER_CHANGE_INVOICES.pop(api_key, None)
        return None
    return dict(detail)


def _require_tier_change_payment(
    api_key: str, current: Any, new: Any, state: dict[str, Any]
) -> JSONResponse:
    """Raise HTTP 402 with an invoice for the prorated upgrade difference.

    No activation happens here: the current tier stays active until the
    invoice is confirmed and paid. Repeated calls reuse the pending invoice.
    """
    cached = _cached_tier_invoice(api_key, new.name)
    if cached is not None:
        # JSONResponse, not HTTPException: the global error handler flattens a
        # dict ``detail`` to "Bad Request", which would drop the invoice.
        return JSONResponse(status_code=402, content=cached)

    months = _months_remaining(state.get("expires_at"))
    price_adjustment = round(
        ((new.price_usd_monthly or 0.0) - (current.price_usd_monthly or 0.0)) * months,
        2,
    )
    if price_adjustment <= 0:
        raise HTTPException(status_code=400, detail="prorated difference is not payable")

    try:
        invoice = create_subscription_invoice(
            new.name, api_key, months, amount_override_usd=price_adjustment
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    pay_to = invoice.get("payment_address") or ""
    if not wallet_configured(pay_to):
        logger.error("subscription_change_tier_wallet_unconfigured", extra={"tier": new.name})
        raise HTTPException(
            status_code=503,
            detail="no real receiving wallet configured — refusing to emit a placeholder payTo",
        )

    detail = {
        "success": False,
        "invoice_required": True,
        "invoice_id": invoice["invoice_id"],
        "amount": invoice["amount_usd"],
        "amount_usd": invoice["amount_usd"],
        "asset": invoice["asset"],
        "chain": invoice["chain"],
        "pay_to": pay_to,
        "tier": new.name,
        "months": months,
        "expires_at": invoice["expires_at"],
        "payment_method": invoice["payment_method"],
        "message": (
            f"upgrade to {new.name} requires a prorated payment of "
            f"${price_adjustment:.2f}; current tier stays active until paid"
        ),
    }
    _TIER_CHANGE_INVOICES[api_key] = {"new_tier": new.name, "detail": detail}
    logger.info(
        "subscription_tier_upgrade_invoice_required",
        extra={"api_key": api_key, "tier": new.name, "invoice_id": invoice["invoice_id"]},
    )
    return JSONResponse(status_code=402, content=detail)
