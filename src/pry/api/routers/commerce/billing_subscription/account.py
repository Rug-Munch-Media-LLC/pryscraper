"""Subscription status and cancellation routes."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException

from pry.api.routers.commerce.billing_subscription.models import (  # noqa: TC001
    SubscriptionCancelRequest,
)
from pry.api.routers.commerce.billing_subscription.router import logger, router
from pry.api.routers.commerce.billing_subscription.state import _AUTO_RENEW
from pry.commerce.billing import subscription_status


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
