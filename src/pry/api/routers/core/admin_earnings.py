"""Admin earnings endpoints: revenue, combined, Apify actor, cloud subscription."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import logging
from typing import Any

from fastapi import HTTPException, Query

from pry.api.routers.core.admin_router import router

logger = logging.getLogger(__name__)


@router.get(
    "/v1/admin/revenue",
    summary="Revenue summary: totals, by tier, by chain, MRR, growth",
)
async def admin_revenue(
    days: int = Query(30, description="Lookback period in days"),
) -> dict[str, Any]:
    """Revenue summary for the cloud admin panel, backed by the earnings
    tracker (x402 payments + subscription invoices + actor revenue)."""
    from pry.api.routers.core.admin_shared import _earnings_source

    tracker, backend = _earnings_source()
    try:
        total = tracker.get_total_earnings(days)
        monthly = tracker.get_total_earnings(30)
        by_chain = tracker.get_revenue_by_chain(days)
        mrr = tracker.get_mrr()
        growth = tracker.get_growth_rate(days)

        # Revenue by tier: subscription MRR split by tier price.
        from pry.payments.earnings_shared import TIERS_SAFE

        revenue_by_tier: dict[str, float] = {"free": 0.0}
        for tier_name, count in mrr.get("by_tier", {}).items():
            price = (TIERS_SAFE.get(tier_name) or {}).get("price_usd_monthly") or 0.0
            revenue_by_tier[tier_name] = round(float(price) * int(count), 2)

        # Normalize chain split to the evm/solana/tron buckets the panel expects.
        revenue_by_chain = {"evm": 0.0, "solana": 0.0, "tron": 0.0}
        for chain, data in by_chain.items():
            bucket = str(chain).lower()
            if bucket not in revenue_by_chain:
                bucket = "evm"
            revenue_by_chain[bucket] = round(
                revenue_by_chain[bucket] + float(data.get("total_usd", 0)), 2
            )

        return {
            "success": True,
            "backend": backend,
            "total_revenue": total.get("total_usd", 0),
            "monthly_revenue": monthly.get("total_usd", 0),
            "revenue_by_tier": revenue_by_tier,
            "revenue_by_chain": revenue_by_chain,
            "mrr": mrr.get("mrr_usd", 0),
            "growth_rate": growth.get("growth_rate_pct"),
            "period_days": days,
        }
    except Exception as e:
        logger.warning("revenue_fetch_failed", extra={"error": str(e)})
        raise HTTPException(status_code=503, detail=f"revenue unavailable: {e}") from e


@router.get(
    "/v1/admin/earnings/combined",
    summary="Combined earnings from all revenue streams",
)
async def admin_earnings_combined(
    days: int = Query(30, description="Lookback period in days"),
) -> dict[str, Any]:
    """Earnings across x402 payments, subscriptions, actors, and packs."""
    from pry.api.routers.core.admin_shared import _earnings_source

    tracker, backend = _earnings_source()
    try:
        total = tracker.get_total_earnings(days)
        daily = tracker.get_daily_earnings(days)
        by_stream = total.get("by_stream", {})
        revenue_by_source = {
            "x402": round(float(by_stream.get("x402", 0)), 2),
            "subscription": round(float(by_stream.get("subscriptions", 0)), 2),
            "actor": round(float(by_stream.get("apify_actors", 0)), 2),
            "pack": round(float(by_stream.get("packs", 0)), 2),
        }
        return {
            "success": True,
            "backend": backend,
            "x402_revenue": revenue_by_source["x402"],
            "subscription_revenue": revenue_by_source["subscription"],
            "actor_revenue": revenue_by_source["actor"],
            "pack_revenue": revenue_by_source["pack"],
            "total_revenue": round(float(total.get("total_usd", 0)), 2),
            "revenue_by_day": daily,
            "revenue_by_source": revenue_by_source,
            "period_days": days,
        }
    except Exception as e:
        logger.warning("combined_earnings_fetch_failed", extra={"error": str(e)})
        raise HTTPException(status_code=503, detail=f"earnings unavailable: {e}") from e


@router.get(
    "/v1/admin/earnings/apify",
    summary="Apify actor earnings: per-actor revenue and run volume",
)
async def admin_earnings_apify() -> dict[str, Any]:
    """Actor earnings from the actors table plus run volume from scrape_jobs."""
    from datetime import UTC, datetime

    from sqlalchemy import func as sa_func

    from pry.core.db.models import Actor, ScrapeJob
    from pry.core.db.session import get_session

    now = datetime.now(UTC)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    month_start = day_start.replace(day=1)
    try:
        with get_session() as session:
            revenue_by_actor_rows: list = (
                session.query(Actor.actor_id, Actor.name, Actor.revenue_usd)
                .order_by(Actor.revenue_usd.desc())
                .all()
            )
            runs_today = (
                session.query(sa_func.count())
                .select_from(ScrapeJob)
                .filter(ScrapeJob.created_at >= day_start)
                .scalar()
                or 0
            )
            runs_this_month = (
                session.query(sa_func.count())
                .select_from(ScrapeJob)
                .filter(ScrapeJob.created_at >= month_start)
                .scalar()
                or 0
            )
        revenue_by_actor = {
            actor_id: round(float(rev or 0), 2) for actor_id, _name, rev in revenue_by_actor_rows
        }
        top = [
            {"actor_id": actor_id, "name": name, "revenue_usd": round(float(rev or 0), 2)}
            for actor_id, name, rev in revenue_by_actor_rows[:10]
        ]
        return {
            "success": True,
            "total_actor_revenue": round(sum(revenue_by_actor.values()), 2),
            "revenue_by_actor": revenue_by_actor,
            "runs_today": int(runs_today),
            "runs_this_month": int(runs_this_month),
            "top_earning_actors": top,
        }
    except Exception as e:
        logger.warning("apify_earnings_fetch_failed", extra={"error": str(e)})
        raise HTTPException(status_code=503, detail=f"actor earnings unavailable: {e}") from e


@router.get(
    "/v1/admin/earnings/cloud",
    summary="Cloud subscription earnings: MRR, ARR, tiers, churn, LTV",
)
async def admin_earnings_cloud() -> dict[str, Any]:
    """Subscription economics from the earnings tracker's MRR view."""
    from pry.api.routers.core.admin_shared import _earnings_source

    tracker, backend = _earnings_source()
    try:
        mrr_data = tracker.get_mrr()
        mrr = float(mrr_data.get("mrr_usd", 0))
        active = int(mrr_data.get("active_subscriptions", 0))
        by_tier_raw = mrr_data.get("by_tier", {})
        subscribers_by_tier = {
            tier: int(by_tier_raw.get(tier, 0)) for tier in ("free", "scout", "hunter", "pro")
        }
        # Churn is not tracked yet (no cancellation ledger); report 0.0 until a
        # real churn source exists. LTV assumes a 12-month average lifetime.
        # [REVIEW] wire both to real cancellation/invoice history.
        churn_rate = 0.0
        avg_monthly = mrr / active if active else 0.0
        ltv_estimate = round(avg_monthly * 12, 2)
        return {
            "success": True,
            "backend": backend,
            "mrr": round(mrr, 2),
            "arr": round(mrr * 12, 2),
            "subscribers_active": active,
            "subscribers_by_tier": subscribers_by_tier,
            "churn_rate": churn_rate,
            "ltv_estimate": ltv_estimate,
        }
    except Exception as e:
        logger.warning("cloud_earnings_fetch_failed", extra={"error": str(e)})
        raise HTTPException(
            status_code=503, detail=f"subscription earnings unavailable: {e}"
        ) from e
