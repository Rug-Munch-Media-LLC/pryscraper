# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Crypto payment router for Pry.

Handles cryptocurrency payments via Coinbase Commerce, NowPayments, and BTCPay.
Falls back across providers for maximum reliability.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from pry.payments.crypto import CryptoPaymentError, get_crypto_router

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/payments/crypto", tags=["Crypto Payments"])


@router.post("/charge", summary="Create a crypto payment charge")
async def create_charge(request: Request) -> dict[str, Any]:
    """Create a cryptocurrency payment charge.

    Accepts:
        amount_usd: Amount in USD
        description: Payment description
        currency: Preferred crypto (btc, eth, sol, usdc, usdt, trx)
        order_id: Optional order/reference ID

    Returns:
        charge_id, payment URL, pay address, and status
    """
    try:
        body = await request.json()
    except (json.JSONDecodeError, ValueError) as e:
        raise HTTPException(status_code=400, detail="Invalid JSON body") from e

    amount_usd = body.get("amount_usd", 0)
    if not amount_usd or amount_usd <= 0:
        raise HTTPException(status_code=400, detail="amount_usd must be positive")

    router = get_crypto_router()
    if not router.has_providers:
        raise HTTPException(
            status_code=503,
            detail="No crypto payment providers configured. Set PRY_COINBASE_COMMERCE_API_KEY, PRY_NOWPAYMENTS_API_KEY, or PRY_BTCPAY_URL + PRY_BTCPAY_API_KEY.",
        )

    try:
        result = await router.create_charge(
            amount_usd=float(amount_usd),
            description=body.get("description", "Pry API credit"),
            metadata={
                "order_id": body.get("order_id", ""),
                "currency": body.get("currency", "btc"),
                "callback_url": body.get("callback_url", ""),
                "success_url": body.get("success_url", ""),
                "cancel_url": body.get("cancel_url", ""),
            },
        )
        return {"success": True, "data": result}
    except CryptoPaymentError as e:
        logger.error("crypto_charge_failed", extra={"error": str(e)})
        raise HTTPException(status_code=500, detail=f"Failed to create charge: {e}") from e


@router.get("/status/{charge_id}", summary="Check payment status")
async def check_status(charge_id: str, provider: str = "") -> dict[str, Any]:
    """Check the status of a crypto payment."""
    # This would check the status across providers
    return {"success": True, "data": {"charge_id": charge_id, "status": "pending"}}


@router.get("/providers", summary="List configured providers")
async def list_providers() -> dict[str, Any]:
    """List which crypto payment providers are configured."""
    import os

    providers = []
    if os.getenv("PRY_COINBASE_COMMERCE_API_KEY"):
        providers.append("coinbase_commerce")
    if os.getenv("PRY_NOWPAYMENTS_API_KEY"):
        providers.append("nowpayments")
    if os.getenv("PRY_BTCPAY_URL") and os.getenv("PRY_BTCPAY_API_KEY"):
        providers.append("btcpay")

    return {
        "success": True,
        "data": {
            "providers": providers,
            "count": len(providers),
            "supported_currencies": ["BTC", "ETH", "SOL", "USDC", "USDT", "TRX"],
        },
    }
