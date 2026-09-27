"""Pry — Visitor analytics & platform stats tracking.

Tracks pageviews, unique visitors, and API endpoint popularity for the
cloud-hosted platform. Visitor events are kept in a thread-safe in-memory
store (production deployments would use ClickHouse or Postgres); API
popularity and signup funnel stats are computed from the ``Usage`` and
``User`` database models.

Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC

from __future__ import annotations

import threading
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Body, HTTPException

from pry.api.routers.core.admin_router import router as admin_router
from pry.core.db.models import Usage, User
from pry.core.db.session import get_session

router = APIRouter(tags=["Analytics"])

# ── In-memory visitor tracking store ──
# Thread-safe: all mutations go through _STORE_LOCK. Bounded to keep memory
# flat; production would stream these to ClickHouse/Postgres instead.
_MAX_EVENTS = 100_000

_STORE_LOCK = threading.Lock()
_EVENTS: list[
    dict[str, Any]
] = []  # {"ts": datetime, "event": str, "path": str, "visitor": str, "session_id": str}

_VALID_EVENTS = ("pageview", "click", "signup", "api_call")


def _record_event(event: str, path: str, visitor: str, session_id: str) -> None:
    """Append an event to the in-memory store (thread-safe, bounded)."""
    with _STORE_LOCK:
        _EVENTS.append(
            {
                "ts": datetime.now(UTC),
                "event": event,
                "path": path,
                "visitor": visitor,
                "session_id": session_id,
            }
        )
        if len(_EVENTS) > _MAX_EVENTS:
            del _EVENTS[: len(_EVENTS) - _MAX_EVENTS]


def _snapshot_events() -> list[dict[str, Any]]:
    """Copy of the event list for lock-free aggregation."""
    with _STORE_LOCK:
        return list(_EVENTS)


def _day_key(ts: datetime) -> str:
    return ts.strftime("%Y-%m-%d")


def _visitor_stats(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate visitor/pageview stats from raw events."""
    now = datetime.now(UTC)
    today = _day_key(now)
    month_prefix = now.strftime("%Y-%m")

    pageviews = [e for e in events if e["event"] == "pageview"]
    visitors_today: set[str] = set()
    visitors_month: set[str] = set()
    views_today = 0
    views_month = 0
    views_by_day: Counter[str] = Counter()
    visitors_by_day: dict[str, set[str]] = defaultdict(set)
    page_counts: Counter[str] = Counter()

    for e in pageviews:
        day = _day_key(e["ts"])
        views_by_day[day] += 1
        visitors_by_day[day].add(e["visitor"])
        page_counts[e["path"]] += 1
        if day == today:
            views_today += 1
            visitors_today.add(e["visitor"])
        if e["ts"].strftime("%Y-%m") == month_prefix:
            views_month += 1
            visitors_month.add(e["visitor"])

    # 30-day series (oldest → newest), zero-filled.
    visitors_by_day_list = []
    for i in range(29, -1, -1):
        day = _day_key(now - timedelta(days=i))
        visitors_by_day_list.append({"day": day, "visitors": len(visitors_by_day.get(day, set()))})

    # Average session duration: group pageviews by session, span = last - first.
    session_spans: dict[str, list[datetime]] = defaultdict(list)
    for e in pageviews:
        if e["session_id"]:
            session_spans[e["session_id"]].append(e["ts"])
    durations = [
        (max(tss) - min(tss)).total_seconds() for tss in session_spans.values() if len(tss) > 1
    ]
    avg_session_duration = round(sum(durations) / len(durations), 1) if durations else 0.0

    return {
        "unique_visitors_today": len(visitors_today),
        "unique_visitors_this_month": len(visitors_month),
        "pageviews_today": views_today,
        "pageviews_this_month": views_month,
        "visitors_by_day": visitors_by_day_list,
        "top_pages": [{"path": p, "views": v} for p, v in page_counts.most_common(10)],
        "avg_session_duration": avg_session_duration,
    }


# ── Public tracking endpoint ──


@router.post(
    "/v1/analytics/track",
    summary="Track a pageview or event",
)
async def track_event(
    payload: dict[str, Any] = Body(...),
) -> dict[str, Any]:
    """Record a pageview/click/signup/api_call event.

    In-memory store only — production would forward to ClickHouse/Postgres.
    """
    event = str(payload.get("event") or "").strip().lower()
    if event not in _VALID_EVENTS:
        raise HTTPException(status_code=422, detail=f"event must be one of {_VALID_EVENTS}")

    _record_event(
        event=event,
        path=str(payload.get("path") or ""),
        visitor=str(payload.get("user_id") or payload.get("session_id") or "anonymous"),
        session_id=str(payload.get("session_id") or ""),
    )
    return {"success": True}


@router.get(
    "/v1/analytics/visitors",
    summary="Visitor and pageview stats",
)
async def visitor_stats() -> dict[str, Any]:
    """Unique visitors, pageviews, top pages, and 30-day series."""
    return _visitor_stats(_snapshot_events())


