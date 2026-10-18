"""Pry — batch job queue with Redis and webhook callbacks.
Async processing engine inspired by Firecrawl's webhook system."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

import asyncio
import hashlib
import hmac
import json
import logging
import random
import threading
import time
import uuid
from collections import OrderedDict
from datetime import UTC, datetime
from typing import Any

import httpx

from pry.core.settings import settings

logger = logging.getLogger(__name__)

# Results outlive the execution deadline: a crawl may legitimately run for
# minutes, and a poller must still be able to read the outcome afterwards.
# This TTL is independent of the per-job ``timeout`` (execution deadline).
RESULT_TTL_S = 7 * 24 * 60 * 60

# Redis index of in-flight jobs, scored by their execution deadline (epoch s).
# A sorted set keeps the reaper O(log n) and avoids a KEYS scan.
RUNNING_KEY = "pry:jobs:running"
DEAD_LETTER_KEY = "pry:webhook:deadletter"
DEAD_LETTER_MAX = 1000

LOCAL_MAX_JOBS = 512
WEBHOOK_ATTEMPTS = 3
WEBHOOK_BASE_DELAY_S = 0.5

_ACTIVE = frozenset({"pending", "running"})


def _deadline_ts(job: dict) -> float:
    """Return the job's execution deadline (epoch seconds), or +inf if unknown."""
    try:
        return float(job["deadline_ts"])
    except (KeyError, TypeError, ValueError):
        pass
    try:
        base = datetime.fromisoformat(str(job["created_at"])).timestamp()
    except (KeyError, TypeError, ValueError):
        return float("inf")
    try:
        return base + float(job.get("timeout") or 300)
    except (TypeError, ValueError):
        return float("inf")


