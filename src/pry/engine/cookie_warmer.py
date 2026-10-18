"""Pry — Cookie Warming and Session Aging.
Pre-age cookies by browsing legitimate pages first. Aged cookies with
realistic browsing history bypass anti-bot detection that checks for
'fresh' cookies. This is a technique used by professional scraping services."""

# SPDX-License-Identifier: BSL-1.1
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — Stealth / Anti-Detection Module
# Licensed under Business Source License 1.1 — see LICENSE-BSL-STEALTH.
# Change Date: 2029-01-01 (converts to MIT).

import asyncio
import json
import logging
import os
import random
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from pry.core.chromium import CHROMIUM_CHANNEL
from pry.core.paths import PRY_DATA_DIR
from pry.engine.route_guard import install_route_guard

# SystemRandom: crypto-grade entropy so browsing simulation is not predictable.
_RNG = random.SystemRandom()

logger = logging.getLogger(__name__)

#: Runtime data dir — never the package tree (installed packages are read-only
#: and writing session cookies next to the source leaks them into images).
WARMER_DIR = PRY_DATA_DIR / "warmed_cookies"
WARMER_DIR.mkdir(parents=True, exist_ok=True)


def _tier_user_agent() -> str:
    """The UA the render tier actually sends — read at call time.

    Kept in one place so warmed cookies cannot claim a browser version the
    scraper never presents (a UA mismatch is a bot signal).
    """
    from pry.engine.methods import _common

    return _common._DEFAULT_USER_AGENT


# Realistic pages to "warm" cookies against (these are common referrers/browsing paths)
WARMING_PAGES = {
    "amazon": [
        "https://www.amazon.com/",
        "https://www.amazon.com/gp/help/customer/contact-us",
        "https://www.amazon.com/privacy",
        "https://www.amazon.com/conditions-of-use",
    ],
    "ebay": [
        "https://www.ebay.com/",
        "https://www.ebay.com/help/home",
        "https://www.ebay.com/myp/PurchaseHistory",
    ],
    "shopify": ["https://www.shopify.com/", "https://www.shopify.com/pricing"],
    "twitter": [
        "https://twitter.com/",
        "https://twitter.com/explore",
        "https://twitter.com/settings/account",
    ],
    "linkedin": ["https://www.linkedin.com/", "https://www.linkedin.com/help/intro"],
    "generic": [
        "https://www.google.com/",
        "https://en.wikipedia.org/wiki/Main_Page",
        "https://github.com/",
    ],
}


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
        from playwright.async_api import async_playwright

        if not session_id:
            session_id = f"{target_domain}_{int(time.time())}"

        # Find warming pages for this domain
        domain_key = next((k for k in WARMING_PAGES if k in target_domain.lower()), "generic")
        pages = WARMING_PAGES[domain_key][:pages_to_visit]

        cookies: list[dict[str, Any]] = []
        user_agent = _tier_user_agent()

        try:
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
                    cookies = self._collect_cookies(await context.cookies())
                finally:
                    # Always release the browser — an exception in warming must
                    # not leak a Chromium process per warm.
                    await browser.close()

            # Save warmed cookies (session cookies are credentials: 0600).
            cookie_file = Path(WARMER_DIR) / f"{session_id}.json"
            cookie_data = {
                "domain": target_domain,
                "session_id": session_id,
                "warmed_at": datetime.now(UTC).isoformat(),
                "expires_at": (datetime.now(UTC) + timedelta(days=30)).isoformat(),
                "pages_visited": pages,
                "cookies": cookies,
                "user_agent": user_agent,
            }
            cookie_file.write_text(json.dumps(cookie_data, indent=2))
            os.chmod(cookie_file, 0o600)
            return {
                "success": True,
                "session_id": session_id,
                "domain": target_domain,
                "cookie_count": len(cookies),
                "pages_visited": pages,
                "expires_at": cookie_data["expires_at"],
            }
        except Exception as e:  # noqa: BLE001 - warmer must never crash a scrape
            logger.warning(
                "cookie_warm_failed",
                extra={"domain": target_domain, "error": str(e)[:200]},
            )
            return {"success": False, "error": str(e)[:300]}

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

    @staticmethod
    def _collect_cookies(storage_cookies: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Keep only the cookie fields the warmer persists."""
        return [
            {
                "name": str(c.get("name", "")),
                "value": str(c.get("value", "")),
                "domain": str(c.get("domain", "")),
                "path": str(c.get("path", "/")),
                "expires": c.get("expires", -1),
                "httpOnly": c.get("httpOnly", False),
                "secure": c.get("secure", False),
            }
            for c in storage_cookies
        ]

    def get_warmed_cookies(self, session_id: str) -> dict[str, Any] | None:
        """Get warmed cookies for a session."""
        cookie_file = WARMER_DIR / f"{session_id}.json"
        if not cookie_file.exists():
            return None
        try:
            data = json.loads(cookie_file.read_text())
            # Check expiry
            expires = datetime.fromisoformat(data["expires_at"])
            if expires < datetime.now(UTC):
                return None
            return data
        except (json.JSONDecodeError, ValueError):
            logger.warning("silent_exception_swallowed", exc_info=True)
            return None

    def list_sessions(self) -> list[dict[str, Any]]:
        sessions: list[dict[str, Any]] = []
        for f in WARMER_DIR.glob("*.json"):
            try:
                data = json.loads(f.read_text())
                sessions.append(
                    {
                        "session_id": data["session_id"],
                        "domain": data["domain"],
                        "warmed_at": data["warmed_at"],
                        "expires_at": data["expires_at"],
                        "cookie_count": len(data.get("cookies", [])),
                    }
                )
            except (json.JSONDecodeError, ValueError) as e:
                logger.warning("cookie_warmer_session_load_failed", extra={"error": str(e)[:160]})
        return sessions
