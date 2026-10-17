"""Tests for the Firecrawl-compatible async crawl-job surface.

Covers: polling a completed job (idempotent), cancelling a queued job,
unknown ids, and the per-URL errors endpoint. The job store is the real
``pry.core.deps.queue`` (JobQueue) with Redis forced off, so the tests
exercise the same code path the API uses — not a fake queue.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from pry.api.routers.scraping.crawl_jobs import router
from pry.core.deps import queue
from pry.core.jobqueue import JobQueue

PAGES: list[dict[str, Any]] = [
    {"url": "https://example.com/", "markdown": "# Home", "title": "Home", "method": "direct"},
    {"url": "https://example.com/missing", "status": "error", "error": "404", "method": "direct"},
]


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


async def _no_redis(_self: Any) -> None:
    """Force JobQueue onto its in-process fallback store."""
    return None


@pytest.fixture(autouse=True)
def local_job_store(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(JobQueue, "_get_redis", _no_redis)
    queue._redis = None  # type: ignore[attr-defined]


@pytest.fixture
def client() -> Iterator[TestClient]:
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as test_client:
        yield test_client


def _completed_job() -> str:
    job_id = _run(queue.create_job("crawl", {"url": "https://example.com/"}))
    _run(queue.complete_job(job_id, {"pages": PAGES}))
    return job_id


def test_poll_completed_job_is_idempotent(client: TestClient) -> None:
    job_id = _completed_job()

    first = client.get(f"/v1/crawl/{job_id}")
    assert first.status_code == 200
    body = first.json()
    assert body["id"] == job_id
    assert body["status"] == "completed"
    assert body["total"] == 2
    assert body["completed"] == 1
    assert body["data"] == [PAGES[0]]
    assert "error" not in body

    second = client.get(f"/v1/crawl/{job_id}")
    assert second.status_code == 200
    assert second.json() == body


def test_cancel_queued_job(client: TestClient) -> None:
    job_id = _run(queue.create_job("crawl", {"url": "https://example.com/"}))

    cancelled = client.delete(f"/v1/crawl/{job_id}")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    assert cancelled.json()["data"] == []

    stored = _run(queue.get_job(job_id))
    assert stored is not None
    assert stored["status"] == "cancelled"
    assert client.get(f"/v1/crawl/{job_id}").json()["status"] == "cancelled"


def test_cancel_is_sticky_after_late_completion(client: TestClient) -> None:
    job_id = _run(queue.create_job("crawl", {"url": "https://example.com/"}))
    assert client.delete(f"/v1/crawl/{job_id}").json()["status"] == "cancelled"

    # The in-flight task was not force-killed and finishes after the DELETE.
    _run(queue.complete_job(job_id, {"pages": PAGES}))

    body = client.get(f"/v1/crawl/{job_id}").json()
    assert body["status"] == "cancelled"
    assert body["total"] == 2


def test_cancel_completed_job_keeps_completed(client: TestClient) -> None:
    job_id = _completed_job()

    response = client.delete(f"/v1/crawl/{job_id}")

    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    assert response.json()["total"] == 2


@pytest.mark.parametrize("method", ["get", "delete"])
def test_unknown_job_returns_404(client: TestClient, method: str) -> None:
    response = getattr(client, method)("/v1/crawl/job_doesnotexist")

    assert response.status_code == 404
    assert response.json()["detail"] == "Crawl job not found"


def test_errors_endpoint_shape(client: TestClient) -> None:
    job_id = _completed_job()

    response = client.get(f"/v1/crawl/{job_id}/errors")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"id", "status", "count", "errors"}
    assert body["id"] == job_id
    assert body["status"] == "completed"
    assert body["count"] == 1
    assert body["errors"] == [PAGES[1]]
    assert set(body["errors"][0]) >= {"url", "error"}
