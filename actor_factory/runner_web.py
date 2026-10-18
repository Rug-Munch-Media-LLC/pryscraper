"""Pry - Apify Actor Factory: browser/document runtime.

Extends the shared PPE runner with the capabilities the specialised
screenshot and document actors actually advertise:

- ``screenshot`` - renders the page with Playwright/Chromium and puts the
  PNG (base64) plus its byte size in the dataset item. If Playwright is not
  available the item fails honestly with ``screenshot_unavailable``.
- ``pdfdoc`` - fetches the URL, extracts PDF text/tables with Pry's
  PDFTableExtractor and records the parser method. Non-PDF responses keep
  the generic scrape output and are labelled ``document_type=html``.

No capability is simulated: every failure path returns an explicit error.

Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import asyncio
import base64
from datetime import UTC, datetime
from typing import Any

from actor_factory.runner import PPEScraperRunner


class WebCapabilityRunner(PPEScraperRunner):
    """PPE runner with real screenshot and PDF-document handling."""

    async def process_url(self, url: str, options: dict[str, Any]) -> dict[str, Any]:
        if self.config.processor_name == "screenshot":
            return await self._capture_screenshot(url, options)
        if self.config.processor_name == "pdfdoc":
            return await self._parse_document(url, options)
        return await super().process_url(url, options)

    async def _capture_screenshot(self, url: str, options: dict[str, Any]) -> dict[str, Any]:
        item: dict[str, Any] = {
            "url": url,
            "status": "error",
            "method": "playwright",
            "scraped_at": datetime.now(UTC).isoformat(),
        }
        width = int(options.get("viewport_width", 1280) or 1280)
        full_page = bool(options.get("full_page", True))
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            item["error"] = "screenshot_unavailable: playwright not installed"
            return item
        try:
            async with async_playwright() as pw:
                browser = await pw.chromium.launch(args=["--no-sandbox"])
                try:
                    page = await browser.new_page(viewport={"width": width, "height": 720})
                    await page.goto(url, wait_until="domcontentloaded", timeout=45_000)
                    png = await page.screenshot(full_page=full_page)
                finally:
                    await browser.close()
        except Exception as exc:  # noqa: BLE001 - one bad target must not kill the run
            item["error"] = f"screenshot_failed: {str(exc)[:120]}"
            return item
        item["status"] = "ok"
        item["screenshot_base64"] = base64.b64encode(png).decode("ascii")
        item["screenshot_bytes"] = len(png)
        item["metadata"] = {
            "domain": url.split("/")[2] if "://" in url else url,
            "content_length": len(png),
        }
        return item

    async def _fetch(self, url: str) -> Any:
        import httpx

        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
            return await client.get(url)

    async def _pdf_item(self, url: str, body: bytes) -> dict[str, Any]:
        from pry.engine.pdf_extractor import PDFTableExtractor

        parsed = await asyncio.to_thread(PDFTableExtractor().extract, body)
        text = parsed.get("text", "") or ""
        errored = bool(parsed.get("error"))
        item: dict[str, Any] = {
            "url": url,
            "status": "error" if errored else "ok",
            "method": "document",
            "scraped_at": datetime.now(UTC).isoformat(),
            "content": text,
            "document_type": "pdf",
            "document": {
                "text": text,
                "page_count": parsed.get("page_count", 0),
                "tables": parsed.get("tables", []),
                "method_used": parsed.get("method_used") or ("unavailable" if errored else "pdf"),
            },
            "metadata": {
                "domain": url.split("/")[2] if "://" in url else url,
                "content_length": len(text),
            },
        }
        if errored:
            item["error"] = str(parsed["error"])[:160]
        return item

    async def _parse_document(self, url: str, options: dict[str, Any]) -> dict[str, Any]:
        try:
            resp = await self._fetch(url)
        except Exception as exc:  # noqa: BLE001
            return {
                "url": url,
                "status": "error",
                "method": "document",
                "error": f"document_fetch_failed: {str(exc)[:120]}",
                "scraped_at": datetime.now(UTC).isoformat(),
            }
        ctype = resp.headers.get("content-type", "").lower()
        is_pdf = "pdf" in ctype or url.lower().split("?")[0].endswith(".pdf")
        if is_pdf:
            return await self._pdf_item(url, resp.content)
        item = await super().process_url(url, options)
        item["document_type"] = "html"
        item["document"] = {}
        return item
