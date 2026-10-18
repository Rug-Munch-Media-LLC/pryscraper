"""Pry — x402 router (thin routes over the payload/view builders).

POST/GET contracts are unchanged: same paths, tags, status codes and response
shapes. Shaping lives in ``x402_views``; the pay request model and pay/verify
helpers live in ``x402_payloads``.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Request

from pry.api.routers.commerce import x402_views
from pry.api.routers.commerce.x402_payloads import PayRequest  # noqa: TC001 — runtime for FastAPI
from pry.core.errors import InvalidRequestError

router = APIRouter(tags=["x402"])


@router.get("/v1/x402/health", tags=["x402"], summary="x402 readiness/health probe")
async def x402_health() -> dict[str, Any]:
    """Live x402 readiness probe (facilitator, oracle, networks, settlement)."""
    return await x402_views.health_payload()


@router.get("/v1/x402/pricing", tags=["x402"], summary="Get x402 pricing for all paid operations")
async def x402_pricing() -> dict[str, Any]:
    """Per-operation USD price, supported networks/assets and treasury wallets.

    Free endpoint; the listed operations are paid via ``POST /v1/x402/payment``.
    """
    return x402_views.pricing_payload()


@router.get(
    "/v1/x402/catalog",
    tags=["x402"],
    summary="Full x402 catalog: operations, engines and every Apify actor preset",
)
async def x402_catalog() -> dict[str, Any]:
    """Machine-readable catalog: operations, engine per actor preset, MCP tool."""
    return x402_views.catalog_payload()


@router.post("/v1/x402/payment", tags=["x402"], summary="Create a x402 payment request")
async def x402_payment_request(
    operation: str = Body(...),
    metadata: dict[str, Any] | None = Body(None),
) -> dict[str, Any]:
    """Create a x402 payment request for a paid operation."""
    from pry.payments.x402 import create_payment_request

    return {"success": True, "data": create_payment_request(operation, metadata)}


@router.post("/v1/x402/verify", tags=["x402"], summary="Verify a x402 payment was settled")
async def x402_verify_payment(
    payment_id: str = Body(...),
    tx_hash: str = Body(...),
    network: str = Body(""),
    asset: str = Body(""),
    amount_usd: float = Body(0.0),
) -> dict[str, Any]:
    """Verify a payment on-chain; the server price overrides a client amount."""
    return await x402_views.verify_payload(payment_id, tx_hash, network, asset, amount_usd)


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
    """Create a single x402 payment covering multiple operations."""
    from pry.payments.x402 import create_batch_payment

    operations = payload.get("operations", [])
    if not isinstance(operations, list):
        raise InvalidRequestError("operations must be a list")
    result = await create_batch_payment(operations)
    if "error" in result:
        return {"success": False, "error": result["error"]}
    return {"success": True, "data": result}


@router.post("/v1/x402/batch-verify", tags=["x402"], summary="Verify a batch x402 payment")
async def x402_batch_verify(
    request: Request,
    payload: dict[str, Any] = Body(...),
) -> dict[str, Any]:
    """Verify + finalize a batch; success requires per-item settlement receipts."""
    return await x402_views.batch_verify_payload(request, payload)


@router.post("/v1/x402/pay", tags=["x402"], summary="Process x402 payment and get access token")
async def x402_pay(request: Request, body: PayRequest) -> dict[str, Any]:
    """Verify then settle a payment; return an access token (payment_id)."""
    return await x402_views.pay_payload(request, body)


# Re-exported so `from pry.api.routers.commerce.x402 import ENGINE_TOOLS` keeps
# working. NOT a bound local: internal callers go through `x402_engines`.
from pry.api.routers.commerce.x402_engines import ENGINE_TOOLS  # noqa: E402,F401
