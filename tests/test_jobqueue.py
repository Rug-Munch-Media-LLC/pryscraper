# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
import pytest

from pry.core.jobqueue import JobQueue


@pytest.mark.asyncio
async def test_jobqueue_create_job_returns_id() -> None:
    q = JobQueue()
    job_id = await q.create_job("scrape", {"url": "https://example.com"})
    assert job_id.startswith("job_")


@pytest.mark.asyncio
async def test_jobqueue_get_job_exists() -> None:
    q = JobQueue()
    job_id = await q.create_job("scrape", {"url": "https://example.com"})
    job = await q.get_job(job_id)
    assert job is not None
    assert job["type"] == "scrape"
    assert job["status"] == "pending"


@pytest.mark.asyncio
async def test_jobqueue_get_job_missing() -> None:
    q = JobQueue()
    job = await q.get_job("nonexistent")
    assert job is None


@pytest.mark.asyncio
async def test_jobqueue_complete_job() -> None:
    q = JobQueue()
    job_id = await q.create_job("scrape", {"url": "https://example.com"})
    await q.complete_job(job_id, {"content": "test"})
    job = await q.get_job(job_id)
    assert job["status"] == "completed"
    assert job["result"]["content"] == "test"


@pytest.mark.asyncio
async def test_jobqueue_fail_job() -> None:
    q = JobQueue()
    job_id = await q.create_job("scrape", {"url": "https://example.com"})
    await q.fail_job(job_id, "network error")
    job = await q.get_job(job_id)
    assert job["status"] == "failed"
    assert "network" in job["error"]


@pytest.mark.asyncio
async def test_jobqueue_update_preserves_fields() -> None:
    q = JobQueue()
    job_id = await q.create_job(
        "crawl", {"url": "https://example.com"}, webhook="https://hook.example.com"
    )
    await q.update_job(job_id, status="running")
    job = await q.get_job(job_id)
    assert job["status"] == "running"
    assert job["webhook"] == "https://hook.example.com"
