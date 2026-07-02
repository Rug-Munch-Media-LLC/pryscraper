"""Pry — Background job system using asyncio (built-in) or Celery if available.
Long-running jobs like crawls, monitors, and bulk imports should not block request threads."""
from paths import PRY_DATA_DIR

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

import asyncio
import json
import logging
import os
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Try Celery
try:
    from celery import Celery
    _has_celery = True
except ImportError:
    _has_celery = False

JOBS_DIR = PRY_DATA_DIR / "jobs"
JOBS_DIR.mkdir(parents=True, exist_ok=True)


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Job:
    """Represents a background job."""
    def __init__(self, job_id: str, name: str, func: Callable, args: tuple = (), kwargs: dict | None = None):
        self.id = job_id
        self.name = name
        self.func = func
        self.args = args
        self.kwargs = kwargs or {}
        self.status = JobStatus.PENDING
        self.created_at = datetime.now(UTC).isoformat()
        self.started_at = None
        self.completed_at = None
        self.result = None
        self.error = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "name": self.name, "status": self.status.value,
            "created_at": self.created_at, "started_at": self.started_at,
            "completed_at": self.completed_at, "result": self.result, "error": self.error,
        }


class JobQueue:
    """Async background job queue. Uses asyncio for in-process jobs.
    Falls back to Celery if installed and configured."""

    def __init__(self, max_workers: int = 4, use_celery: bool = False):
        self.max_workers = max_workers
        self.use_celery = use_celery and _has_celery
        self.jobs: dict[str, Job] = {}
        self._queue: asyncio.Queue = asyncio.Queue() if not self.use_celery else None
        self._workers: list[asyncio.Task] = []
        self._running = False

    async def submit(self, name: str, func: Callable, args: tuple = (), kwargs: dict | None = None) -> str:
        job_id = uuid.uuid4().hex[:12]
        job = Job(job_id, name, func, args, kwargs)
        self.jobs[job_id] = job
        if self._queue:
            await self._queue.put(job)
            if not self._running:
                await self.start()
        return job_id

    async def start(self) -> None:
        if self._running or self._queue is None: return
        self._running = True
        for i in range(self.max_workers):
            worker = asyncio.create_task(self._worker(f"worker-{i}"))
            self._workers.append(worker)

    async def _worker(self, name: str) -> None:
        while self._running:
            try:
                job = await asyncio.wait_for(self._queue.get(), timeout=1.0)
            except TimeoutError:
                continue
            await self._execute(job)

    async def _execute(self, job: Job) -> None:
        job.status = JobStatus.RUNNING
        job.started_at = datetime.now(UTC).isoformat()
        try:
            if asyncio.iscoroutinefunction(job.func):
                job.result = await job.func(*job.args, **job.kwargs)
            else:
                job.result = await asyncio.to_thread(job.func, *job.args, **job.kwargs)
            job.status = JobStatus.COMPLETED
        except Exception as e:  # noqa: BLE001
            job.error = str(e)[:500]
            job.status = JobStatus.FAILED
            logger.exception("job_failed", extra={"job_id": job.id, "error": str(e)})
        finally:
            job.completed_at = datetime.now(UTC).isoformat()
            # Persist
            try:
                path = JOBS_DIR / f"{job.id}.json"
                path.write_text(json.dumps(job.to_dict(), indent=2, default=str))
            except OSError:
                pass

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        job = self.jobs.get(job_id)
        return job.to_dict() if job else None

    def list_jobs(self, status: str = "", limit: int = 50) -> list[dict[str, Any]]:
        jobs = list(self.jobs.values())
        if status:
            jobs = [j for j in jobs if j.status.value == status]
        return [j.to_dict() for j in sorted(jobs, key=lambda j: j.created_at, reverse=True)[:limit]]

    async def stop(self) -> None:
        self._running = False
        for w in self._workers:
            w.cancel()
        self._workers.clear()


# Global queue
_queue: JobQueue | None = None


def get_queue() -> JobQueue:
    global _queue
    if _queue is None:
        _queue = JobQueue()
    return _queue
