"""Admin usage endpoints: API usage stats and actor marketplace status."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import logging
from typing import Any

from fastapi import HTTPException

from pry.api.routers.core.admin import router

logger = logging.getLogger(__name__)


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
