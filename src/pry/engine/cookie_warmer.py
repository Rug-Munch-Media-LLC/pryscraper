"""Pry — Cookie Warming and Session Aging.
Pre-age cookies by browsing legitimate pages first. Aged cookies with
realistic browsing history bypass anti-bot detection that checks for
'fresh' cookies. This is a technique used by professional scraping services.

Split: warming targets / UA in ``cookie_warmer_ua``, persistence and listing
in ``cookie_warmer_storage``; this module owns the warm loop.
"""

# SPDX-License-Identifier: BSL-1.1
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — Stealth / Anti-Detection Module
# Licensed under Business Source License 1.1 — see LICENSE-BSL-STEALTH.
# Change Date: 2029-01-01 (converts to MIT).

import asyncio
import logging
import random
import time
from typing import Any

from pry.core.chromium import CHROMIUM_CHANNEL
from pry.engine.cookie_warmer_storage import (
    build_cookie_data,
    collect_cookies,
    list_warmed,
    load_warmed,
    save_warmed,
)
from pry.engine.cookie_warmer_ua import WARMER_DIR, WARMING_PAGES, tier_user_agent
from pry.engine.route_guard import install_route_guard

# SystemRandom: crypto-grade entropy so browsing simulation is not predictable.
_RNG = random.SystemRandom()

logger = logging.getLogger(__name__)

__all__ = ["WARMER_DIR", "WARMING_PAGES", "CookieWarmer"]


class CookieWarmer:
    """Warm cookies by simulating realistic user browsing before scraping."""

    def __init__(self, browser_pool: Any = None):
        self._browser_pool = browser_pool

    async def warm_for_site(
        self,
        target_domain: str,
        session_id: str = "",
        pages_to_visit: int = 3,
        min_delay: float = 2.0,
        max_delay: float = 8.0,
    ) -> dict[str, Any]:
        """Warm cookies for ``target_domain`` by visiting legitimate pages first."""
        if not session_id:
            session_id = f"{target_domain}_{int(time.time())}"

        # Find warming pages for this domain
        domain_key = next((k for k in WARMING_PAGES if k in target_domain.lower()), "generic")
        pages = WARMING_PAGES[domain_key][:pages_to_visit]

        user_agent = tier_user_agent()

        try:
            cookies = await self._browse_and_collect(pages, user_agent, min_delay, max_delay)
            cookie_data = build_cookie_data(target_domain, session_id, pages, cookies, user_agent)
            return save_warmed(WARMER_DIR, cookie_data, session_id)
        except Exception as e:  # noqa: BLE001 - warmer must never crash a scrape
            logger.warning(
                "cookie_warm_failed",
                extra={"domain": target_domain, "error": str(e)[:200]},
            )
            return {"success": False, "error": str(e)[:300]}

    async def _browse_and_collect(
        self, pages: list[str], user_agent: str, min_delay: float, max_delay: float
    ) -> list[dict[str, Any]]:
        """Browse the warming pages and return the collected cookies."""
        from playwright.async_api import async_playwright

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=True, channel=CHROMIUM_CHANNEL, args=["--no-sandbox"]
            )
            try:
                context = await browser.new_context(
                    viewport={"width": 1920, "height": 1080},
                    user_agent=user_agent,
                )
                # Add stealth
                await context.add_init_script("""
                    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                    Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
                """)
                page = await context.new_page()
                # Warming targets and any redirect hop are SSRF-validated.
                install_route_guard(page)

                await self._warm_pages(page, pages, min_delay, max_delay)
                return collect_cookies(await context.cookies())
            finally:
                # Always release the browser — an exception in warming must
                # not leak a Chromium process per warm.
                await browser.close()

    async def _warm_pages(
        self, page: Any, pages: list[str], min_delay: float, max_delay: float
    ) -> None:
        """Visit warming pages with human-like scrolling and politeness delays."""
        for warming_url in pages:
            try:
                await page.goto(warming_url, wait_until="domcontentloaded", timeout=30000)
                # Human-like behavior: scroll, paused, scroll back.
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight * 0.3)")
                await page.wait_for_timeout(_RNG.randint(500, 2000))
                await page.evaluate("window.scrollTo(0, 0)")
                await page.wait_for_timeout(_RNG.randint(500, 1500))
                await asyncio.sleep(_RNG.uniform(min_delay, max_delay))
            except Exception as e:  # noqa: BLE001
                logger.warning("warm_page_failed url=%s err=%s", warming_url, str(e)[:50])

    # Kept for callers/tests that used the old static helper.
    _collect_cookies = staticmethod(collect_cookies)

    def get_warmed_cookies(self, session_id: str) -> dict[str, Any] | None:
        """Get warmed cookies for a session."""
        return load_warmed(WARMER_DIR, session_id)

    def list_sessions(self) -> list[dict[str, Any]]:
        return list_warmed(WARMER_DIR)
