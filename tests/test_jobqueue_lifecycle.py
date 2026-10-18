"""Lifecycle tests for the job queue.

Covers the four failure modes this module exists to prevent:
results surviving past the execution deadline, overdue ``running`` jobs being
reaped to ``failed``, webhook retries with a dead letter after exhaustion, and
the local fallback store staying bounded.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC

from __future__ import annotations

import time
from typing import Any

import httpx
import pytest

from pry.core.jobqueue import JobQueue

HOOK = "https://hook.example.com/job"


async def _no_redis(_self: Any) -> None:
    """Force JobQueue onto its in-process fallback store."""
    return None


@pytest.fixture(autouse=True)
def _local_store(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(JobQueue, "_get_redis", _no_redis)


class _Response:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            request = httpx.Request("POST", HOOK)
            response = httpx.Response(self.status_code, request=request)
            raise httpx.HTTPStatusError(
                f"HTTP {self.status_code}", request=request, response=response
            )


class _FakeClient:
    """Minimal httpx.AsyncClient stand-in returning scripted status codes."""

    def __init__(self, statuses: list[int]) -> None:
        self._statuses = statuses
        self.calls = 0

    async def __aenter__(self) -> _FakeClient:
        return self

    async def __aexit__(self, *_exc: object) -> bool:
        return False

    async def post(self, *_args: Any, **_kwargs: Any) -> _Response:
        index = min(self.calls, len(self._statuses) - 1)
        self.calls += 1
        return _Response(self._statuses[index])


def _patch_client(monkeypatch: pytest.MonkeyPatch, statuses: list[int]) -> _FakeClient:
    client = _FakeClient(statuses)
    monkeypatch.setattr("pry.core.jobqueue.httpx.AsyncClient", lambda *_a, **_k: client)
    return client


async def test_result_survives_past_execution_deadline() -> None:
    q = JobQueue()
    job_id = await q.create_job("crawl", {"url": "https://example.com"}, timeout_s=1)
    await q.complete_job(job_id, {"pages": [{"url": "https://example.com"}]})

    # Execution deadline in the past; the result must still be readable.
    await q.update_job(job_id, deadline_ts=time.time() - 3600)

    job = await q.get_job(job_id)
    assert job is not None
    assert job["status"] == "completed"
    assert job["result"]["pages"]


async def test_expired_running_job_is_reaped_to_failed() -> None:
    q = JobQueue()
    job_id = await q.create_job("crawl", {"url": "https://example.com"}, timeout_s=1)
    await q.update_job(job_id, status="running", deadline_ts=time.time() - 5)

    job = await q.get_job(job_id)
    assert job is not None
    assert job["status"] == "failed"
    assert job["terminal_reason"] == "timeout"
    assert "deadline" in job["error"]


async def test_webhook_retried_on_500_then_delivered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _patch_client(monkeypatch, [500, 200])
    q = JobQueue(webhook_base_delay_s=0)
    job_id = await q.create_job("crawl", {}, webhook=HOOK)
    job = await q.get_job(job_id)
    assert job is not None

    assert await q._fire_webhook(HOOK, job) is True
    assert client.calls == 2
    assert await q.get_dead_letters() == []


async def test_webhook_dead_lettered_after_exhaustion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _patch_client(monkeypatch, [500])
    q = JobQueue(webhook_base_delay_s=0, webhook_attempts=3)
    job_id = await q.create_job("crawl", {}, webhook=HOOK)
    job = await q.get_job(job_id)
    assert job is not None

    assert await q._fire_webhook(HOOK, job) is False
    assert client.calls == 3
    letters = await q.get_dead_letters()
    assert len(letters) == 1
    assert letters[0]["job_id"] == job["id"]
    assert "HTTPStatusError" in letters[0]["error"]


async def test_completion_schedules_webhook_without_blocking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _patch_client(monkeypatch, [200])
    q = JobQueue(webhook_base_delay_s=0)
    job_id = await q.create_job("crawl", {}, webhook=HOOK)

    await q.complete_job(job_id, {"pages": []})
    await q.drain_webhooks()

    assert client.calls == 1
    assert (await q.get_job(job_id))["status"] == "completed"  # type: ignore[index]


async def test_local_store_is_bounded() -> None:
    q = JobQueue(max_local_jobs=3)
    job_ids = [await q.create_job("scrape", {"i": i}) for i in range(5)]

    assert len(q._local_jobs) == 3
    assert job_ids[0] not in q._local_jobs
    assert await q.get_job(job_ids[-1]) is not None


async def test_local_store_sweeps_expired_jobs() -> None:
    q = JobQueue(result_ttl_s=1)
    job_id = await q.create_job("scrape", {})
    q._local_jobs[job_id]["_expires_at"] = time.time() - 1

    assert await q.get_job(job_id) is None
    assert job_id not in q._local_jobs
