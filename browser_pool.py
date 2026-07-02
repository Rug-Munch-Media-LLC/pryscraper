"""Pry — shared Playwright browser pool.
Reuses browser instances across requests instead of launching per scrape."""

# SPDX-License-Identifier: BSL-1.1
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — Stealth / Anti-Detection Module
# Licensed under Business Source License 1.1 — see LICENSE-BSL-STEALTH.
# Change Date: 2029-01-01 (converts to MIT).

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)


class BrowserPool:
    """Warm pool of Playwright browser instances.

    Maximum `max_browsers` chromium instances. Each can create multiple
    contexts/pages. Browsers are kept warm and reused across requests.
    """

    def __init__(self, max_browsers: int = 2, headless: bool = True):
        self.max_browsers = max_browsers
        self.headless = headless
        self._playwright: Any = None
        self._browsers: list[Any] = []
        self._lock = asyncio.Lock()
        self._initialized = False

    async def start(self) -> None:
        """Launch the Playwright manager and pre-warm browsers."""
        from playwright.async_api import async_playwright

        self._playwright = await async_playwright().start()
        for _ in range(self.max_browsers):
            browser = await self._launch_browser()
            self._browsers.append(browser)
        self._initialized = True
        logger.info("browser_pool_started", extra={"browsers": self.max_browsers})

    async def _launch_browser(self) -> Any:
        """Launch a single Chromium instance."""
        assert self._playwright is not None
        return await self._playwright.chromium.launch(
            headless=self.headless,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
            ],
        )

    async def get_browser(self) -> Any:
        """Get a browser from the pool (round-robin)."""
        async with self._lock:
            if not self._initialized:
                await self.start()
            if not self._browsers:
                browser = await self._launch_browser()
                self._browsers.append(browser)
            # Simple round-robin: return first, rotate
            browser = self._browsers.pop(0)
            self._browsers.append(browser)
            return browser

    async def close(self) -> None:
        """Close all browsers and stop Playwright."""
        for b in self._browsers:
            try:
                await b.close()
            except OSError:
                logger.exception("browser_close_failed")
        self._browsers.clear()
        if self._playwright:
            await self._playwright.stop()
        self._initialized = False
        logger.info("browser_pool_stopped")


# Module-level singleton
_pool: BrowserPool | None = None


async def get_browser_pool() -> BrowserPool:
    """Get or create the global browser pool."""
    global _pool
    if _pool is None:
        _pool = BrowserPool()
        await _pool.start()
    return _pool


async def close_browser_pool() -> None:
    """Close the global browser pool."""
    global _pool
    if _pool:
        await _pool.close()
        _pool = None
