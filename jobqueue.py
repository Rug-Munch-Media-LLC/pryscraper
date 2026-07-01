"""Pry — batch job queue with Redis and webhook callbacks.
Async processing engine inspired by Firecrawl's webhook system."""

import hashlib
import hmac
import json
import uuid
from datetime import datetime
from typing import Any

import httpx


class JobQueue:
    """Redis-backed async job queue for batch scrape/crawl operations.

    Features:
    - Job creation with unique ID
    - Status tracking (pending, running, completed, failed)
    - Webhook callbacks on completion
    - Job timeout and cleanup
    """

    def __init__(self, redis_url: str = "redis://localhost:6379/0"):
        self.redis_url = redis_url
        self._redis = None
        self._local_jobs: dict[str, dict] = {}

    async def _get_redis(self):
        if self._redis is None:
            import redis.asyncio as aioredis

            try:
                self._redis = await aioredis.from_url(self.redis_url, socket_timeout=3)
                await self._redis.ping()
            except:
                self._redis = None  # Fallback to local storage
        return self._redis

    async def create_job(
        self, job_type: str, payload: dict, webhook: str | None = None, timeout: int = 300
    ) -> str:
        """Create a new job and return its ID."""
        job_id = f"job_{uuid.uuid4().hex[:16]}"
        job = {
            "id": job_id,
            "type": job_type,
            "payload": payload,
            "status": "pending",
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat(),
            "webhook": webhook,
            "timeout": timeout,
            "result": None,
            "error": None,
        }
        redis = await self._get_redis()
        if redis:
            await redis.set(f"pry:job:{job_id}", json.dumps(job), ex=timeout + 60)
            await redis.rpush("pry:queue", job_id)
        else:
            self._local_jobs[job_id] = job
        return job_id

    async def get_job(self, job_id: str) -> dict | None:
        """Get job status and result."""
        redis = await self._get_redis()
        if redis:
            data = await redis.get(f"pry:job:{job_id}")
            return json.loads(data) if data else None
        return self._local_jobs.get(job_id)

    async def update_job(self, job_id: str, **updates):
        """Update job fields."""
        redis = await self._get_redis()
        if redis:
            data = await redis.get(f"pry:job:{job_id}")
            if data:
                job = json.loads(data)
                job.update(updates)
                job["updated_at"] = datetime.utcnow().isoformat()
                await redis.set(
                    f"pry:job:{job_id}", json.dumps(job), ex=job.get("timeout", 300) + 60
                )
        elif job_id in self._local_jobs:
            self._local_jobs[job_id].update(updates)
            self._local_jobs[job_id]["updated_at"] = datetime.utcnow().isoformat()

    async def complete_job(self, job_id: str, result: Any):
        """Mark job as completed and fire webhook."""
        await self.update_job(job_id, status="completed", result=result)
        job = await self.get_job(job_id)
        if job and job.get("webhook"):
            await self._fire_webhook(job["webhook"], job)

    async def fail_job(self, job_id: str, error: str):
        """Mark job as failed and fire webhook."""
        await self.update_job(job_id, status="failed", error=error)
        job = await self.get_job(job_id)
        if job and job.get("webhook"):
            await self._fire_webhook(job["webhook"], job)

    async def _fire_webhook(self, url: str, job: dict):
        """Fire webhook callback with job result."""
        try:
            signature = hmac.new(
                b"pry-webhook-secret", json.dumps(job).encode(), hashlib.sha256
            ).hexdigest()
            async with httpx.AsyncClient(timeout=10) as client:
                await client.post(
                    url,
                    json=job,
                    headers={
                        "X-Pry-Signature": signature,
                        "Content-Type": "application/json",
                    },
                )
        except:
            pass  # Webhook fire is best-effort
