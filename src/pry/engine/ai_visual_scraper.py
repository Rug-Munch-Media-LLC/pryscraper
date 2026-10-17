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

The vision endpoint is restricted to a server-side allowlist. A caller may
select an endpoint, but never a host the operator did not approve: the Bearer
key must not be sent to an arbitrary destination.
"""

from __future__ import annotations

import base64
import importlib.util
import logging
import os
import urllib.parse
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_VISION_ENDPOINT = "https://api.openai.com/v1/chat/completions"

# Server-side default: configured LLM providers only. Extend with
# PRY_VISION_ALLOWED_HOSTS="host1,host2" (never from caller input).
DEFAULT_ALLOWED_VISION_HOSTS = frozenset(
    {
        "api.openai.com",
        "api.anthropic.com",
        "generativelanguage.googleapis.com",
        "openrouter.ai",
        "api.deepseek.com",
        "api.groq.com",
        "api.mistral.ai",
    }
)


class VisionEndpointNotAllowed(ValueError):
    """Raised when a caller supplies a vision endpoint that is not allow-listed."""


def allowed_vision_hosts() -> frozenset[str]:
    """Return the effective allowlist (env override or built-in providers)."""
    raw = os.getenv("PRY_VISION_ALLOWED_HOSTS", "")
    configured = {h.strip().lower() for h in raw.split(",") if h.strip()}
    return frozenset(configured) if configured else DEFAULT_ALLOWED_VISION_HOSTS


def validate_vision_endpoint(endpoint: str) -> str:
    """Validate an endpoint against the allowlist and return it unchanged."""
    url = endpoint or DEFAULT_VISION_ENDPOINT
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https":
        raise VisionEndpointNotAllowed(f"vision endpoint must use https: {url!r}")
    host = (parsed.hostname or "").lower()
    if not host:
        raise VisionEndpointNotAllowed("vision endpoint is missing a hostname")
    if host not in allowed_vision_hosts():
        raise VisionEndpointNotAllowed(
            f"vision endpoint host {host!r} is not allow-listed; "
            "set PRY_VISION_ALLOWED_HOSTS server-side to permit it"
        )
    return url


# Optional dependencies
_has_playwright = False
try:
    from playwright.async_api import async_playwright

    _has_playwright = True
except ImportError as e:
    logger.debug("ai_visual_scraper_playwright_unavailable", extra={"error": str(e)[:160]})

# Availability probe only — the name is imported locally where used
# (_extract_with_llm), so no module-level binding is needed.
_has_httpx = importlib.util.find_spec("httpx") is not None


class AIVisualScraper:
    """AI-powered visual scraping using screenshot + LLM vision."""

    def __init__(self, llm_endpoint: str = "", llm_api_key: str = ""):
        self.llm_endpoint = validate_vision_endpoint(llm_endpoint)
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
        # Re-validate at send time: the key must never reach a host that is
        # not allow-listed, even if the attribute was mutated after __init__.
        try:
            endpoint = validate_vision_endpoint(self.llm_endpoint)
        except VisionEndpointNotAllowed as e:
            logger.error("vision_endpoint_rejected", extra={"error": str(e)[:160]})
            return None
        try:
            import httpx

            b64_image = base64.b64encode(screenshot).decode()
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(
                    endpoint,
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
