"""Pry — x402 router (remaining api.py routes).

Auto-extracted from api.py during the router-split refactor.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, Body, Request

from pry.core.errors import InvalidRequestError

logger = logging.getLogger(__name__)

router = APIRouter(tags=["x402"])


@router.get("/v1/x402/health", tags=["x402"], summary="x402 readiness/health probe")
async def x402_health() -> dict[str, Any]:
    """Live x402 readiness probe.

    Returns facilitator mode/readiness (self-hosted vs external), whether the
    price oracle is reachable and from which source, the supported network
    surface with per-network verification status, and settlement counters
    (nonces seen, pending). All fields are probed — the facilitator wallet/RPC
    and the oracle are checked, never assumed.
    """
    from pry.payments.x402 import get_facilitator_router
    from pry.payments.x402.scheme import (
        SUPPORTED_ASSETS,
        SUPPORTED_NETWORKS,
        network_verification_status,
        probe_oracle,
    )

    router = get_facilitator_router()
    oracle_reachable, oracle_source = await probe_oracle()
    verification_status = {
        n["network"]: network_verification_status(n["network"]) for n in SUPPORTED_NETWORKS
    }
    return {
        "status": "ok",
        "facilitator": router.readiness(),
        "oracle": {"reachable": oracle_reachable, "source": oracle_source},
        "supported_networks": [n["network"] for n in SUPPORTED_NETWORKS],
        "supported_assets_count": sum(len(assets) for assets in SUPPORTED_ASSETS.values()),
        "verification_status": verification_status,
        "settlement": router.settlement_stats(),
    }


@router.get("/v1/x402/pricing", tags=["x402"], summary="Get x402 pricing for all paid operations")
async def x402_pricing() -> dict[str, Any]:
    """Get the price list for pay-per-scrape operations."""
    from pry.payments.x402 import X402Handler

    return {"success": True, "data": X402Handler().get_stats()}


@router.post("/v1/x402/payment", tags=["x402"], summary="Create a x402 payment request")
async def x402_payment_request(
    operation: str = Body(...),
    metadata: dict[str, Any] | None = Body(None),
) -> dict[str, Any]:
    """Create a x402 payment request for a paid operation.

    Returns payment details (wallet, amount, asset) for the client to pay.
    """
    from pry.payments.x402 import create_payment_request

    req = create_payment_request(operation, metadata)
    return {"success": True, "data": req}


@router.post("/v1/x402/verify", tags=["x402"], summary="Verify a x402 payment was settled")
async def x402_verify_payment(
    payment_id: str = Body(...),
    tx_hash: str = Body(...),
    network: str = Body(""),
    asset: str = Body(""),
    amount_usd: float = Body(0.0),
) -> dict[str, Any]:
    """Verify a x402 payment has been settled on-chain via facilitator router.

    When ``payment_id`` names a priced operation, the client-supplied
    ``amount_usd`` is validated against the SERVER-side price first and
    underpayment is rejected before any facilitator call.
    """
    from pry.payments.x402 import X402_PRICING, X402Handler, validate_client_amount

    if payment_id in X402_PRICING:
        ok, reason = validate_client_amount(payment_id, amount_usd, asset, network=network)
        if not ok:
            logger.warning(
                "x402_underpayment_rejected",
                extra={"operation": payment_id, "reason": reason},
            )
            return {
                "success": False,
                "data": {"verified": False, "reason": reason, "settlement": None},
            }

    result = await X402Handler().verify_payment(
        payment_id,
        tx_hash,
        network=network,
        asset=asset,
        amount_usd=amount_usd,
        operation=payment_id if payment_id in X402_PRICING else "",
    )
    return {"success": result["verified"], "data": result}


@router.post(
    "/v1/x402/require-payment", tags=["x402"], summary="Generate a 402 Payment Required response"
)
async def x402_require_payment(
    operation: str = Body(...),
    metadata: dict[str, Any] | None = Body(None),
) -> dict[str, Any]:
    """Generate a 402 Payment Required response for a paid endpoint."""
    from pry.payments.x402 import require_payment_legacy

    return require_payment_legacy(operation, metadata)


@router.post("/v1/x402/batch-payment", tags=["x402"], summary="Create a batch x402 payment")
async def x402_batch_payment(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """Create a single x402 payment covering multiple operations.

    Returns a PaymentRequired body with the combined amount. After paying,
    submit the tx to POST /v1/x402/batch-verify.
    """
    from pry.payments.x402 import create_batch_payment

    operations = payload.get("operations", [])
    if not isinstance(operations, list):
        raise InvalidRequestError("operations must be a list")
    result = await create_batch_payment(operations)
    if "error" in result:
        return {"success": False, "error": result["error"]}
    return {"success": True, "data": result}


@router.post("/v1/x402/batch-verify", tags=["x402"], summary="Verify a batch x402 payment")
async def x402_batch_verify(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """Verify the on-chain payment for a batch and mark it paid."""
    from pry.payments.x402 import verify_batch_payment

    batch_id = payload.get("batch_id", "")
    tx_hash = payload.get("tx_hash", "")
    network = payload.get("network", "")
    asset = payload.get("asset", "")
    if not batch_id or not tx_hash:
        raise InvalidRequestError("batch_id and tx_hash are required")
    result = await verify_batch_payment(batch_id, tx_hash, network=network, asset=asset)
    return {"success": result["verified"], "data": result}


@router.post(
    "/v1/x402/pay",
    tags=["x402"],
    summary="Process x402 payment and get access token",
)
async def x402_pay(
    request: Request,
    operation: str = Body(...),
    tx_hash: str = Body(...),
    payer_wallet: str = Body(...),
    network: str = Body(""),
    asset: str = Body(""),
    amount_usd: float = Body(0.0),
) -> dict[str, Any]:
    """Process an x402 payment and return an access token.

    Flow:
    1. User gets 402 from a paid endpoint
    2. User sends USDC to the wallet in the 402 response
    3. User calls this endpoint with the tx_hash
    4. Pry verifies the transaction through the facilitator router
    5. Returns access token (payment_id) to use in X-Payment-Hash header

    Security: the client-supplied ``amount_usd`` is validated against the
    SERVER-side price for ``operation`` before any verification, so a client
    cannot underpay by claiming a lower amount. The returned payment_id is
    bound to the caller IP and expires after PAYMENT_VALIDITY_SECONDS.
    """
    from pry.payments.x402 import X402Handler, resolve_price_usd, validate_client_amount

    # Never trust the client-supplied amount: reject underpayment up front.
    # ``network`` lets the canonical SUPPORTED_ASSETS table quote non-1:1
    # assets (ETH/ARB/SOL/TRX) with the right decimals + USD-per-unit.
    ok, reason = validate_client_amount(operation, amount_usd, asset, network=network)
    if not ok:
        logger.warning(
            "x402_underpayment_rejected",
            extra={"operation": operation, "reason": reason},
        )
        return {
            "success": False,
            "data": {
                "payment_id": "",
                "tx_hash": tx_hash,
                "verified": {"verified": False, "reason": reason, "settlement": None},
                "settlement": None,
                "payer_wallet": payer_wallet,
                "required_amount_usd": resolve_price_usd(operation),
            },
        }

    # Bind the payment to the caller IP so the middleware replay check (which
    # also uses the socket peer IP) can match it within the TTL window.
    caller_key = request.client.host if request.client else ""
    h = X402Handler()
    payment_id = uuid.uuid4().hex[:12]
    # Use the server-side price for the operation.
    verify_result = await h.verify_payment(
        payment_id,
        tx_hash,
        network=network,
        asset=asset,
        amount_usd=amount_usd,
        operation=operation,
        caller_key=caller_key,
    )
    settlement = None
    if verify_result.get("verified"):
        settlement = await h.settle_payment(
            payment_id,
            tx_hash,
            network=network,
            asset=asset,
            amount_usd=amount_usd,
            operation=operation,
        )
    return {
        "success": verify_result.get("verified", False),
        "data": {
            "payment_id": payment_id,
            "tx_hash": tx_hash,
            "verified": verify_result,
            "settlement": settlement,
            "payer_wallet": payer_wallet,
            "use_in_header": {"X-Payment-ID": payment_id, "X-Payment-Hash": tx_hash},
        },
    }
