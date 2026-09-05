"""Admin dashboard, health, metrics, config, and ping endpoints."""

from __future__ import annotations

import logging
import os
import time
from typing import Any

from fastapi import Body, HTTPException, Query
from fastapi.responses import PlainTextResponse
from prometheus_client import generate_latest

from pry.api.routers.core.admin import ADMIN_DIR, PRY_DATA_DIR, router
from pry.api.routers.core.admin_shared import (
    CACHE_HIT_RATIO,
    COST_TOTAL,
    REVENUE_TOTAL,
    SCRAPES_ACTIVE,
    _compute_profits,
    _get_apify_profits,
)
from pry.core.deps import automator, cache, ratelimiter

logger = logging.getLogger(__name__)

# Process start time for uptime reporting (avoids blocking os.path calls
# inside async handlers — ASYNC240).
_START_TIME = time.time()


@router.get(
    "/v1/admin/dashboard",
    summary="Complete admin dashboard with profits and health",
)
async def admin_dashboard(
    days: int = Query(30, description="Number of days to look back"),
) -> dict[str, Any]:
    """Get the full admin dashboard: profits, costs, system health, Apify."""
    profits = _compute_profits(days)
    apify = _get_apify_profits()

    # System health
    cache_stats = cache.stats()
    rate_stats = ratelimiter.get_stats()
    hit_rate = cache_stats.get("hit_rate", 0)

    REVENUE_TOTAL.set(profits["x402"]["revenue_usd"])
    COST_TOTAL.set(profits["costs"]["total_operating_cost_usd"])
    CACHE_HIT_RATIO.set(hit_rate)

    return {
        "success": True,
        "profits": profits,
        "apify": apify,
        "system": {
            "cache_hit_rate": hit_rate,
            "active_sessions": len(automator.sessions),
            "total_requests": rate_stats.get("total_requests", 0),
            "active_ips": rate_stats.get("active_ips", 0),
            "blocked_requests": rate_stats.get("total_blocked", 0),
        },
        "period_days": days,
    }


@router.get(
    "/v1/admin/profits",
    summary="Profit breakdown from x402 payments minus costs",
)
async def admin_profits(
    days: int = Query(30, description="Lookback period in days"),
) -> dict[str, Any]:
    """Detailed profit/loss breakdown."""
    return {"success": True, "data": _compute_profits(days)}


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
    "/v1/admin/api-usage",
    summary="API usage stats: calls today, by endpoint, latency, errors, top users",
)
async def admin_api_usage() -> dict[str, Any]:
    """API usage statistics from the usage table for the last 24h."""
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import func as sa_func

    from pry.core.db.models import Usage, User
    from pry.core.db.session import get_session

    cutoff = datetime.now(UTC) - timedelta(hours=24)
    try:
        with get_session() as session:
            total_calls_today = (
                session.query(sa_func.count())
                .select_from(Usage)
                .filter(Usage.created_at >= cutoff)
                .scalar()
                or 0
            )
            by_endpoint_rows = (
                session.query(Usage.endpoint, sa_func.count())
                .filter(Usage.created_at >= cutoff)
                .group_by(Usage.endpoint)
                .all()
            )
            avg_ms = (
                session.query(sa_func.avg(Usage.duration_ms))
                .filter(Usage.created_at >= cutoff)
                .scalar()
            )
            errors = (
                session.query(sa_func.count())
                .select_from(Usage)
                .filter(Usage.created_at >= cutoff, Usage.status != "success")
                .scalar()
                or 0
            )
            top_rows = (
                session.query(Usage.user_id, sa_func.count().label("calls"))
                .filter(Usage.created_at >= cutoff)
                .group_by(Usage.user_id)
                .order_by(sa_func.count().desc())
                .limit(10)
                .all()
            )
            emails = {
                u.user_id: u.email
                for u in session.query(User)
                .filter(User.user_id.in_([r[0] for r in top_rows]))
                .all()
            }
        error_rate = round(errors / total_calls_today * 100, 2) if total_calls_today else 0.0
        return {
            "success": True,
            "total_calls_today": int(total_calls_today),
            "calls_by_endpoint": {ep or "unknown": cnt for ep, cnt in by_endpoint_rows},
            "avg_response_time_ms": round(float(avg_ms), 2) if avg_ms is not None else 0.0,
            "error_rate": error_rate,
            "top_users": [
                {"user_id": uid, "email": emails.get(uid, ""), "calls": cnt}
                for uid, cnt in top_rows
            ],
        }
    except Exception as e:
        logger.warning("api_usage_fetch_failed", extra={"error": str(e)})
        raise HTTPException(status_code=503, detail=f"api usage unavailable: {e}") from e


