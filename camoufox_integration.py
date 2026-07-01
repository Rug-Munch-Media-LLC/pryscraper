"""Pry — Camoufox (Firefox anti-detection) integration.
Camoufox patches Firefox at the source level to bypass fingerprinting
more effectively than Playwright/Puppeteer. It's a drop-in alternative
for Playwright that focuses on stealth."""

import logging
import random
import time
from typing import Any

logger = logging.getLogger(__name__)

# Check for camoufox
try:
    from camoufox import AsyncCamoufox
    from camoufox.utils import DefaultAddons
    _has_camoufox = True
except ImportError:
    _has_camoufox = False


class CamoufoxBrowser:
    """Anti-detection Firefox browser using Camoufox."""

    DEFAULT_CONFIGS = {
        "chrome_windows": {
            "headless": True, "os": "windows", "browser": "chrome",
            "screen": (1920, 1080), "window": (1920, 1080),
        },
        "firefox_windows": {
            "headless": True, "os": "windows", "browser": "firefox",
            "screen": (1920, 1080), "window": (1920, 1080),
        },
        "chrome_mac": {
            "headless": True, "os": "macos", "browser": "chrome",
            "screen": (2560, 1600), "window": (1440, 900),
        },
        "firefox_linux": {
            "headless": True, "os": "linux", "browser": "firefox",
            "screen": (1920, 1080), "window": (1920, 1080),
        },
    }

    def __init__(self, default_profile: str = "chrome_windows"):
        self.default_profile = default_profile
        if not _has_camoufox:
            logger.warning("camoufox_not_available",
                           extra={"hint": "pip install camoufox && python -m camoufox fetch"})

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
            return {"success": False, "error": "camoufox not installed. Run: pip install camoufox && python -m camoufox fetch"}
        profile_name = profile or self.default_profile
        config = dict(self.DEFAULT_CONFIGS.get(profile_name, self.DEFAULT_CONFIGS["chrome_windows"]))
        if proxy: config["proxy"] = proxy
        try:
            start = time.time()
            async with AsyncCamoufox(**config) as browser:
                page = await browser.new_page()
                if cookies:
                    for cookie in cookies:
                        await page.context.add_cookies([cookie])
                await page.goto(url, wait_until="domcontentloaded")
                if wait_selector:
                    try:
                        await page.wait_for_selector(wait_selector, timeout=wait_time)
                    except Exception:
                        pass
                else:
                    await page.wait_for_timeout(wait_time)
                content = await page.content()
                title = await page.title()
                elapsed = time.time() - start
                cookies_received = await page.context.cookies()
                return {
                    "success": True, "url": url, "title": title,
                    "content": content, "raw_html": content,
                    "status_code": 200, "elapsed": round(elapsed, 2),
                    "profile": profile_name, "cookies": cookies_received,
                }
        except Exception as e:
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
                if proxy: config["proxy"] = proxy
                async with AsyncCamoufox(**config) as browser:
                    page = await browser.new_page()
                    await page.goto(url, wait_until="domcontentloaded")
                    # Apply human behavior
                    if human_behavior.get("scroll"):
                        for scroll_y in human_behavior["scroll"]:
                            await page.evaluate(f"window.scrollTo(0, {scroll_y})")
                            await page.wait_for_timeout(random.randint(200, 800))
                    if human_behavior.get("wait_time"):
                        await page.wait_for_timeout(human_behavior["wait_time"])
                    content = await page.content()
                    result["content"] = content
                    result["raw_html"] = content
            except Exception:
                pass
        return result

    def is_available(self) -> bool:
        return _has_camoufox

    @staticmethod
    def list_profiles() -> list[str]:
        return list(CamoufoxBrowser.DEFAULT_CONFIGS.keys())
