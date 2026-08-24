"""Pry Python SDK — simple client library.
Usage:
    from pry.api.pry_sdk import PryCrawl
    mc = PryCrawl("http://localhost:8002")
    result = await mc.scrape("https://example.com")
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

import asyncio
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_LOOP: asyncio.AbstractEventLoop | None = None


def _get_or_create_loop() -> asyncio.AbstractEventLoop:
    """Get the running event loop or create a persistent one for sync use."""
    global _LOOP
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        if _LOOP is None or _LOOP.is_closed():
            _LOOP = asyncio.new_event_loop()
            asyncio.set_event_loop(_LOOP)
        return _LOOP


class PryCrawl:
    """Python SDK for Pry API."""

    def __init__(
        self, base_url: str = "http://localhost:8002", api_key: str | None = None, timeout: int = 60
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._headers = {"Content-Type": "application/json"}
        if api_key:
            self._headers["Authorization"] = f"Bearer {api_key}"

    async def _post(self, path: str, data: dict[str, Any]) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self.timeout, headers=self._headers) as client:
            resp = await client.post(f"{self.base_url}{path}", json=data)
            resp.raise_for_status()
            result: dict[str, Any] = resp.json()
            return result

    async def scrape(self, url: str, **options: Any) -> dict[str, Any]:
        """Scrape a single URL to markdown."""
        return await self._post("/v1/scrape", {"url": url, **options})

    async def scrape_json(self, url: str, schema: dict[str, str], **options: Any) -> dict[str, Any]:
        """Scrape with structured JSON extraction."""
        return await self._post(
            "/v1/scrape", {"url": url, "formats": ["json"], "jsonSchema": schema, **options}
        )

    async def crawl(self, url: str, max_pages: int = 10, **options: Any) -> dict[str, Any]:
        """Crawl multiple pages from a URL."""
        return await self._post("/v1/crawl", {"url": url, "maxPages": max_pages, **options})

    async def map(self, url: str, limit: int = 50) -> dict[str, Any]:
        """Discover URLs on a site."""
        return await self._post("/v1/map", {"url": url, "limit": limit})

    async def parse(self, url: str) -> dict[str, Any]:
        """Parse a document (PDF, DOCX, image)."""
        return await self._post("/v1/parse", {"url": url})

    async def automate(self, steps: list[dict[str, Any]], **options: Any) -> dict[str, Any]:
        """Run browser automation steps."""
        return await self._post("/v1/automate", {"steps": steps, **options})

    async def screenshot(self, url: str) -> dict[str, Any]:
        """Take a screenshot of a URL."""
        return await self._post("/v1/screenshot", {"url": url})

    async def health(self) -> dict[str, Any]:
        """Check service health."""
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{self.base_url}/health")
            result: dict[str, Any] = resp.json()
            return result


class PryCrawlSync:
    """Synchronous wrapper for Pry SDK."""

    def __init__(
        self, base_url: str = "http://localhost:8002", api_key: str | None = None, timeout: int = 60
    ):
        self._client = PryCrawl(base_url, api_key, timeout)

    def _run(self, coro: Any) -> Any:
        loop = _get_or_create_loop()
        return loop.run_until_complete(coro)

    def scrape(self, url: str, **options: Any) -> dict[str, Any]:
        result: dict[str, Any] = self._run(self._client.scrape(url, **options))
        return result

    def scrape_json(self, url: str, schema: dict[str, str], **options: Any) -> dict[str, Any]:
        result: dict[str, Any] = self._run(self._client.scrape_json(url, schema, **options))
        return result

    def crawl(self, url: str, max_pages: int = 10, **options: Any) -> dict[str, Any]:
        result: dict[str, Any] = self._run(self._client.crawl(url, max_pages, **options))
        return result

    def map(self, url: str, limit: int = 50) -> dict[str, Any]:
        result: dict[str, Any] = self._run(self._client.map(url, limit))
        return result

    def parse(self, url: str) -> dict[str, Any]:
        result: dict[str, Any] = self._run(self._client.parse(url))
        return result

    def automate(self, steps: list[dict[str, Any]], **options: Any) -> dict[str, Any]:
        result: dict[str, Any] = self._run(self._client.automate(steps, **options))
        return result

    def screenshot(self, url: str) -> dict[str, Any]:
        result: dict[str, Any] = self._run(self._client.screenshot(url))
        return result

    def health(self) -> dict[str, Any]:
        result: dict[str, Any] = self._run(self._client.health())
        return result
