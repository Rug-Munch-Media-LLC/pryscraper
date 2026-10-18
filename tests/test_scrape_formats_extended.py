"""Tests for the extended Firecrawl-parity scrape formats and async batch.

Covers ``formats: ["screenshot"]``, ``formats: ["pdf"]`` (renderer stubbed at
the scraper boundary — no browser is launched), the size caps, and the
queue-backed ``async``/``webhook`` batch path. Drives the real FastAPI app so
the assertions cover the shipped router logic.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC

from __future__ import annotations

import base64
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from pry.api.api import app
from pry.api.routers.scraping import batch_routes
from pry.api.routers.scraping.media_formats import MAX_PDF_BYTES, MAX_SCREENSHOT_BYTES

if TYPE_CHECKING:
    from collections.abc import Iterator

SCRAPING = "pry.api.routers.scraping.scraping"

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
PDF = b"%PDF-1.4\n%test\n"

RESULT: dict[str, Any] = {
    "status": "ok",
    "url": "https://example.com",
    "title": "Example",
    "description": "An example page",
    "content": "# Hello\n\nBody text.",
    "raw_html": "<html><body><p>Hello</p></body></html>",
    "method": "playwright",
    "markdown_quality": 0.9,
}


@pytest.fixture(autouse=True)
def bypass_x402_middleware() -> Iterator[None]:
    with patch(
        "pry.payments.x402_middleware.X402Middleware.__call__",
        lambda self, scope, receive, send: self.app(scope, receive, send),
    ):
        yield


@pytest.fixture(autouse=True)
def clear_response_cache() -> None:
    from pry.core.deps import cache as response_cache

    response_cache.clear()


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def media_scraper() -> Iterator[MagicMock]:
    scraper = MagicMock()
    scraper.scrape = AsyncMock(return_value=RESULT)
    scraper.render_media = AsyncMock(
        return_value={"screenshot": PNG, "pdf": PDF},
    )
    with patch(f"{SCRAPING}.scraper", scraper):
        yield scraper


class FakeQueue:
    """In-memory stand-in for ``JobQueue`` (same async surface)."""

    def __init__(self) -> None:
        self.jobs: dict[str, dict[str, Any]] = {}
        self.created: list[dict[str, Any]] = []

    async def create_job(
        self, job_type: str, payload: dict, webhook: str | None = None, timeout_s: int = 300
    ) -> str:
        job_id = f"job_{len(self.jobs) + 1}"
        self.jobs[job_id] = {
            "id": job_id,
            "type": job_type,
            "status": "pending",
            "payload": payload,
            "webhook": webhook,
            "result": None,
            "error": None,
        }
        self.created.append({"id": job_id, "webhook": webhook, "timeout_s": timeout_s})
        return job_id

    async def get_job(self, job_id: str) -> dict[str, Any] | None:
        return self.jobs.get(job_id)

    async def complete_job(self, job_id: str, result: Any) -> None:
        self.jobs[job_id].update(status="completed", result=result)

    async def fail_job(self, job_id: str, error: str) -> None:
        self.jobs[job_id].update(status="failed", error=error)


@pytest.fixture
def fake_queue() -> Iterator[FakeQueue]:
    queue = FakeQueue()
    with patch(f"{SCRAPING}.queue", queue):
        yield queue


def test_scrape_screenshot_returns_base64_png(client: TestClient, media_scraper: MagicMock) -> None:
    resp = client.post(
        "/v1/scrape",
        json={"url": "https://example.com", "formats": ["screenshot"]},
    )
    assert resp.status_code == 200, resp.text
    raw = base64.b64decode(resp.json()["data"]["screenshot"])
    assert raw.startswith(b"\x89PNG\r\n\x1a\n")
    assert "pdf" not in resp.json()["data"]
    media_scraper.render_media.assert_awaited_once()
    assert media_scraper.render_media.await_args.kwargs["want_screenshot"] is True


def test_scrape_pdf_returns_pdf_bytes(client: TestClient, media_scraper: MagicMock) -> None:
    resp = client.post("/v1/scrape", json={"url": "https://example.com", "formats": ["pdf"]})
    assert resp.status_code == 200, resp.text
    raw = base64.b64decode(resp.json()["data"]["pdf"])
    assert raw.startswith(b"%PDF")
    assert "screenshot" not in resp.json()["data"]


def test_scrape_oversize_screenshot_rejected(client: TestClient, media_scraper: MagicMock) -> None:
    media_scraper.render_media = AsyncMock(
        return_value={"screenshot": b"x" * (MAX_SCREENSHOT_BYTES + 1)},
    )
    resp = client.post(
        "/v1/scrape",
        json={"url": "https://example.com", "formats": ["screenshot"]},
    )
    assert resp.status_code == 422


def test_scrape_oversize_pdf_rejected(client: TestClient, media_scraper: MagicMock) -> None:
    media_scraper.render_media = AsyncMock(return_value={"pdf": b"x" * (MAX_PDF_BYTES + 1)})
    resp = client.post("/v1/scrape", json={"url": "https://example.com", "formats": ["pdf"]})
    assert resp.status_code == 422


def test_scrape_without_media_does_not_render(client: TestClient, media_scraper: MagicMock) -> None:
    resp = client.post("/v1/scrape", json={"url": "https://example.com"})
    assert resp.status_code == 200
    media_scraper.render_media.assert_not_awaited()


def test_sync_batch_unchanged(client: TestClient, fake_queue: FakeQueue) -> None:
    scraper = MagicMock()
    scraper.scrape = AsyncMock(return_value=RESULT)
    with patch(f"{SCRAPING}.scraper", scraper):
        resp = client.post("/v1/batch", json=["https://example.com/1", "https://example.com/2"])
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["total"] == 2
    assert fake_queue.jobs == {}


def test_async_batch_returns_job_id(client: TestClient, fake_queue: FakeQueue) -> None:
    scraper = MagicMock()
    scraper.scrape = AsyncMock(return_value=RESULT)
    with patch(f"{SCRAPING}.scraper", scraper):
        resp = client.post(
            "/v1/batch",
            json={
                "urls": ["https://example.com/1"],
                "async": True,
                "webhook": "https://hooks.example.com/pry",
            },
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    assert body["id"] == "job_1"
    # TestClient may drain the created task before the response returns.
    assert fake_queue.jobs["job_1"]["status"] in {"pending", "completed"}
    assert fake_queue.created[0]["webhook"] == "https://hooks.example.com/pry"


@pytest.mark.asyncio
async def test_async_batch_job_completes(client: TestClient, fake_queue: FakeQueue) -> None:
    scraper = MagicMock()
    scraper.scrape = AsyncMock(return_value=RESULT)
    job_id = await fake_queue.create_job(
        "batch", {"urls": ["https://example.com/1", "https://example.com/2"]}
    )
    with patch(f"{SCRAPING}.scraper", scraper):
        await batch_routes._run_batch_job(
            job_id, ["https://example.com/1", "https://example.com/2"], 30
        )
    resp = client.get(f"/v1/batch/{job_id}")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "completed"
    assert body["total"] == 2
    assert body["completed"] == 2
    assert fake_queue.jobs[job_id]["status"] == "completed"


def test_unknown_batch_job_404(client: TestClient, fake_queue: FakeQueue) -> None:
    assert client.get("/v1/batch/job_missing").status_code == 404


@pytest.mark.asyncio
async def test_render_media_for_delegates_to_engine_hook() -> None:
    """``PryScraper`` has no hook; the service delegates to one UltimateScraper."""
    from pry.engine import scraping_service

    class Engine:
        async def render_media(self, url: str, **kwargs: Any) -> dict[str, Any]:
            assert url == "https://example.com"
            assert kwargs == {"want_screenshot": True, "want_pdf": False, "timeout_s": 5}
            return {"screenshot": PNG}

    previous = scraping_service._media_engine
    scraping_service._media_engine = Engine()
    try:
        out = await scraping_service.render_media_for(
            object(),
            "https://example.com",
            want_screenshot=True,
            want_pdf=False,
            timeout_s=5,
        )
    finally:
        scraping_service._media_engine = previous
    assert out == {"screenshot": PNG}
