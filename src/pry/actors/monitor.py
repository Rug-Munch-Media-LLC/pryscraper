"""Pry — scheduled monitors with AI change detection.
Cron-based monitors that diff content and judge meaningful changes."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
import asyncio
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from pry.actors.change_judger import ChangeJudger, _compute_diff
from pry.actors.scheduler import (
    claim_monitor,
    record_run,
    release_monitor,
    scrape_with_retry,
)
from pry.core.db import Monitor, MonitorRun, session_scope

logger = logging.getLogger(__name__)


def _default(value: Any, fallback: Any) -> Any:
    return value if value is not None else fallback


def _iso(value: Any) -> str:
    return value.isoformat() if value else ""


def _monitor_to_dict(m: Monitor, last_run_status: str | None = None) -> dict[str, Any]:
    status = "active" if m.active else ("error" if last_run_status == "error" else "inactive")
    return {
        "id": m.monitor_id,
        "name": m.monitor_name,
        "target_url": m.url,
        "schedule_cron": m.schedule_cron,
        "goal": _default(m.goal, ""),
        "webhook_url": _default(m.webhook_url, ""),
        "use_llm_judge": bool(m.use_llm_judge),
        "status": status,
        "created_at": _iso(m.created_at),
        "last_run_at": _iso(m.last_run_at) or None,
        "current_version": _default(m.current_version, 0),
        "last_content": _default(m.last_content, ""),
        "total_checks": _default(m.total_checks, 0),
        "total_changes": _default(m.total_changes, 0),
    }


async def create_monitor(
    name: str,
    target_url: str,
    schedule_cron: str = "0 */6 * * *",
    goal: str = "",
    webhook_url: str = "",
    **flags: Any,
) -> dict[str, Any]:
    use_llm_judge = bool(flags.get("use_llm_judge", False))
    monitor_id = uuid.uuid4().hex[:12]
    now = datetime.now(UTC)
    monitor = Monitor(
        monitor_id=monitor_id,
        url=target_url,
        monitor_name=name,
        schedule_cron=schedule_cron,
        goal=goal,
        use_llm_judge=use_llm_judge,
        active=True,
        webhook_url=webhook_url,
        created_at=now,
        current_version=0,
        last_content="",
        total_checks=0,
        total_changes=0,
    )
    try:
        with session_scope() as s:
            s.add(monitor)
        logger.info("monitor_created", extra={"monitor_id": monitor_id, "monitor_name": name})
        return _monitor_to_dict(monitor)
    except Exception:
        logger.exception("monitor_creation_failed", extra={"monitor_name": name})
        raise


def _load_monitor(monitor_id: str) -> dict[str, Any] | None:
    """Read a monitor row into a plain dict. Runs in a worker thread.

    The session is opened, used, and closed entirely within this call — no
    sync connection is ever held across an ``await`` on the event loop.
    """
    with session_scope() as s:
        monitor = s.query(Monitor).filter(Monitor.monitor_id == monitor_id).first()
        if not monitor:
            return None
        return {
            "name": str(monitor.monitor_name),
            "url": str(monitor.url),
            "previous_content": str(monitor.last_content or ""),
            "use_llm_judge": bool(monitor.use_llm_judge),
            "goal": str(monitor.goal or ""),
            "webhook_url": str(monitor.webhook_url or ""),
        }


def _record_error_run(monitor_id: str, error: str, ts: datetime) -> None:
    """Persist a failed MonitorRun. Runs in a worker thread."""
    with session_scope() as s:
        s.add(
            MonitorRun(
                monitor_id=monitor_id,
                ts=ts,
                status="error",
                error=error,
            )
        )


def _persist_run(
    monitor_id: str,
    previous_content: str,
    current_content: str,
    judgment: dict[str, Any],
) -> dict[str, Any]:
    """Apply the post-scrape state to the monitor row and record the run.

    Runs entirely in a worker thread — re-opens its own session so no sync
    connection crosses an ``await`` boundary on the event loop.
    """
    with session_scope() as s:
        monitor = s.query(Monitor).filter(Monitor.monitor_id == monitor_id).first()
        if not monitor:
            return {"error": f"Monitor not found: {monitor_id}"}

        changed = bool(previous_content) and current_content != previous_content
        now = datetime.now(UTC)
        monitor.last_run_at = now  # type: ignore[assignment]  # SQLAlchemy Column[datetime] → datetime
        monitor.total_checks = (monitor.total_checks or 0) + 1  # type: ignore[assignment]

        run_status = "success"
        diff_data: dict[str, Any] = {}
        if changed:
            monitor.total_changes = (monitor.total_changes or 0) + 1  # type: ignore[assignment]
            monitor.current_version = (monitor.current_version or 0) + 1  # type: ignore[assignment]
            run_status = "changed"
            diff_data = {
                "previous_length": len(previous_content),
                "current_length": len(current_content),
                "diff": _compute_diff(previous_content, current_content),
            }

        monitor.last_content = current_content  # type: ignore[assignment]

        s.add(
            MonitorRun(
                monitor_id=monitor_id,
                ts=now,
                status=run_status,
                diff=diff_data,
            )
        )

        return {
            "monitor_id": monitor_id,
            "name": str(monitor.monitor_name),
            "changed": changed,
            "previous_content_length": len(previous_content),
            "current_content_length": len(current_content),
            "judgment": judgment,
            "total_checks": monitor.total_checks,
            "total_changes": monitor.total_changes,
        }


async def run_monitor(monitor_id: str) -> dict[str, Any]:
    """Run one monitor check, holding a cross-process claim for its duration.

    Concurrent calls for the same monitor return ``skipped`` — the claim is
    what prevents duplicate MonitorRun rows, doubled counters and webhooks.
    """
    token = await claim_monitor(monitor_id)
    if token is None:
        logger.info("monitor_run_skipped_locked", extra={"monitor_id": monitor_id})
        return {"monitor_id": monitor_id, "skipped": True, "reason": "already_running"}
    try:
        loaded = await asyncio.to_thread(_load_monitor, monitor_id)
        if loaded is None:
            return {"error": f"Monitor not found: {monitor_id}"}

        previous_content = loaded["previous_content"]
        current_content, scrape_error = await scrape_with_retry(monitor_id, loaded["url"])
        if scrape_error is not None or current_content is None:
            # scrape_with_retry retried with backoff, wrote the dead-letter
            # record and marked the monitor exhausted (active=False ->
            # surfaced as status "error" by list_monitors()).
            await asyncio.to_thread(
                _record_error_run,
                monitor_id,
                scrape_error or "scrape returned no content",
                datetime.now(UTC),
            )
            return {"monitor_id": monitor_id, "error": f"Scrape failed: {scrape_error}"}

        judger = ChangeJudger(use_llm=loaded["use_llm_judge"])
        judgment = await judger.judge(previous_content, current_content, loaded["goal"])

        result = await asyncio.to_thread(
            _persist_run, monitor_id, previous_content, current_content, judgment
        )
        record_run("changed" if result.get("changed") else "success", monitor_id)

        if judgment["meaningful"] and loaded["webhook_url"]:
            await _fire_webhook(loaded["webhook_url"], result)

        return result
    except Exception:
        record_run("error", monitor_id)
        logger.exception("monitor_run_failed", extra={"monitor_id": monitor_id})
        return {"error": f"Monitor run failed: {monitor_id}"}
    finally:
        await release_monitor(monitor_id, token)


async def _fire_webhook(webhook_url: str, payload: dict[str, Any]) -> None:
    """Deliver via WebhookDelivery: SSRF-validated, HMAC-signed, retried, DLQ'd."""
    from urllib.parse import urlparse

    from pry.api.webhook_delivery import WebhookDelivery

    host = urlparse(webhook_url).hostname or "invalid"
    result = await WebhookDelivery().deliver(webhook_url, payload, event_type="monitor.change")
    if result.get("success"):
        logger.info("monitor_webhook_fired", extra={"webhook_host": host})
    else:
        logger.warning(
            "monitor_webhook_failed",
            extra={"webhook_host": host, "error": result.get("error")},
        )


async def list_monitors() -> list[dict[str, Any]]:
    try:
        with session_scope() as s:
            monitors = s.query(Monitor).order_by(Monitor.created_at.desc()).limit(500).all()
            # Latest run status per monitor so an exhausted monitor surfaces
            # as "error" rather than silently vanishing (active=False).
            latest: dict[str, str] = {}
            for mid, status in (
                s.query(MonitorRun.monitor_id, MonitorRun.status)
                .order_by(MonitorRun.id.desc())
                .limit(5000)
                .all()
            ):
                latest.setdefault(mid, status)
            return [_monitor_to_dict(m, latest.get(m.monitor_id)) for m in monitors]
    except Exception:
        logger.exception("monitor_list_failed")
        return []


async def delete_monitor(monitor_id: str) -> bool:
    try:
        with session_scope() as s:
            monitor = s.query(Monitor).filter(Monitor.monitor_id == monitor_id).first()
            if not monitor:
                return False
            s.delete(monitor)
        logger.info("monitor_deleted", extra={"monitor_id": monitor_id})
        return True
    except Exception:
        logger.exception("monitor_delete_failed", extra={"monitor_id": monitor_id})
        return False
