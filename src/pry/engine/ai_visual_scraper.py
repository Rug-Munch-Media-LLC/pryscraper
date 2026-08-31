# SPDX-License-Identifier: BSL-1.1
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — Stealth / Anti-Detection Module
# Licensed under Business Source License 1.1 — see LICENSE-BSL-STEALTH.
"""Pry — AI Visual Scraper (Tier 13).

Uses screenshot + LLM vision to extract content from pages that resist
traditional scraping. Works when the page is rendered via JS, behind
login walls, or uses canvas/WebGL rendering.

Flow: screenshot → LLM vision model → structured extraction
"""

from __future__ import annotations

import base64
import importlib.util
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Optional dependencies
_has_playwright = False
try:
    from playwright.async_api import async_playwright

    _has_playwright = True
except ImportError:
    pass

# Availability probe only — the name is imported locally where used
# (_extract_with_llm), so no module-level binding is needed.
_has_httpx = importlib.util.find_spec("httpx") is not None


class AIVisualScraper:
    """AI-powered visual scraping using screenshot + LLM vision."""

    def __init__(self, llm_endpoint: str = "", llm_api_key: str = ""):
        self.llm_endpoint = llm_endpoint or "https://api.openai.com/v1/chat/completions"
        self.llm_api_key = llm_api_key

    def is_available(self) -> bool:
        return _has_playwright and bool(self.llm_api_key)

    async def scrape(self, url: str, opts: dict[str, Any] | None = None) -> str | None:
        """Scrape a URL using screenshot + LLM vision."""
        if not _has_playwright:
            return None

        opts = opts or {}
        viewport = opts.get("viewport", {"width": 1920, "height": 1080})
        wait_time = opts.get("wait_time", 5000)

        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_viewport_size(**viewport)
                await page.goto(url, wait_until="networkidle", timeout=30000)
                await page.wait_for_timeout(wait_time)
                screenshot = await page.screenshot(full_page=True)
                await browser.close()

            # Use LLM vision to extract content
            if self.llm_api_key and _has_httpx:
                return await self._extract_with_llm(screenshot, url)
            else:
                # Fallback: return base64 screenshot for later processing
                return f"<screenshot>{base64.b64encode(screenshot).decode()}</screenshot>"

        except Exception as e:
            logger.debug("ai_visual_scraper_failed", extra={"error": str(e)[:50]})
            return None

    async def _extract_with_llm(self, screenshot: bytes, url: str) -> str | None:
        """Extract content from screenshot using LLM vision."""
        try:
            import httpx

            b64_image = base64.b64encode(screenshot).decode()
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(
                    self.llm_endpoint,
                    headers={
                        "Authorization": f"Bearer {self.llm_api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": "gpt-4o",
                        "messages": [
                            {
                                "role": "user",
                                "content": [
                                    {
                                        "type": "text",
                                        "text": "Extract all visible text content from this webpage screenshot. Return clean markdown with headings, paragraphs, and any data tables.",
                                    },
                                    {
                                        "type": "image_url",
                                        "image_url": {"url": f"data:image/png;base64,{b64_image}"},
                                    },
                                ],
                            }
                        ],
                        "max_tokens": 4000,
                    },
                )
                if resp.is_success:
                    data = resp.json()
                    return data["choices"][0]["message"]["content"]
        except Exception as e:
            logger.debug("llm_vision_extraction_failed", extra={"error": str(e)[:50]})
        return None