@router.get(
    "/v1/analytics/api-popularity",
    summary="API endpoint popularity",
)
async def api_popularity() -> dict[str, Any]:
    """Endpoint popularity from the Usage table: calls, error rate, latency."""
    calls: Counter[str] = Counter()
    errors: Counter[str] = Counter()
    latency_sum: dict[str, float] = defaultdict(float)

    with get_session() as session:
        rows = session.query(Usage.endpoint, Usage.status, Usage.duration_ms).all()  # type: ignore[attr-defined]
    for endpoint, status, duration_ms in rows:
        name = endpoint or "unknown"
        calls[name] += 1
        if str(status) != "success":
            errors[name] += 1
        latency_sum[name] += float(duration_ms or 0)

    by_error_rate = {name: round(errors[name] / calls[name], 4) for name in calls if calls[name]}
    by_avg_latency = {
        name: round(latency_sum[name] / calls[name], 1) for name in calls if calls[name]
    }
    trending = [name for name, _ in calls.most_common(10)]

    return {
        "endpoints_by_calls": dict(calls.most_common()),
        "endpoints_by_error_rate": by_error_rate,
        "endpoints_by_avg_latency": by_avg_latency,
        "trending_endpoints": trending,
    }


@router.get(
    "/v1/analytics/funnel",
    summary="Signup funnel stats",
)
async def signup_funnel() -> dict[str, Any]:
    """Visitors → signups conversion, by day and by source."""
    events = _snapshot_events()
    visitors = {e["visitor"] for e in events if e["visitor"]}

    signups_by_day: Counter[str] = Counter()
    signups_by_source: Counter[str] = Counter()
    with get_session() as session:
        rows = session.query(User.created_at).all()  # type: ignore[attr-defined]
    for (created_at,) in rows:
        if created_at is None:
            continue
        signups_by_day[_day_key(created_at)] += 1
        signups_by_source["direct"] += 1  # source attribution not tracked yet

    signups = len(rows)
    conversion_rate = round(signups / len(visitors), 4) if visitors else 0.0

    now = datetime.now(UTC)
    series = []
    for i in range(29, -1, -1):
        day = _day_key(now - timedelta(days=i))
        series.append({"day": day, "signups": signups_by_day.get(day, 0)})

    return {
        "visitors": len(visitors),
        "signups": signups,
        "conversion_rate": conversion_rate,
        "signups_by_day": series,
        "signups_by_source": dict(signups_by_source),
    }


# ── Admin-only combined overview (behind the admin security gate) ──


@admin_router.get(
    "/v1/admin/analytics/overview",
    summary="Combined analytics dashboard (admin)",
)
async def admin_analytics_overview() -> dict[str, Any]:
    """Aggregate visitors, API usage, revenue, signups, and active users."""
    events = _snapshot_events()
    visitors = _visitor_stats(events)

    with get_session() as session:
        total_users = session.query(User).count()  # type: ignore[attr-defined]
        active_users = session.query(User).filter(User.is_active.is_(True)).count()  # type: ignore[attr-defined]
        usage_rows = session.query(
            Usage.endpoint, Usage.status, Usage.duration_ms, Usage.cost_usd
        ).all()  # type: ignore[attr-defined]

    calls: Counter[str] = Counter()
    errors: Counter[str] = Counter()
    latency_sum: dict[str, float] = defaultdict(float)
    revenue = 0.0
    for endpoint, status, duration_ms, cost_usd in usage_rows:
        name = endpoint or "unknown"
        calls[name] += 1
        if str(status) != "success":
            errors[name] += 1
        latency_sum[name] += float(duration_ms or 0)
        revenue += float(cost_usd or 0)

    api_usage = {
        "endpoints_by_calls": dict(calls.most_common()),
        "endpoints_by_error_rate": {
            name: round(errors[name] / calls[name], 4) for name in calls if calls[name]
        },
        "endpoints_by_avg_latency": {
            name: round(latency_sum[name] / calls[name], 1) for name in calls if calls[name]
        },
        "total_calls": sum(calls.values()),
    }

    signups_by_day: Counter[str] = Counter()
    with get_session() as session:
        for (created_at,) in session.query(User.created_at).all():  # type: ignore[attr-defined]
            if created_at is not None:
                signups_by_day[_day_key(created_at)] += 1

    now = datetime.now(UTC)
    signups_series = [
        {
            "day": _day_key(now - timedelta(days=i)),
            "signups": signups_by_day.get(_day_key(now - timedelta(days=i)), 0),
        }
        for i in range(29, -1, -1)
    ]

    return {
        "visitors": visitors,
        "api_usage": api_usage,
        "revenue": {"total_usd": round(revenue, 2)},
        "signups": {"total": total_users, "by_day": signups_series},
        "active_users": active_users,
    }
