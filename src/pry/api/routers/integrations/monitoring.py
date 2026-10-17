"""Pry — Monitoring router (remaining api.py routes).

Auto-extracted from api.py during the router-split refactor.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Body

from pry.core.errors import NotFoundError

logger = logging.getLogger(__name__)


@asynccontextmanager
async def _monitor_lifespan(_app: Any):
    """Start the in-process monitor scheduler with the app; stop on shutdown."""
    from pry.actors.scheduler import start_scheduler, stop_scheduler

    await start_scheduler()
    try:
        yield
    finally:
        await stop_scheduler()


router = APIRouter(tags=["Monitoring"], lifespan=_monitor_lifespan)


@router.post("/v1/monitor", tags=["Monitoring"], summary="Create a scheduled content monitor")
async def create_monitor_endpoint(
    name: str = Body(...),
    url: str = Body(...),
    schedule_cron: str = Body("0 */6 * * *"),
    goal: str = Body(""),
    webhook: str = Body(""),
    use_llm: bool = Body(False),
) -> dict[str, Any]:
    """Create a scheduled monitor that tracks content changes.

    Args:
        name: Human-readable monitor name
        url: Target URL to monitor
        schedule_cron: Cron expression (default: every 6 hours)
        goal: Natural language goal for meaningful-change detection
        webhook: URL to notify on meaningful changes
        use_llm: Use LLM for change judging (slower but smarter)
    """
    from pry.actors.monitor import create_monitor

    monitor = await create_monitor(name, url, schedule_cron, goal, webhook, use_llm)
    return {"success": True, "data": monitor}


@router.post("/v1/monitor/run", tags=["Monitoring"], summary="Run a single monitor check")
async def run_monitor_endpoint(
    monitor_id: str = Body(...),
) -> dict[str, Any]:
    """Execute a monitor check immediately (outside of schedule)."""
    from pry.actors.monitor import run_monitor

    result = await run_monitor(monitor_id)
    if "error" in result:
        raise NotFoundError(result["error"])
    return {"success": True, "data": result}


@router.get("/v1/monitors", tags=["Monitoring"], summary="List all monitors")
async def list_monitors_endpoint() -> dict[str, Any]:
    """List all registered monitors."""
    from pry.actors.monitor import list_monitors

    monitors = await list_monitors()
    return {"success": True, "data": {"monitors": monitors, "total": len(monitors)}}


@router.delete("/v1/monitor/{monitor_id}", tags=["Monitoring"], summary="Delete a monitor")
async def delete_monitor_endpoint(monitor_id: str) -> dict[str, Any]:
    """Delete a monitor and its snapshots."""
    from pry.actors.monitor import delete_monitor

    success = await delete_monitor(monitor_id)
    if not success:
        raise NotFoundError(f"Monitor not found: {monitor_id}")
    return {"success": True, "data": {"monitor_id": monitor_id, "deleted": True}}


@router.post("/v1/monitor/check", tags=["Monitoring"], summary="Run all due monitors")
async def run_due_monitors() -> dict[str, Any]:
    """Run due monitors with bounded concurrency, a per-monitor timeout and
    per-monitor failure reporting (never a serial sweep of up to 500)."""
    import croniter

    from pry.actors.monitor import list_monitors, run_monitor

    monitors = await list_monitors()
    now = datetime.now(UTC)
    due = []
    for m in monitors:
        if m.get("status") != "active":
            continue
        last_run = m.get("last_run_at")
        last_dt = datetime.fromisoformat(last_run) if last_run else datetime.min.replace(tzinfo=UTC)
        try:
            nxt = croniter.croniter(m["schedule_cron"], last_dt).get_next(datetime)
            if nxt.tzinfo is None:
                nxt = nxt.replace(tzinfo=UTC)
            if nxt <= now:
                due.append(m["id"])
        except Exception as e:  # noqa: BLE001 — bad cron must not abort the sweep
            logger.warning(
                "monitor_schedule_check_failed", extra={"monitor_id": m["id"], "error": str(e)}
            )

    concurrency = max(1, int(os.getenv("PRY_MONITOR_SWEEP_CONCURRENCY", "5")))
    timeout_s = float(os.getenv("PRY_MONITOR_SWEEP_TIMEOUT_S", "120"))
    sem = asyncio.Semaphore(concurrency)

    async def _one(monitor_id: str) -> dict[str, Any]:
        async with sem:
            try:
                return await asyncio.wait_for(run_monitor(monitor_id), timeout=timeout_s)
            except TimeoutError:
                logger.warning("monitor_sweep_timeout", extra={"monitor_id": monitor_id})
                return {"monitor_id": monitor_id, "error": "timeout"}

    gathered = await asyncio.gather(*(_one(mid) for mid in due), return_exceptions=True)
    results: list[dict[str, Any]] = [
        r if isinstance(r, dict) else {"error": repr(r)} for r in gathered
    ]
    failures = [r for r in results if "error" in r]

    return {
        "success": True,
        "data": {
            "total_monitors": len(monitors),
            "due_count": len(due),
            "ran_count": len(results),
            "failures": failures,
            "results": results,
        },
    }