class JobQueue:
    """Redis-backed async job queue for batch scrape/crawl operations.

    Features:
    - Job creation with unique ID
    - Status tracking (pending, running, completed, failed)
    - Webhook callbacks on completion (retry + dead-letter)
    - Separate execution deadline (``timeout``) and result TTL (``result_ttl_s``)
    - Stuck-job reaping so an overdue ``running`` job becomes ``failed``

    Note: jobs are addressed directly by ID via ``pry:job:<id>``. The legacy
    ``rpush("pry:queue", ...)`` registration was removed because nothing ever
    popped the list — it grew unbounded and served no consumer.
    """

    def __init__(
        self,
        redis_url: str = "redis://localhost:6379/0",
        *,
        result_ttl_s: int = RESULT_TTL_S,
        max_local_jobs: int = LOCAL_MAX_JOBS,
        webhook_attempts: int = WEBHOOK_ATTEMPTS,
        webhook_base_delay_s: float = WEBHOOK_BASE_DELAY_S,
    ):
        self.redis_url = redis_url
        self._redis = None
        self.result_ttl_s = int(result_ttl_s)
        self.max_local_jobs = int(max_local_jobs)
        self.webhook_attempts = max(1, int(webhook_attempts))
        self.webhook_base_delay_s = max(0.0, float(webhook_base_delay_s))
        # OrderedDict doubles as the LRU list for the local fallback store.
        self._local_jobs: OrderedDict[str, dict] = OrderedDict()
        self._dead_letters: list[dict] = []
        self._webhook_tasks: set[asyncio.Task] = set()
        # Serializes in-process job mutations. The local fallback store is
        # touched only in synchronous sections (never across an await), so a
        # plain threading.Lock is safe there. Redis read-modify-write must not
        # hold a threading.Lock across awaits in an asyncio loop (it would
        # deadlock the loop thread), so Redis RMW is serialized with an
        # asyncio.Lock instead.
        self._lock = threading.Lock()
        self._redis_lock = asyncio.Lock()

    async def _get_redis(self):
        if self._redis is None:
            import redis.asyncio as aioredis

            try:
                self._redis = await aioredis.from_url(self.redis_url, socket_timeout=3)
                await self._redis.ping()
            except (aioredis.RedisError, OSError, TimeoutError):
                logger.warning("jobqueue_redis_unavailable", exc_info=True)
                self._redis = None  # Fallback to local storage
        return self._redis

    def _sweep_local(self) -> None:
        """Evict expired and least-recently-used local jobs (call under lock)."""
        now = time.time()
        expired = [
            jid
            for jid, job in self._local_jobs.items()
            if job.get("_expires_at", float("inf")) <= now
        ]
        for jid in expired:
            self._local_jobs.pop(jid, None)
        while len(self._local_jobs) > self.max_local_jobs:
            self._local_jobs.popitem(last=False)

    async def create_job(
        self,
        job_type: str,
        payload: dict,
        webhook: str | None = None,
        timeout_s: int = 300,
    ) -> str:
        """Create a new job and return its ID."""
        job_id = f"job_{uuid.uuid4().hex[:16]}"
        now = datetime.now(UTC)
        job = {
            "id": job_id,
            "type": job_type,
            "payload": payload,
            "status": "pending",
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
            "deadline_ts": now.timestamp() + float(timeout_s),
            "webhook": webhook,
            "timeout": timeout_s,
            "result": None,
            "error": None,
        }
        redis = await self._get_redis()
        if redis:
            async with self._redis_lock:
                await redis.set(f"pry:job:{job_id}", json.dumps(job), ex=self.result_ttl_s)
                await redis.zadd(RUNNING_KEY, {job_id: job["deadline_ts"]})
        else:
            with self._lock:
                job["_expires_at"] = now.timestamp() + self.result_ttl_s
                self._local_jobs[job_id] = job
                self._sweep_local()
        return job_id

    async def get_job(self, job_id: str) -> dict | None:
        """Get job status and result (reaping it first if overdue)."""
        redis = await self._get_redis()
        if redis:
            async with self._redis_lock:
                data = await redis.get(f"pry:job:{job_id}")
            job = json.loads(data) if data else None
        else:
            with self._lock:
                self._sweep_local()
                stored = self._local_jobs.get(job_id)
                if stored is not None:
                    self._local_jobs.move_to_end(job_id)
                job = dict(stored) if stored else None
        if job and job.get("status") in _ACTIVE and _deadline_ts(job) <= time.time():
            job = await self._reap(job)
        return job

    async def update_job(self, job_id: str, **updates):
        """Update job fields and refresh the *result* TTL.

        The Redis path performs a read-modify-write; it is serialized with an
        asyncio.Lock so concurrent updates cannot clobber each other's changes
        (TOCTOU race). The local fallback path is guarded by a threading.Lock.
        """
        redis = await self._get_redis()
        now = datetime.now(UTC)
        if redis:
            async with self._redis_lock:
                data = await redis.get(f"pry:job:{job_id}")
                if data:
                    job = json.loads(data)
                    job.update(updates)
                    job["updated_at"] = now.isoformat()
                    await redis.set(f"pry:job:{job_id}", json.dumps(job), ex=self.result_ttl_s)
                    if job.get("status") in _ACTIVE:
                        await redis.zadd(RUNNING_KEY, {job_id: _deadline_ts(job)})
                    else:
                        await redis.zrem(RUNNING_KEY, job_id)
        else:
            with self._lock:
                self._sweep_local()
                if job_id in self._local_jobs:
                    job = self._local_jobs[job_id]
                    job.update(updates)
                    job["updated_at"] = now.isoformat()
                    job["_expires_at"] = now.timestamp() + self.result_ttl_s
                    self._local_jobs.move_to_end(job_id)

    async def _reap(self, job: dict, *, terminal_reason: str = "timeout") -> dict:
        """Fail an overdue job so a poller gets a terminal state, never a 404."""
        job_id = str(job.get("id"))
        error = f"execution deadline exceeded ({job.get('timeout', 300)}s)"
        logger.warning(
            "job_reaped",
            extra={"job_id": job_id, "status": job.get("status"), "reason": terminal_reason},
        )
        await self.update_job(job_id, status="failed", error=error, terminal_reason=terminal_reason)
        return await self.get_job(job_id) or {**job, "status": "failed", "error": error}

    async def reap_expired_jobs(self, limit: int = 100) -> int:
        """Sweep jobs past their execution deadline into ``failed``."""
        redis = await self._get_redis()
        reaped = 0
        if redis:
            async with self._redis_lock:
                overdue = await redis.zrangebyscore(
                    RUNNING_KEY, "-inf", time.time(), start=0, num=limit
                )
            for raw_id in overdue:
                job_id = raw_id.decode() if isinstance(raw_id, bytes) else str(raw_id)
                job = await self.get_job(job_id)
                if job and job.get("status") == "failed" and job.get("terminal_reason"):
                    reaped += 1
                elif job is None:
                    async with self._redis_lock:
                        await redis.zrem(RUNNING_KEY, job_id)
        else:
            with self._lock:
                ids = [
                    jid for jid, job in self._local_jobs.items() if _deadline_ts(job) <= time.time()
                ]
            for job_id in ids[:limit]:
                job = await self.get_job(job_id)
                if job and job.get("status") == "failed":
                    reaped += 1
        if reaped:
            logger.info("job_reaper_swept", extra={"reaped": reaped})
        return reaped

    async def complete_job(self, job_id: str, result: Any):
        """Mark job as completed and schedule the webhook (non-blocking)."""
        await self.update_job(job_id, status="completed", result=result)
        await self._schedule_webhook(job_id)

    async def fail_job(self, job_id: str, error: str):
        """Mark job as failed and schedule the webhook (non-blocking)."""
        await self.update_job(job_id, status="failed", error=error, terminal_reason="error")
        await self._schedule_webhook(job_id)

    async def _schedule_webhook(self, job_id: str) -> None:
        job = await self.get_job(job_id)
        url = str(job.get("webhook") or "") if job else ""
        if not url:
            return
        try:
            task = asyncio.create_task(self._fire_webhook(url, job))
        except RuntimeError:  # no running loop — nothing to schedule onto
            logger.warning("webhook_not_scheduled", extra={"job_id": job_id})
            return
        self._webhook_tasks.add(task)
        task.add_done_callback(self._webhook_tasks.discard)

    async def drain_webhooks(self) -> None:
        """Await in-flight webhook deliveries (shutdown / tests)."""
        tasks = list(self._webhook_tasks)
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _fire_webhook(self, url: str, job: dict) -> bool:
        """Deliver a webhook with retries, then dead-letter on exhaustion.

        The HMAC key comes from settings.webhook_secret (PRY_WEBHOOK_SECRET
        env / pry/webhook_secret in gopass — see settings.py), so a deployed
        secret is actually honored. Webhook verification requires a
        configured secret; with an empty secret the signature is unverifiable.
        """
        if not settings.webhook_secret:
            logger.warning(
                "webhook_secret_empty — job webhook signature is UNVERIFIABLE. "
                "Set PRY_WEBHOOK_SECRET in production."
            )
        signature = hmac.new(
            settings.webhook_secret.encode(), json.dumps(job).encode(), hashlib.sha256
        ).hexdigest()
        headers = {"X-Pry-Signature": signature, "Content-Type": "application/json"}
        job_id = str(job.get("id") or "")
        delay = self.webhook_base_delay_s
        async with httpx.AsyncClient(timeout=10) as client:
            for attempt in range(1, self.webhook_attempts + 1):
                try:
                    response = await client.post(url, json=job, headers=headers)
                    response.raise_for_status()
                    logger.info(
                        "webhook_delivered",
                        extra={
                            "job_id": job_id,
                            "url": url,
                            "attempt": attempt,
                            "status_code": response.status_code,
                        },
                    )
                    return True
                except (httpx.HTTPStatusError, httpx.RequestError, OSError) as exc:
                    status_code = getattr(getattr(exc, "response", None), "status_code", None)
                    logger.warning(
                        "webhook_attempt_failed",
                        extra={
                            "job_id": job_id,
                            "url": url,
                            "attempt": attempt,
                            "status_code": status_code,
                            "error": f"{type(exc).__name__}",
                        },
                    )
                    if attempt == self.webhook_attempts:
                        await self._dead_letter(url, job, exc)
                        return False
                    # Exponential backoff with jitter (up to +50%).
                    await asyncio.sleep(delay + random.uniform(0, delay * 0.5))  # noqa: S311
                    delay *= 2
        return False

    async def _dead_letter(self, url: str, job: dict, exc: Exception) -> None:
        """Persist an exhausted webhook delivery so it can be replayed."""
        record = {
            "job_id": job.get("id"),
            "url": url,
            "error": f"{type(exc).__name__}: {exc}",
            "created_at": datetime.now(UTC).isoformat(),
            "payload": job,
        }
        redis = await self._get_redis()
        if redis:
            async with self._redis_lock:
                await redis.rpush(DEAD_LETTER_KEY, json.dumps(record))
                await redis.ltrim(DEAD_LETTER_KEY, -DEAD_LETTER_MAX, -1)
        with self._lock:
            self._dead_letters.append(record)
            del self._dead_letters[:-DEAD_LETTER_MAX]
        logger.error("webhook_dead_lettered", extra={"job_id": record["job_id"], "url": url})

    async def get_dead_letters(self, limit: int = 50) -> list[dict]:
        """Return recent dead-lettered webhook deliveries (newest last)."""
        redis = await self._get_redis()
        if redis:
            async with self._redis_lock:
                raw = await redis.lrange(DEAD_LETTER_KEY, -limit, -1)
            return [json.loads(item) for item in raw]
        with self._lock:
            return list(self._dead_letters[-limit:])
