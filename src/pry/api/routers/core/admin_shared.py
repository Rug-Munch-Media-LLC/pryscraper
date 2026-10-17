"""Shared helpers and Prometheus metrics for the admin router modules.

Path constants (PRY_DATA_DIR / ADMIN_DIR) live in the ``admin`` facade so
tests can monkeypatch them there; helpers resolve them lazily at call time.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
from datetime import UTC, datetime, timedelta
from typing import Any

from prometheus_client import Counter, Gauge, Histogram

# The in-memory issue tracker moved to admin_issues_store.py. Re-exported here
# because admin_issues.py imports these names FROM THIS MODULE via deferred
# imports, and that import surface must not change. Identical objects, not copies.
from pry.api.routers.core.admin_issues_store import (  # noqa: F401
    _ISSUES,
    _create_issue,
    _issue_summary,
    _resolve_issue,
)

logger = logging.getLogger(__name__)

# ── Prometheus metrics (prefixed with admin_ to avoid observability.py conflicts) ──
SCRAPES_TOTAL = Counter("pry_admin_scrapes_total", "Total scrape requests", ["method"])
SCRAPES_DURATION = Histogram("pry_admin_scrapes_duration_seconds", "Scrape duration", ["method"])
PAYMENTS_TOTAL = Counter("pry_admin_payments_total", "Total x402 payments", ["chain", "asset"])
PAYMENTS_AMOUNT = Gauge("pry_admin_payments_amount_usd", "Total x402 payment amount in USD")
SCRAPES_ACTIVE = Gauge("pry_admin_scrapes_active", "Currently active scrapes")
CACHE_HIT_RATIO = Gauge("pry_admin_cache_hit_ratio", "Cache hit ratio")
REVENUE_TOTAL = Gauge("pry_admin_revenue_total_usd", "Total revenue in USD")
COST_TOTAL = Gauge("pry_admin_cost_total_usd", "Total operating cost in USD")
APIFY_PROFIT = Gauge("pry_admin_apify_profit_usd", "Apify platform profit in USD")


def _data_dir() -> str:
    """Resolve the data dir at call time (tests monkeypatch the facade)."""
    from pry.api.routers.core import admin as _admin

    return _admin.PRY_DATA_DIR


# ── Helpers ──


def _load_jsonl(path: str) -> list[dict[str, Any]]:
    """Load a JSONL file, returning a list of records."""
    records: list[dict[str, Any]] = []
    if os.path.exists(path):
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line:
                    with contextlib.suppress(json.JSONDecodeError):
                        records.append(json.loads(line))
    return records


def _parse_ts(raw: Any) -> datetime | None:
    """Parse an ISO-8601-ish timestamp to an aware UTC datetime.

    Naive values are treated as UTC rather than raising; absent or malformed
    values return None so callers can decide the fallback.
    """
    if isinstance(raw, datetime):
        parsed = raw
    elif isinstance(raw, str) and raw.strip():
        try:
            parsed = datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
        except ValueError:
            logger.warning("admin_shared_exception_handler", exc_info=True)
            return None
    else:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _payment_ts(p: dict[str, Any]) -> datetime | None:
    """Canonical payment time: verified_at -> ts -> created_at (aware UTC)."""
    from pry.payments.analytics import payment_ts

    return payment_ts(p)


def _payment_amount(p: dict[str, Any]) -> float:
    """Coerce a payment row's amount to float; corrupt rows count as 0."""
    try:
        return float(p.get("amount_usd", 0) or 0)
    except (TypeError, ValueError):
        logger.warning("admin_shared_exception_handler", exc_info=True)
        return 0.0


def _get_x402_payments(days: int = 30) -> list[dict[str, Any]]:
    """Load x402 payments inside the lookback window.

    Postgres x402_payment_records is the declared source of truth; the JSONL
    log is the fallback. Each returned row carries a normalized ts taken from
    verified_at -> ts -> created_at (aware UTC), so short windows are not
    empty and every caller sorts on the real event time.
    """
    from pry.payments.analytics import load_payment_records

    payments_file = os.path.join(_data_dir(), "x402", "payments.jsonl")
    cutoff = datetime.now(UTC) - timedelta(days=days)
    filtered: list[dict[str, Any]] = []
    for p in load_payment_records(payments_file):
        ts = _payment_ts(p)
        if ts is None:
            # Rows without a parseable timestamp are kept only for the default
            # full-window query so legacy logs still count toward totals.
            if days >= 30:
                filtered.append(dict(p))
            continue
        if ts >= cutoff:
            normalized = dict(p)
            normalized["ts"] = ts.isoformat()
            filtered.append(normalized)
    return filtered


