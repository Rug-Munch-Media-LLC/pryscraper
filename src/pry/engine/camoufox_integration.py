"""Pry — Camoufox (Firefox anti-detection) integration.
Camoufox patches Firefox at the source level to bypass fingerprinting
more effectively than Playwright/Puppeteer. It's a drop-in alternative
for Playwright that focuses on stealth."""

# SPDX-License-Identifier: BSL-1.1
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — Stealth / Anti-Detection Module
# Licensed under Business Source License 1.1 — see LICENSE-BSL-STEALTH.
# Change Date: 2029-01-01 (converts to MIT).

import contextlib
import logging
import random
import time
from typing import Any, ClassVar
from urllib.parse import urlparse

from pry.core.errors import InvalidRequestError
from pry.engine.url_guard import validate_url

# SystemRandom: crypto-grade entropy so human-behavior simulation is unpredictable.
_RNG = random.SystemRandom()

logger = logging.getLogger(__name__)

# Check for camoufox
try:
    from camoufox import AsyncCamoufox

    _has_camoufox = True
except ImportError:
    _has_camoufox = False


class CamoufoxBrowser:
    """Anti-detection Firefox browser using Camoufox."""

    DEFAULT_CONFIGS: ClassVar[dict[str, dict[str, Any]]] = {
        "chrome_windows": {
            "headless": True,
            "os": "windows",
            "browser": "chrome",
            "screen": (1920, 1080),
            "window": (1920, 1080),
        },
        "firefox_windows": {
            "headless": True,
            "os": "windows",
            "browser": "firefox",
            "screen": (1920, 1080),
            "window": (1920, 1080),
        },
        "chrome_mac": {
            "headless": True,
            "os": "macos",
            "browser": "chrome",
            "screen": (2560, 1600),
            "window": (1440, 900),
        },
        "firefox_linux": {
            "headless": True,
            "os": "linux",
            "browser": "firefox",
            "screen": (1920, 1080),
            "window": (1920, 1080),
        },
    }

    def __init__(self, default_profile: str = "chrome_windows"):
        self.default_profile = default_profile
        if not _has_camoufox:
            logger.warning(
                "camoufox_not_available",
                extra={"hint": "pip install camoufox && python -m camoufox fetch"},
            )

    async def _guarded_route(self, route: Any) -> None:
        """Playwright route guard: abort requests that target SSRF-sensitive hosts.

        The browser follows redirects internally, so a ``302 -> 169.254.169.254``
        would otherwise bypass URL validation. Every network request (including
        each redirect hop) passes through this handler and is re-validated with
        :func:`url_guard.validate_url` before continuing. Non-network schemes
        (``data:``, ``blob:``, ``about:``, ...) never touch the network and are
        allowed through.
        """
        request_url = route.request.url
        try:
            parsed = urlparse(request_url)
        except ValueError:
            await route.abort()
            return
        if parsed.scheme not in {"http", "https"}:
            # Non-network scheme (data:, blob:, about:) — no SSRF surface.
            await route.continue_()
            return
        try:
            validate_url(request_url)
        except InvalidRequestError:
            logger.warning("camoufox_ssrf_blocked", extra={"url": request_url})
            await route.abort()
            return
        await route.continue_()

    async def fetch(
        self,
        url: str,
        profile: str = "",
        wait_selector: str = "",
        wait_time: int = 3000,
        proxy: str = "",
        cookies: list[dict] | None = None,
    ) -> dict[str, Any]:
        """Fetch a URL with Camoufox anti-detection.

        Args:
            url: The URL to fetch
            profile: Browser profile (chrome_windows, firefox_windows, etc.)
            wait_selector: CSS selector to wait for before returning
            wait_time: Time to wait in milliseconds
            proxy: Proxy URL
            cookies: Cookies to set before navigation
        """
        if not _has_camoufox:
            return {
                "success": False,
                "error": "camoufox not installed. Run: pip install camoufox && python -m camoufox fetch",
            }
        profile_name = profile or self.default_profile
        config = dict(
            self.DEFAULT_CONFIGS.get(profile_name, self.DEFAULT_CONFIGS["chrome_windows"])
        )
        if proxy:
            config["proxy"] = proxy
        try:
            start = time.time()
            validate_url(url)
            async with AsyncCamoufox(**config) as browser:
                page = await browser.new_page()
                # Route guard re-validates every request, including internal
                # redirect hops the browser follows on its own.
                await page.route("**/*", self._guarded_route)
                if cookies:
                    for cookie in cookies:
                        await page.context.add_cookies([cookie])
                await page.goto(url, wait_until="domcontentloaded")
                if wait_selector:
                    with contextlib.suppress(Exception):
                        await page.wait_for_selector(wait_selector, timeout=wait_time)
                else:
                    await page.wait_for_timeout(wait_time)
                content = await page.content()
                title = await page.title()
                elapsed = time.time() - start
                cookies_received = await page.context.cookies()
                return {
                    "success": True,
                    "url": url,
                    "title": title,
                    "content": content,
                    "raw_html": content,
                    "status_code": 200,
                    "elapsed": round(elapsed, 2),
                    "profile": profile_name,
                    "cookies": cookies_received,
                }
        except Exception as e:  # noqa: BLE001
            return {"success": False, "error": str(e)[:300], "url": url}

    async def fetch_with_stealth(
        self,
        url: str,
        human_behavior: dict | None = None,
        proxy: str = "",
    ) -> dict[str, Any]:
        """Fetch with built-in human behavior simulation."""
        result = await self.fetch(url, proxy=proxy)
        if not result.get("success"):
            return result
        # Apply human behavior patterns
        if human_behavior:
            try:
                from camoufox import AsyncCamoufox

                config = dict(self.DEFAULT_CONFIGS.get(self.default_profile, {}))
                if proxy:
                    config["proxy"] = proxy
                async with AsyncCamoufox(**config) as browser:
                    page = await browser.new_page()
                    await page.route("**/*", self._guarded_route)
                    await page.goto(url, wait_until="domcontentloaded")
                    # Apply human behavior
                    if human_behavior.get("scroll"):
                        for scroll_y in human_behavior["scroll"]:
                            await page.evaluate(f"window.scrollTo(0, {scroll_y})")
                            await page.wait_for_timeout(_RNG.randint(200, 800))
                    if human_behavior.get("wait_time"):
                        await page.wait_for_timeout(human_behavior["wait_time"])
                    content = await page.content()
                    result["content"] = content
                    result["raw_html"] = content
            except Exception:  # noqa: BLE001, S110 - fallback: return whatever partial result exists
                pass
        return result

    def is_available(self) -> bool:
        return _has_camoufox

    @staticmethod
    def list_profiles() -> list[str]:
        return list(CamoufoxBrowser.DEFAULT_CONFIGS.keys())
