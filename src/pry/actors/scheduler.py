"""Pry — in-process monitor scheduler + run-claim control.

Started from the app lifespan (the monitoring router composes its lifespan);
importing this module starts nothing. Disable with ``PRY_SCHEDULER_ENABLED=0``
(default on, except under pytest). Tuning: PRY_SCHEDULER_INTERVAL_S,
PRY_SCHEDULER_CONCURRENCY, PRY_SCHEDULER_REDIS, PRY_MONITOR_MAX_ATTEMPTS,
PRY_MONITOR_RETRY_BACKOFF_S.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

import asyncio
import json
import logging
import os
import pathlib
import sys
import threading
import time
import uuid
from datetime import UTC, datetime
from typing import Any

from pry.core.db import Monitor, session_scope
from pry.core.deps import scraper as _scraper
from pry.core.paths import subdir

logger = logging.getLogger(__name__)

try:
    from prometheus_client import Counter, Gauge

    MONITOR_RUNS = Counter("pry_monitor_runs_total", "Monitor runs by status", ["status"])
    MONITOR_LAST_SUCCESS = Gauge(
        "pry_monitor_last_success_timestamp", "Last successful check", ["monitor"]
    )
    SCHEDULER_HEARTBEAT = Gauge("pry_scheduler_heartbeat", "Unix time of last tick")
except (ImportError, ValueError):  # pragma: no cover — prometheus optional
    MONITOR_RUNS = MONITOR_LAST_SUCCESS = SCHEDULER_HEARTBEAT = None


def record_run(status: str, monitor_id: str = "") -> None:
    if MONITOR_RUNS is None:
        return
    try:
        MONITOR_RUNS.labels(status=status).inc()
        if status in ("success", "changed") and monitor_id:
            MONITOR_LAST_SUCCESS.labels(monitor=monitor_id).set(time.time())
    except Exception:  # pragma: no cover
        logger.warning("monitor_metric_failed", exc_info=True)


def under_pytest() -> bool:
    return "pytest" in sys.modules or bool(os.getenv("PYTEST_CURRENT_TEST"))


def enabled() -> bool:
    raw = os.getenv("PRY_SCHEDULER_ENABLED", "").strip().lower()
    return (raw not in ("0", "false", "no", "off")) if raw else not under_pytest()


def _env_float(name: str, default: float, floor: float = 0.0) -> float:
    try:
        return max(floor, float(os.getenv(name, str(default))))
    except ValueError:
        return default


def interval_s() -> float:
    return _env_float("PRY_SCHEDULER_INTERVAL_S", 30.0, 1.0)


# ── Claims: row lock (SKIP LOCKED) → Redis SET NX PX → process lock ──
_LOCAL: dict[str, float] = {}
_LOCAL_LOCK = threading.Lock()
_DB_SESSIONS: dict[str, Any] = {}
_REDIS: Any = None
_REDIS_DEAD_UNTIL = 0.0


def _db_claim_sync(monitor_id: str, token: str) -> bool | None:
    """Hold a row lock for the life of the run; None = unsupported."""
    try:
        from sqlalchemy.orm import Session

        from pry.core.db.session import get_engine

        engine = get_engine()
        if not str(engine.url).startswith("postgresql"):
            return None
        sess = Session(bind=engine)
        row = (
            sess.query(Monitor)
            .filter(Monitor.monitor_id == monitor_id)
            .with_for_update(skip_locked=True)
            .first()
        )
        if row is None:
            sess.close()
            return False
        _DB_SESSIONS[token] = sess
        return True
    except Exception:  # noqa: BLE001 — any DB failure degrades to the next layer
        return None


def _redis_enabled() -> bool:
    raw = os.getenv("PRY_SCHEDULER_REDIS", "").strip().lower()
    return (raw not in ("0", "false", "no", "off")) if raw else not under_pytest()


async def _redis_claim(key: str, token: str, ttl_s: int) -> bool | None:
    global _REDIS, _REDIS_DEAD_UNTIL
    if not _redis_enabled() or time.time() < _REDIS_DEAD_UNTIL:
        return None
    try:
        if _REDIS is None:
            import redis.asyncio as aioredis

            _REDIS = aioredis.from_url(
                os.getenv("PRY_REDIS_URL", "redis://localhost:6379/0"),
                socket_connect_timeout=1,
                socket_timeout=1,
            )
        return bool(
            await _REDIS.set(f"pry:sched:{key}", token, nx=True, px=max(1000, ttl_s * 1000))
        )
    except Exception:  # noqa: BLE001 — Redis is an optional claim layer
        _REDIS_DEAD_UNTIL = time.time() + 60
        return None


def _local_claim(key: str, token: str, ttl_s: int) -> bool:
    now = time.monotonic()
    with _LOCAL_LOCK:
        if _LOCAL.get(key, 0) > now:
            return False
        _LOCAL[key] = now + ttl_s
        return True


async def claim_monitor(monitor_id: str, ttl_s: int = 900) -> str | None:
    """Claim a monitor exclusively. Returns a release token, or None if held."""
    token = uuid.uuid4().hex
    db = None if under_pytest() else await asyncio.to_thread(_db_claim_sync, monitor_id, token)
    if db is True:
        return "db:" + token
    if db is False:
        return None
    key = "monitor:" + monitor_id
    redis = await _redis_claim(key, token, ttl_s)
    if redis is True:
        return "redis:" + token
    if redis is False:
        return None
    return "local:" + token if _local_claim(key, token, ttl_s) else None


async def release_monitor(monitor_id: str, token: str | None) -> None:
    if not token:
        return
    kind, _, raw = token.partition(":")
    if kind == "local":
        with _LOCAL_LOCK:
            _LOCAL.pop("monitor:" + monitor_id, None)
    elif kind == "db" and (sess := _DB_SESSIONS.pop(raw, None)) is not None:
        await asyncio.to_thread(sess.close)
    elif kind == "redis" and _REDIS is not None:
        try:
            await _REDIS.delete(f"pry:sched:monitor:{monitor_id}")
        except Exception:
            logger.warning("scheduler_claim_release_failed", exc_info=True)


# ── Retry / dead-letter / exhaustion ──
def _dlq_path() -> Any:
    """Resolve at call time so PRY_DATA_DIR overrides apply (tests, deploys)."""
    base = os.getenv("PRY_DATA_DIR")
    root = pathlib.Path(base).expanduser().resolve() if base else subdir("monitor_dlq").parent
    path = root / "monitor_dlq" / "dead_letter.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def record_dead_letter(monitor_id: str, url: str, error: str, attempts: int) -> None:
    try:
        path = _dlq_path()
        with path.open("a") as fh:
            fh.write(
                json.dumps(
                    {
                        "monitor_id": monitor_id,
                        "url_host": url.split("//")[-1].split("/")[0],
                        "error": error[:500],
                        "attempts": attempts,
                        "ts": datetime.now(UTC).isoformat(),
                    }
                )
                + "\n"
            )
    except OSError:
        logger.warning("monitor_dead_letter_write_failed", exc_info=True)


def mark_exhausted(monitor_id: str) -> None:
    """Take a permanently failing monitor out of rotation (status -> error)."""
    try:
        with session_scope() as s:
            row = s.query(Monitor).filter(Monitor.monitor_id == monitor_id).first()
            if row is not None:
                row.active = False  # type: ignore[assignment]
    except Exception:
        logger.exception("monitor_mark_exhausted_failed", extra={"monitor_id": monitor_id})


async def scrape_with_retry(monitor_id: str, url: str) -> tuple[str | None, str | None]:
    """Scrape with exponential backoff. Returns (content, error)."""

    attempts = max(1, int(_env_float("PRY_MONITOR_MAX_ATTEMPTS", 3, 1)))
    backoff = _env_float("PRY_MONITOR_RETRY_BACKOFF_S", 0.5)
    last = "unknown error"
    for attempt in range(1, attempts + 1):
        try:
            result = await _scraper.scrape(url)
            return str(result.get("content", "")), None
        except Exception as exc:  # noqa: BLE001 — backends raise anything
            last = str(exc) or exc.__class__.__name__
            logger.warning(
                "monitor_scrape_failed",
                extra={"monitor_id": monitor_id, "attempt": attempt, "error": last[:200]},
            )
            if attempt < attempts:
                record_run("retry", monitor_id)
                await asyncio.sleep(backoff * (2 ** (attempt - 1)))
    record_run("error", monitor_id)
    await asyncio.to_thread(record_dead_letter, monitor_id, url, last, attempts)
    await asyncio.to_thread(mark_exhausted, monitor_id)
    return None, last


# ── Due selection + tick ──
def _due_monitors() -> list[str]:
    import croniter

    now = datetime.now(UTC)
    due: list[str] = []
    with session_scope() as s:
        for m in s.query(Monitor).filter(Monitor.active.is_(True)).limit(500).all():
            base = m.last_run_at or m.created_at or datetime.min.replace(tzinfo=UTC)
            if base.tzinfo is None:
                base = base.replace(tzinfo=UTC)
            try:
                nxt = croniter.croniter(m.schedule_cron or "0 */6 * * *", base).get_next(datetime)
            except (ValueError, KeyError):
                logger.warning("monitor_cron_invalid", extra={"monitor_id": m.monitor_id})
                continue
            if nxt.tzinfo is None:
                nxt = nxt.replace(tzinfo=UTC)
            if nxt <= now:
                due.append(str(m.monitor_id))
    return due


async def tick(timeout_s: float = 120.0) -> dict[str, Any]:
    """One pass: run due monitors with bounded concurrency and timeout."""
    if SCHEDULER_HEARTBEAT is not None:
        SCHEDULER_HEARTBEAT.set(time.time())
    from pry.actors.monitor import run_monitor

    due = await asyncio.to_thread(_due_monitors)
    sem = asyncio.Semaphore(int(_env_float("PRY_SCHEDULER_CONCURRENCY", 4, 1)))

    async def _one(monitor_id: str) -> dict[str, Any]:
        async with sem:
            try:
                return await asyncio.wait_for(run_monitor(monitor_id), timeout=timeout_s)
            except TimeoutError:
                record_run("timeout", monitor_id)
                logger.warning("monitor_tick_timeout", extra={"monitor_id": monitor_id})
                return {"monitor_id": monitor_id, "error": "timeout"}

    results = await asyncio.gather(*(_one(m) for m in due), return_exceptions=True)
    return {"due": len(due), "results": list(results)}


_scheduler_task: asyncio.Task[None] | None = None
_stop = asyncio.Event()


async def _loop() -> None:
    while not _stop.is_set():
        try:
            await tick()
        except Exception:
            logger.exception("scheduler_tick_failed")
        try:
            await asyncio.wait_for(_stop.wait(), timeout=interval_s())
        except TimeoutError:
            continue


async def start_scheduler() -> None:
    global _scheduler_task
    if not enabled():
        logger.info("scheduler_disabled", extra={"reason": "flag_or_pytest"})
        return
    if _scheduler_task is not None and not _scheduler_task.done():
        return
    _stop.clear()
    _scheduler_task = asyncio.create_task(_loop(), name="pry-monitor-scheduler")
    logger.info("scheduler_started", extra={"interval_s": interval_s()})


async def stop_scheduler() -> None:
    global _scheduler_task
    _stop.set()
    if _scheduler_task is not None:
        try:
            await asyncio.wait_for(_scheduler_task, timeout=5)
        except (TimeoutError, asyncio.CancelledError):
            _scheduler_task.cancel()
        _scheduler_task = None
    logger.info("scheduler_stopped")
