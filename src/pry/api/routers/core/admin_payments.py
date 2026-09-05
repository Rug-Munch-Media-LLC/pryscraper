"""Admin earnings, treasury, and payments endpoints."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query  # noqa: F401 - APIRouter re-exported

from pry.api.routers.core.admin import router
from pry.api.routers.core.admin_shared import _earnings_source, _get_x402_payments, _parse_ts

logger = logging.getLogger(__name__)


@router.get(
    "/v1/admin/earnings",
    summary="Earnings: total + daily + by-stream + by-chain",
)
async def admin_earnings(
    days: int = Query(30, description="Lookback period in days"),
) -> dict[str, Any]:
    """Aggregate earnings across all revenue streams."""
    tracker, backend = _earnings_source()
    try:
        return {
            "success": True,
            "backend": backend,
            "total": tracker.get_total_earnings(days),
            "daily": tracker.get_daily_earnings(days),
            "by_stream": tracker.get_revenue_by_stream(days),
            "by_chain": tracker.get_revenue_by_chain(days),
            "mrr": tracker.get_mrr(),
            "growth": tracker.get_growth_rate(days),
        }
    except Exception as e:
        logger.warning("earnings_fetch_failed", extra={"error": str(e)})
        raise HTTPException(status_code=503, detail=f"earnings unavailable: {e}") from e


@router.get(
    "/v1/admin/earnings/treasury",
    summary="On-chain treasury wallet balances",
)
async def admin_treasury() -> dict[str, Any]:
    """On-chain balances for the operator treasuries (EVM / Solana / TRON)."""
    tracker, backend = _earnings_source()
    try:
        return {"success": True, "backend": backend, "treasury": tracker.get_treasury_balances()}
    except Exception as e:
        logger.warning("treasury_fetch_failed", extra={"error": str(e)})
        raise HTTPException(status_code=503, detail=f"treasury unavailable: {e}") from e


@router.get(
    "/v1/admin/payments/recent",
    summary="Last 50 payments from payments.jsonl",
)
async def admin_payments_recent() -> dict[str, Any]:
    """Most recent payments, newest first."""
    payments = _get_x402_payments(days=30)
    payments.sort(
        key=lambda p: _parse_ts(p.get("ts", "")) or datetime.min.replace(tzinfo=UTC), reverse=True
    )
    return {"success": True, "count": len(payments[:50]), "payments": payments[:50]}


@router.get(
    "/v1/admin/payments/failed",
    summary="Failed payment verifications",
)
async def admin_payments_failed() -> dict[str, Any]:
    """Payments whose verification did not succeed, with failure reasons."""
    payments = _get_x402_payments(days=30)
    failed = [p for p in payments if not p.get("verified")]
    failed.sort(
        key=lambda p: _parse_ts(p.get("ts", "")) or datetime.min.replace(tzinfo=UTC), reverse=True
    )
    return {"success": True, "count": len(failed), "payments": failed[:50]}
