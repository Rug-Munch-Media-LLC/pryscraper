"""Pry — x402 route payload builders (pay / verify-and-settle).

Request models and the response-shaping helpers that the thin router delegates
to. Kept separate from ``x402_views`` so each module stays single-purpose.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel

logger = logging.getLogger(__name__)


class PayRequest(BaseModel):
    """``POST /v1/x402/pay`` body (same flat JSON shape as the old Body params)."""

    operation: str
    tx_hash: str
    payer_wallet: str
    network: str = ""
    asset: str = ""
    amount_usd: float = 0.0


def build_pay_payload(body: PayRequest, caller_key: str) -> dict[str, Any]:
    """Normalise the route body into the internal payment dict."""
    return {
        "payment_id": _new_payment_id(),
        "tx_hash": body.tx_hash,
        "network": body.network,
        "asset": body.asset,
        "amount_usd": body.amount_usd,
        "operation": body.operation,
        "payer_wallet": body.payer_wallet,
        # Bind to the caller IP so the middleware replay check matches it.
        "caller_key": caller_key,
    }


def _new_payment_id() -> str:
    import uuid

    return uuid.uuid4().hex[:12]


def rejected_payment(payload: dict[str, Any], reason: str) -> dict[str, Any]:
    """Underpayment response body — same shape as a failed verification."""
    from pry.payments.x402 import resolve_price_usd

    return {
        "success": False,
        "data": {
            "payment_id": "",
            "tx_hash": payload["tx_hash"],
            "settled": False,
            "verified": {"verified": False, "reason": reason, "settlement": None},
            "settlement": None,
            "payer_wallet": payload["payer_wallet"],
            "required_amount_usd": resolve_price_usd(payload["operation"]),
        },
    }


async def verify_and_settle(payload: dict[str, Any]) -> tuple[dict[str, Any], Any]:
    """Verify then settle one payment; settlement proves access, verification does not."""
    from pry.payments.x402 import X402Handler

    handler = X402Handler()
    common = {
        "network": payload["network"],
        "asset": payload["asset"],
        "amount_usd": payload["amount_usd"],
        "operation": payload["operation"],
    }
    verify_result = await handler.verify_payment(
        payload["payment_id"], payload["tx_hash"], caller_key=payload["caller_key"], **common
    )
    if not verify_result.get("verified"):
        return verify_result, None
    settlement = await handler.settle_payment(payload["payment_id"], payload["tx_hash"], **common)
    return verify_result, settlement


def paid_payload(
    payload: dict[str, Any], verify_result: dict[str, Any], settlement: Any
) -> dict[str, Any]:
    """Success/failure body for ``/v1/x402/pay`` (payment_id only when settled)."""
    settled = bool(settlement and settlement.get("success") is True)
    success = bool(verify_result.get("verified")) and settled
    payment_id = payload["payment_id"]
    return {
        "success": success,
        "data": {
            "payment_id": payment_id if settled else "",
            "tx_hash": payload["tx_hash"],
            "settled": settled,
            "verified": verify_result,
            "settlement": settlement,
            "payer_wallet": payload["payer_wallet"],
            "use_in_header": (
                {"X-Payment-ID": payment_id, "X-Payment-Hash": payload["tx_hash"]}
                if settled
                else {}
            ),
        },
    }
