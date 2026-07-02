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
import random
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

WARMER_DIR = Path(__file__).parent / "warmed_cookies"
WARMER_DIR.mkdir(parents=True, exist_ok=True)


# Realistic pages to "warm" cookies against (these are common referrers/browsing paths)
WARMING_PAGES = {
    "amazon": ["https://www.amazon.com/", "https://www.amazon.com/gp/help/customer/contact-us",
               "https://www.amazon.com/privacy", "https://www.amazon.com/conditions-of-use"],
    "ebay": ["https://www.ebay.com/", "https://www.ebay.com/help/home",
             "https://www.ebay.com/myp/PurchaseHistory"],
    "shopify": ["https://www.shopify.com/", "https://www.shopify.com/pricing"],
    "twitter": ["https://twitter.com/", "https://twitter.com/explore",
                "https://twitter.com/settings/account"],
    "linkedin": ["https://www.linkedin.com/", "https://www.linkedin.com/help/intro"],
    "generic": ["https://www.google.com/", "https://en.wikipedia.org/wiki/Main_Page",
                "https://github.com/"],
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
        """Warm cookies for a target domain by visiting legitimate pages first.

        Args:
            target_domain: Domain to warm cookies for (e.g., "amazon.com")
            session_id: Session identifier (for storing warmed cookies)
            pages_to_visit: Number of pages to visit to warm cookies
            min_delay: Minimum delay between page visits (seconds)
            max_delay: Maximum delay between page visits (seconds)
        """
        from playwright.async_api import async_playwright

        if not session_id:
            session_id = f"{target_domain}_{int(time.time())}"

        # Find warming pages for this domain
        domain_key = next((k for k in WARMING_PAGES if k in target_domain.lower()), "generic")
        pages = WARMING_PAGES[domain_key][:pages_to_visit]

        cookies: list[dict[str, Any]] = []
        user_agent = (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        )

        try:
            async with async_playwright() as pw:
                browser = await pw.chromium.launch(headless=True, args=["--no-sandbox"])
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

                for warming_url in pages:
                    try:
                        await page.goto(warming_url, wait_until="domcontentloaded", timeout=30000)
                        # Human-like behavior: scroll, hover
                        await page.evaluate("window.scrollTo(0, document.body.scrollHeight * 0.3)")
                        await page.wait_for_timeout(random.randint(500, 2000))
                        await page.evaluate("window.scrollTo(0, 0)")
                        await page.wait_for_timeout(random.randint(500, 1500))
                        delay = random.uniform(min_delay, max_delay)
                        await asyncio.sleep(delay)
                    except Exception as e:  # noqa: BLE001
                        logger.warning("warm_page_failed url=%s err=%s", warming_url, str(e)[:50])

                # Collect cookies
                storage_cookies = await context.cookies()
                cookies = [
                    {
                        "name": c["name"],
                        "value": c["value"],
                        "domain": c["domain"],
                        "path": c["path"],
                        "expires": c.get("expires", -1),
                        "httpOnly": c.get("httpOnly", False),
                        "secure": c.get("secure", False),
                    }
                    for c in storage_cookies
                ]

                await browser.close()

            # Save warmed cookies
            cookie_file = WARMER_DIR / f"{session_id}.json"
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
            return {
                "success": True,
                "session_id": session_id,
                "domain": target_domain,
                "cookie_count": len(cookies),
                "pages_visited": pages,
                "expires_at": cookie_data["expires_at"],
            }
        except (json.JSONDecodeError, ValueError) as e:
            return {"success": False, "error": str(e)[:300]}

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
            except (json.JSONDecodeError, ValueError):
                pass
        return sessions