def _get_usage_costs(days: int = 30) -> dict[str, Any]:
    """Get costing data for the last N days."""
    from pry.commerce.costing import get_cost_dashboard

    try:
        dashboard = get_cost_dashboard()
        return dashboard
    except (OSError, KeyError, ValueError, TypeError) as e:
        logger.warning("costing_ledger_unavailable", extra={"error": str(e)})
        return {"total_cost": 0, "by_operation": {}, "projected_monthly": 0, "unavailable": True}


def _compute_profits(days: int = 30) -> dict[str, Any]:
    """Compute profits from x402 payments minus operating costs."""
    payments = _get_x402_payments(days)
    # Revenue is verified-only: an unverified row is a failed attempt, not income.
    verified = [p for p in payments if p.get("verified")]
    x402_revenue = sum(_payment_amount(p) for p in verified)
    x402_count = len(payments)

    costs = _get_usage_costs(days)
    total_cost = costs.get("total_cost", 0)
    projected_cost = costs.get("projected_monthly", 0)

    # Estimate x402 profit (revenue - 2% processing fee)
    processing_fee = x402_revenue * 0.02
    net_x402 = x402_revenue - processing_fee - total_cost

    return {
        "x402": {
            "revenue_usd": round(x402_revenue, 2),
            "payment_count": x402_count,
            "processing_fee_usd": round(processing_fee, 2),
            "net_profit_usd": round(net_x402, 2),
        },
        "costs": {
            "total_operating_cost_usd": round(total_cost, 4),
            "projected_monthly_usd": round(projected_cost, 4),
            "unavailable": bool(costs.get("unavailable", False)),
        },
        "period_days": days,
    }


def _get_apify_profits() -> dict[str, Any]:
    """Fetch profit data from Apify API if configured."""
    api_key = os.getenv("APIFY_API_KEY", "")
    if not api_key:
        return {
            "configured": False,
            "message": "Set APIFY_API_KEY to enable Apify profit tracking",
            "actors": [],
            "total_profit_usd": 0,
        }
    try:
        import httpx

        # Apify API: list actor runs and compute cost/profit
        resp = httpx.get(
            "https://api.apify.com/v2/actor-runs/",
            params={"limit": 50, "status": "SUCCEEDED"},
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=10,
        )
        if resp.status_code != 200:
            return {"configured": True, "error": f"Apify API: {resp.status_code}", "actors": []}

        data = resp.json()
        runs = data.get("data", [])
        actors: dict[str, dict[str, Any]] = {}
        total_profit = 0.0
        for run in runs:
            aid = run.get("actId", "unknown")
            if aid not in actors:
                actors[aid] = {
                    "id": aid,
                    "name": run.get("actName", aid),
                    "runs": 0,
                    "total_cost_usd": 0,
                    "total_compute_units": 0,
                }
            actors[aid]["runs"] += 1
            cost = run.get("usageTotalUsd", 0) or 0
            actors[aid]["total_cost_usd"] += cost
            actors[aid]["total_compute_units"] += run.get("usageTotalCu", 0) or 0
            total_profit += cost

        APIFY_PROFIT.set(total_profit)
        return {
            "configured": True,
            "actors": list(actors.values()),
            "total_profit_usd": round(total_profit, 2),
            "total_runs": len(runs),
        }
    except (httpx.HTTPError, KeyError, ValueError, TypeError) as e:
        logger.warning("apify_profit_fetch_failed", extra={"error": str(e)})
        return {"configured": True, "error": str(e), "actors": []}


def _earnings_source() -> tuple[Any, str]:
    """Return (tracker, backend_name). Prefers EarningsTracker; falls back to
    PaymentAnalytics (which exposes the same method surface) on any failure."""
    try:
        from pry.payments.earnings import get_earnings_tracker

        return get_earnings_tracker(), "earnings_tracker"
    except Exception as e:  # noqa: BLE001 - defensive fallback
        logger.warning("earnings_tracker_unavailable", extra={"error": str(e)})
        from pry.payments.analytics import get_analytics

        return get_analytics(), "payment_analytics"


def _fmt_usd(v: Any) -> str:
    try:
        return f"${float(v):,.2f}"
    except (TypeError, ValueError):
        logger.warning("admin_shared_exception_handler", exc_info=True)
        return "$0.00"


# ── In-memory support issue tracker ──
# No persistent ticket model exists in the DB yet; this keeps a process-local
# registry so the admin panel can track and resolve customer issues. Restarting
# the API clears it (acceptable for now — unresolved payment counts are always
# recomputed from the payments log). [REVIEW] promote to a DB table if tickets
# need to survive restarts or span multiple workers.