@router.get(
    "/v1/admin/actors",
    summary="Actor marketplace status: totals, runs today, revenue",
)
async def admin_actors() -> dict[str, Any]:
    """Actor status for the admin panel. Run stats come from scrape_jobs
    (the ActorRun table was dropped); revenue from the actors table."""
    from datetime import UTC, datetime

    from sqlalchemy import func as sa_func

    from pry.core.db.models import Actor, ScrapeJob
    from pry.core.db.session import get_session

    day_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    try:
        with get_session() as session:
            total_actors = session.query(sa_func.count()).select_from(Actor).scalar() or 0
            active_runs = (
                session.query(sa_func.count())
                .select_from(ScrapeJob)
                .filter(ScrapeJob.status.in_(("pending", "running")))
                .scalar()
                or 0
            )
            completed_today = (
                session.query(sa_func.count())
                .select_from(ScrapeJob)
                .filter(ScrapeJob.status == "completed", ScrapeJob.completed_at >= day_start)
                .scalar()
                or 0
            )
            failed_today = (
                session.query(sa_func.count())
                .select_from(ScrapeJob)
                .filter(ScrapeJob.status == "failed", ScrapeJob.updated_at >= day_start)
                .scalar()
                or 0
            )
            revenue_from_actors = (
                session.query(sa_func.coalesce(sa_func.sum(Actor.revenue_usd), 0.0)).scalar() or 0.0
            )
        return {
            "success": True,
            "total_actors": int(total_actors),
            "active_runs": int(active_runs),
            "completed_today": int(completed_today),
            "failed_today": int(failed_today),
            "revenue_from_actors": round(float(revenue_from_actors), 2),
        }
    except Exception as e:
        logger.warning("actors_fetch_failed", extra={"error": str(e)})
        raise HTTPException(status_code=503, detail=f"actors unavailable: {e}") from e


@router.get(
    "/v1/admin/health",
    summary="System health check",
)
async def admin_health() -> dict[str, Any]:
    """Health check with component status."""
    cache_stats = cache.stats()
    rate_stats = ratelimiter.get_stats()
    uptime = time.time() - _START_TIME

    return {
        "success": True,
        "status": "healthy",
        "uptime_seconds": uptime,
        "cache": {
            "hit_rate": cache_stats.get("hit_rate", 0),
            "size": cache_stats.get("size", 0),
            "hits": cache_stats.get("hits", 0),
        },
        "rate_limiter": {
            "total_requests": rate_stats.get("total_requests", 0),
            "active_ips": rate_stats.get("active_ips", 0),
        },
        "automator": {
            "available": automator.available,
            "active_sessions": len(automator.sessions),
        },
        "version": "3.0.0",
    }


@router.get(
    "/v1/admin/apify",
    summary="Apify actor profit monitoring",
)
async def admin_apify() -> dict[str, Any]:
    """Fetch profit data from Apify API."""
    return {"success": True, "data": _get_apify_profits()}


@router.get(
    "/v1/admin/metrics",
    summary="Prometheus metrics for Grafana",
    response_class=PlainTextResponse,
)
async def admin_metrics() -> str:
    """Generate Prometheus-formatted metrics for Grafana scraping."""
    # Refresh metrics
    profits = _compute_profits(30)
    cache_stats = cache.stats()
    REVENUE_TOTAL.set(profits["x402"]["revenue_usd"])
    COST_TOTAL.set(profits["costs"]["total_operating_cost_usd"])
    CACHE_HIT_RATIO.set(cache_stats.get("hit_rate", 0))
    SCRAPES_ACTIVE.set(len(automator.sessions))

    return generate_latest().decode("utf-8")


@router.get(
    "/v1/admin/config",
    summary="Show admin configuration status",
)
async def admin_config() -> dict[str, Any]:
    """Show which admin features are configured."""
    return {
        "success": True,
        "apify_api_key_set": bool(os.getenv("APIFY_API_KEY", "")),
        "admin_dir": ADMIN_DIR,
        "data_dir": PRY_DATA_DIR,
        "metrics_enabled": True,
    }


@router.post(
    "/v1/admin/ping",
    summary="Health check with request body",
)
async def admin_ping(body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    """Simple ping-pong for monitoring."""
    return {"success": True, "pong": True, "echo": body}


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
            revenue_by_actor_rows = (
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


@router.get(
    "/v1/admin/issues",
    summary="Outstanding customer issues and unresolved payments",
)
async def admin_issues() -> dict[str, Any]:
    """Support ticket summary from the in-memory issue tracker."""
    from pry.api.routers.core.admin_shared import _issue_summary

    return {"success": True, **_issue_summary()}


@router.post(
    "/v1/admin/issues/{issue_id}/resolve",
    summary="Mark a support issue as resolved",
)
async def admin_issue_resolve(issue_id: str) -> dict[str, Any]:
    """Resolve an issue by ID."""
    from pry.api.routers.core.admin_shared import _resolve_issue

    issue = _resolve_issue(issue_id)
    if issue is None:
        raise HTTPException(status_code=404, detail=f"issue '{issue_id}' not found")
    return {"success": True, "issue": issue}
