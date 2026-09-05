"""Admin actor catalog endpoints: preview with icons and per-actor detail."""

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


def _actor_status(visibility: str) -> str:
    """Map DB visibility to a catalog status.

    The Actor model has no explicit status column, so visibility is the
    closest signal: public=active, unlisted=maintenance, private=deprecated.
    [REVIEW] add a real status column when lifecycle management lands.
    """
    return {"public": "active", "unlisted": "maintenance"}.get(visibility, "deprecated")


@router.get(
    "/v1/admin/actors/preview",
    summary="Actor catalog preview with icons, pricing, and revenue",
)
async def admin_actors_preview() -> dict[str, Any]:
    """Merge preset catalog metadata with live Actor DB rows."""
    from sqlalchemy import func as sa_func

    from pry.core.db.models import Actor
    from pry.core.db.session import get_session

    # Preset metadata (title, description, category, icon) — degrade to an
    # empty overlay if the factory catalog is unavailable.
    presets: dict[str, Any] = {}
    try:
        from actor_factory.presets import ALL_PRESETS

        presets = ALL_PRESETS
    except Exception as e:  # noqa: BLE001 - catalog must serve even if factory absent
        logger.warning("actor_presets_unavailable", extra={"error": str(e)})

    try:
        with get_session() as session:
            rows = session.query(Actor).all()
            total_runs = (
                session.query(sa_func.coalesce(sa_func.sum(Actor.run_count), 0)).scalar() or 0
            )
            total_revenue = (
                session.query(sa_func.coalesce(sa_func.sum(Actor.revenue_usd), 0.0)).scalar() or 0.0
            )
    except Exception as e:
        logger.warning("actor_db_unavailable", extra={"error": str(e)})
        raise HTTPException(status_code=503, detail=f"actors unavailable: {e}") from e

    db_by_name = {a.actor_id: a for a in rows}
    actors: list[dict[str, Any]] = []
    for name, spec in sorted(presets.items()):
        db = db_by_name.get(name)
        actors.append(
            {
                "name": name,
                "title": spec.title,
                "description": spec.description,
                "category": str(getattr(spec.category, "value", spec.category)),
                "icon": spec.icon,
                "price_per_run": float(db.price_per_run) if db else 0.0,
                "total_runs": int(db.run_count) if db else 0,
                "revenue": round(float(db.revenue_usd or 0), 2) if db else 0.0,
                "status": _actor_status(db.visibility) if db else "deprecated",
            }
        )
    # Include DB-only actors that have no preset entry.
    for actor_id, db in sorted(db_by_name.items()):
        if actor_id in presets:
            continue
        actors.append(
            {
                "name": actor_id,
                "title": db.name,
                "description": db.description or "",
                "category": "CUSTOM",
                "icon": "",
                "price_per_run": float(db.price_per_run or 0),
                "total_runs": int(db.run_count or 0),
                "revenue": round(float(db.revenue_usd or 0), 2),
                "status": _actor_status(db.visibility),
            }
        )

    categories = sorted({a["category"] for a in actors})
    return {
        "success": True,
        "actors": actors,
        "total": len(actors),
        "categories": categories,
        "total_runs": int(total_runs),
        "total_revenue": round(float(total_revenue), 2),
    }


@router.get(
    "/v1/admin/actors/{actor_name}",
    summary="Single actor detail: spec, pricing, runs, revenue, error rate",
)
async def admin_actor_detail(actor_name: str) -> dict[str, Any]:
    """Full detail for one actor: preset spec plus live DB stats."""
    from datetime import UTC, datetime

    from sqlalchemy import func as sa_func

    from pry.core.db.models import Actor, ScrapeJob
    from pry.core.db.session import get_session

    spec_data: dict[str, Any] = {}
    try:
        from actor_factory.presets import ALL_PRESETS

        spec = ALL_PRESETS.get(actor_name)
        if spec is not None:
            spec_data = {
                "title": spec.title,
                "description": spec.description,
                "version": spec.version,
                "category": str(getattr(spec.category, "value", spec.category)),
                "uses_browser": spec.uses_browser,
                "processor": spec.processor,
                "min_memory_mbytes": spec.min_memory_mbytes,
                "max_memory_mbytes": spec.max_memory_mbytes,
                "inputs": [
                    {
                        "name": f.name,
                        "title": f.title,
                        "type": f.type,
                        "required": f.required,
                        "description": f.description,
                    }
                    for f in spec.inputs
                ],
                "pricing_events": [
                    {
                        "name": e.name,
                        "title": e.title,
                        "price_usd": e.price_usd,
                        "description": e.description,
                    }
                    for e in spec.pricing_events
                ],
            }
    except Exception as e:  # noqa: BLE001 - detail must serve even if factory absent
        logger.warning("actor_spec_unavailable", extra={"error": str(e)})

    try:
        with get_session() as session:
            db = session.query(Actor).filter(Actor.actor_id == actor_name).first()
            if db is None:
                raise HTTPException(status_code=404, detail=f"actor '{actor_name}' not found")
            day_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
            runs_total = int(db.run_count or 0)
            failed_total = (
                session.query(sa_func.count())
                .select_from(ScrapeJob)
                .filter(ScrapeJob.status == "failed", ScrapeJob.created_at >= day_start)
                .scalar()
                or 0
            )
            runs_today = (
                session.query(sa_func.count())
                .select_from(ScrapeJob)
                .filter(ScrapeJob.created_at >= day_start)
                .scalar()
                or 0
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.warning("actor_detail_fetch_failed", extra={"error": str(e)})
        raise HTTPException(status_code=503, detail=f"actor detail unavailable: {e}") from e

    # Error rate is scoped to today's scrape_jobs window (the ActorRun table
    # was dropped, so per-actor historical errors are not available).
    error_rate = round(failed_total / runs_today * 100, 2) if runs_today else 0.0
    return {
        "success": True,
        "actor_id": actor_name,
        "spec": spec_data,
        "price_per_run": float(db.price_per_run or 0),
        "visibility": db.visibility,
        "tags": db.tags or [],
        "author": db.author or "",
        "total_runs": runs_total,
        "runs_today": int(runs_today),
        "revenue_usd": round(float(db.revenue_usd or 0), 2),
        "error_rate": error_rate,
        "created_at": db.created_at.isoformat() if db.created_at else None,
    }
