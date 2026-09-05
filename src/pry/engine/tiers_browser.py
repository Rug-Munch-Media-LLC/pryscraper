"""Browser tier implementations (undetected, playwright, TLS fingerprint, camoufox).

Part of the ``TierMixin`` composition in :mod:`pry.engine.tiers`.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import asyncio
import logging
from typing import Any

from pry.engine.browser_pool import get_browser_pool
from pry.engine.tiers_base import _RNG, _us_flag

logger = logging.getLogger(__name__)


class TierBrowserMixin:
    """Browser-based scraping tiers."""

    async def _tier_undetected(
        self, url: str, opts: dict[str, Any], proxy_url: str | None = None
    ) -> str | None:
        if not _us_flag("_has_undetected"):
            return None
        try:
            import time as _time

            def _do_fetch() -> str:
                # Reuse the pooled driver (launched once) instead of launching
                # a fresh Chrome per request. The pool serializes access with a
                # lock because a single driver can only navigate one page at a
                # time.
                driver = get_browser_pool().get_uc_driver()
                try:
                    driver.get(url)
                    # Note: time.sleep is used inside a sync thread-pool task because
                    # undetected_chromedriver's blocking API runs in asyncio.to_thread.
                    # Replacing with asyncio.sleep would require restructuring the tier
                    # to be fully async; this sync sleep is bounded and does not block
                    # the event loop directly.
                    _time.sleep(_RNG.uniform(2, 4))
                    return driver.page_source
                finally:
                    # The driver is pooled and must NOT be quit here — quitting
                    # would discard the cached Chrome process. Only the page is
                    # reset for the next request.
                    try:
                        driver.get("about:blank")
                    except Exception:
                        logger.debug("undetected_reset_failed", exc_info=True)

            return await asyncio.to_thread(_do_fetch)
        except Exception as e:
            logger.debug("undetected_failed", extra={"error": str(e)[:200]})
        return None

    async def _tier_playwright(
        self, url: str, opts: dict[str, Any], proxy_url: str | None = None
    ) -> str | None:
        if not _us_flag("_has_playwright"):
            return None
        try:
            # Reuse the pooled browser (launched once) instead of launching a
            # fresh Chromium per request. Each request gets an isolated context
            # that is closed after use — the browser itself stays alive.
            browser = await get_browser_pool().get_playwright_browser()
            context = await browser.new_context(
                viewport={
                    "width": _RNG.choice([1920, 1366, 1440]),
                    "height": _RNG.choice([1080, 768, 900]),
                },
                user_agent=self._rotate_ua(),
                locale="en-US",
                timezone_id="America/New_York",
            )
            try:
                stealth_engine = _us_flag("_stealth_engine")
                stealth_script = stealth_engine.generate_all() if stealth_engine else ""
                if stealth_script:
                    await context.add_init_script(stealth_script)
                page = await context.new_page()
                await page.goto(url, wait_until="domcontentloaded", timeout=60000)
                await page.wait_for_timeout(_RNG.randint(1000, 3000))
                for _ in range(_RNG.randint(2, 5)):
                    await page.evaluate(f"window.scrollBy(0, {_RNG.randint(200, 500)})")
                    await page.wait_for_timeout(_RNG.randint(300, 1000))
                    await page.mouse.move(_RNG.randint(100, 1400), _RNG.randint(100, 800))
                return await page.content()
            finally:
                # Always close the context — a page-goto timeout (up to 60s)
                # or any other failure would otherwise leak a context per
                # failed attempt. The pooled browser is NOT closed here.
                try:
                    await context.close()
                except Exception:
                    logger.debug("playwright_context_close_failed", exc_info=True)
        except OSError as e:
            logger.debug("playwright_failed", extra={"error": str(e)[:200]})
        return None

    async def _tier_tls_fingerprint(
        self, url: str, opts: dict[str, Any], proxy_url: str | None = None
    ) -> str | None:
        """Fetch using curl_cffi TLS fingerprint impersonation."""
        tls_scraper = getattr(self, "_tls_scraper", None)
        if not tls_scraper or not tls_scraper.is_available():
            return None
        try:
            result = await tls_scraper.fetch(
                url,
                headers=self._build_headers(url),
                proxy=proxy_url or "",
                timeout_s=opts.get("timeout", 30),
            )
            if result.get("success") and result.get("status_code", 0) < 400:
                return result.get("text", "")
        except Exception as e:
            logger.debug("tls_fingerprint_failed", extra={"error": str(e)[:200]})
        return None

    async def _tier_camoufox(
        self, url: str, opts: dict[str, Any], proxy_url: str | None = None
    ) -> str | None:
        """Fetch using Camoufox anti-detection Firefox."""
        camoufox = getattr(self, "_camoufox", None)
        if not camoufox or not camoufox.is_available():
            return None
        try:
            result = await camoufox.fetch(
                url,
                wait_time=opts.get("wait_time", 3000),
                proxy=proxy_url or "",
            )
            if result.get("success"):
                return result.get("content", "")
        except Exception as e:
            logger.debug("camoufox_failed", extra={"error": str(e)[:200]})
        return None
