"""Pry — x402 response builders used by the thin commerce router.

Every builder keeps its ``pry.payments.x402`` imports inside the function so
attribute patches on the package keep resolving at request time (the router
relied on the same late binding).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from fastapi import Request

from pry.api.routers.commerce import x402_engines
from pry.api.routers.commerce.x402_payloads import (
    PayRequest,
    build_pay_payload,
    paid_payload,
    rejected_payment,
    verify_and_settle,
)
from pry.core.errors import InvalidRequestError

logger = logging.getLogger(__name__)


async def health_payload() -> dict[str, Any]:
    """Live readiness payload: facilitator, oracle, network surface, counters."""
    from pry.payments.x402 import get_facilitator_router
    from pry.payments.x402.scheme import (
        SUPPORTED_ASSETS,
        SUPPORTED_NETWORKS,
        network_verification_status,
        probe_oracle,
    )

    facilitator_router = get_facilitator_router()
    oracle_reachable, oracle_source = await probe_oracle()
    verification_status = {
        n["network"]: network_verification_status(n["network"]) for n in SUPPORTED_NETWORKS
    }
    return {
        "status": "ok",
        "facilitator": facilitator_router.readiness(),
        "oracle": {"reachable": oracle_reachable, "source": oracle_source},
        "supported_networks": [n["network"] for n in SUPPORTED_NETWORKS],
        "supported_assets_count": sum(len(assets) for assets in SUPPORTED_ASSETS.values()),
        "verification_status": verification_status,
        "settlement": facilitator_router.settlement_stats(),
    }


def pricing_payload() -> dict[str, Any]:
    """Price list plus the ACTUAL configured per-chain treasuries."""
    from pry.payments.x402 import X402Handler
    from pry.payments.x402.scheme import treasury_wallets

    stats = X402Handler().get_stats()
    stats["wallets"] = treasury_wallets()
    return {"success": True, "data": stats}


def catalog_payload() -> dict[str, Any]:
    """Operations + engine bindings + every Apify actor preset."""
    from pry.payments.x402 import X402Handler
    from pry.payments.x402_middleware import PAID_ENDPOINTS
    from pry.payments.x402_middleware.config import X402_PRICING

    try:
        actors = _catalog_actors()
    except Exception:
        # An empty ``actors`` list is indistinguishable from a factory that
        # genuinely ships no presets, so mark the section unavailable instead.
        logger.warning("x402_catalog_actor_presets_unavailable", exc_info=True)
        return {
            "success": False,
            "error": "actor presets unavailable",
            "data": x402_engines.catalog_data(
                X402_PRICING, PAID_ENDPOINTS, None, X402Handler().get_stats().get("settlement", {})
            ),
        }
    return {
        "success": True,
        "data": x402_engines.catalog_data(
            X402_PRICING, PAID_ENDPOINTS, actors, X402Handler().get_stats().get("settlement", {})
        ),
    }


def _catalog_actors() -> list[dict[str, Any]]:
    """Actor presets with their engine + MCP tool binding."""
    from actor_factory.presets import ALL_PRESETS

    return [
        {
            "actor": name,
            "title": spec.title,
            "icon": spec.icon,
            "engine": spec.processor or "scrape",
            "mcp_tool": x402_engines.ENGINE_TOOLS.get(spec.processor, "pry_scrape"),
            "category": str(getattr(spec.category, "value", spec.category)),
            "uses_browser": bool(spec.uses_browser),
        }
        for name, spec in sorted(ALL_PRESETS.items())
    ]


async def verify_payload(
    payment_id: str, tx_hash: str, network: str, asset: str, amount_usd: float
) -> dict[str, Any]:
    """Verify a single payment, using the SERVER price when the id is priced."""
    from pry.payments.x402 import X402_PRICING, X402Handler, resolve_price_usd

    server_amount = 0.0
    if payment_id in X402_PRICING:
        server_amount = resolve_price_usd(payment_id, network=network, asset=asset)
        if amount_usd > server_amount + 1e-9:
            logger.warning(
                "x402_client_overpayment_claim",
                extra={"operation": payment_id, "client": amount_usd, "server": server_amount},
            )
        amount_usd = server_amount
    result = await X402Handler().verify_payment(
        payment_id,
        tx_hash,
        network=network,
        asset=asset,
        amount_usd=amount_usd,
        operation=payment_id if payment_id in X402_PRICING else "",
    )
    return {"success": result["verified"], "data": result}


async def batch_verify_payload(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
    """Verify + finalize a batch; success requires SETTLEMENT, not verification."""
    from pry.payments.x402 import X402Handler, verify_batch_payment

    batch_id = payload.get("batch_id", "")
    tx_hash = payload.get("tx_hash", "")
    network = payload.get("network", "")
    asset = payload.get("asset", "")
    if not batch_id or not tx_hash:
        raise InvalidRequestError("batch_id and tx_hash are required")
    caller_key = request.client.host if request and request.client else ""
    result = await verify_batch_payment(
        batch_id, tx_hash, network=network, asset=asset, caller_key=caller_key
    )
    status = X402Handler().finalize_batch_settlement(
        batch_id, tx_hash=tx_hash, network=network, asset=asset
    )
    verified = bool(result.get("verified"))
    settled = bool(status.get("all_settled"))
    data = {
        **result,
        "success": verified and settled,
        "settled": settled,
        "settled_items": status.get("settled", []),
        "unsettled": status.get("unsettled", []),
        "receipts_written": status.get("written", 0),
    }
    return {"success": verified and settled, "data": data}


async def pay_payload(request: Request, body: PayRequest) -> dict[str, Any]:
    """Validate the server price, then verify+settle; return the access token."""
    from pry.payments.x402 import validate_client_amount

    caller_key = request.client.host if request.client else ""
    payload = build_pay_payload(body, caller_key)
    ok, reason = validate_client_amount(
        body.operation, body.amount_usd, body.asset, network=body.network
    )
    if not ok:
        logger.warning(
            "x402_underpayment_rejected",
            extra={"operation": body.operation, "reason": reason},
        )
        return rejected_payment(payload, reason)
    verify_result, settlement = await verify_and_settle(payload)
    return paid_payload(payload, verify_result, settlement)
