"""Pry — Process-level singleton browser pool.

The performance audit found that the browser-based fetch tiers launched a
fresh browser per request (1-3s overhead each). This module owns a single
process-level ``BrowserPool`` singleton shared by ALL ``UltimateScraper``
instances (and any other browser consumers) so the expensive browser launch
cost is paid exactly once per process — regardless of how many scraper
instances or worker threads exist.

The pool launches each browser type ONCE on first use and reuses it across
requests. Every request gets an isolated context (cookies / storage) that is
closed after use — never the browser itself.
"""

# SPDX-License-Identifier: BSL-1.1
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — Stealth / Anti-Detection Module
# Licensed under Business Source License 1.1 — see LICENSE-BSL-STEALTH.
# Change Date: 2029-01-01 (converts to MIT).

from __future__ import annotations

import asyncio
import contextlib
import importlib.util
import logging
import threading
from pathlib import Path
from typing import Any

from pry.core.chromium import CHROMIUM_CHANNEL

_has_playwright = importlib.util.find_spec("playwright") is not None

async_playwright: Any = None
if _has_playwright:
    from playwright.async_api import async_playwright

logger = logging.getLogger(__name__)

# The image ships Playwright's Chromium only (no distro ``chromium`` package).
# undetected-chromedriver still needs a concrete binary, so point it at the
# Playwright build instead of a hard-coded /usr/bin/chromium that no longer
# exists. A distro path still wins when present (local/dev images).
_PLAYWRIGHT_CHROMIUM = tuple(
    str(p)
    for pattern in ("chromium-*/chrome-linux64/chrome", "chromium-*/chrome-linux/chrome")
    for p in sorted(Path("/ms-playwright").glob(pattern), reverse=True)
)


def _chromium_binary() -> str | None:
    """Return the first usable Chromium executable, or None."""
    for candidate in ("/usr/bin/chromium", "/usr/bin/chromium-browser", *_PLAYWRIGHT_CHROMIUM):
        if Path(candidate).is_file():
            return candidate
    return None


class BrowserPool:
    """Lazy singleton browser pool for the browser-based fetch tiers.

    The performance audit found that ``_tier_playwright``, ``_tier_undetected``
    and ``_tier_camoufox`` launched a fresh browser per request (1-3s overhead
    each). This pool launches each browser type ONCE on first use and reuses it
    across requests. Every request gets an isolated context (cookies / storage)
    that is closed after use — never the browser itself — so the expensive
    launch cost is paid a single time per process.
    """

    def __init__(self) -> None:
        self._playwright: Any = None
        self._playwright_browser: Any = None
        self._uc_driver: Any = None
        self._uc_lock = threading.Lock()
        self._pw_lock = asyncio.Lock()
        self._closed = False

    # -- Playwright -----------------------------------------------------
    async def get_playwright_browser(self) -> Any:
        """Return the shared Playwright Chromium browser, launching it once."""
        if self._closed:
            raise RuntimeError("browser pool is closed")
        if self._playwright_browser is None:
            async with self._pw_lock:
                if self._playwright_browser is None:
                    try:
                        self._playwright = await async_playwright().start()
                        self._playwright_browser = await self._playwright.chromium.launch(
                            headless=True,
                            channel=CHROMIUM_CHANNEL,
                            args=[
                                "--disable-blink-features=AutomationControlled",
                                "--no-sandbox",
                                "--disable-dev-shm-usage",
                                "--disable-web-security",
                            ],
                        )
                    except Exception:
                        if self._playwright is not None:
                            with contextlib.suppress(Exception):
                                await self._playwright.stop()
                            self._playwright = None
                        raise
        return self._playwright_browser

    # -- undetected-chromedriver (synchronous) --------------------------
    def get_uc_driver(self) -> Any:
        """Return the shared undetected-chromedriver, launching it once.

        Runs inside ``asyncio.to_thread`` (the driver API is synchronous). A
        threading lock serializes access because a single driver can only
        navigate one page at a time.
        """
        if self._closed:
            raise RuntimeError("browser pool is closed")
        with self._uc_lock:
            if self._uc_driver is None:
                import subprocess

                import undetected_chromedriver as uc
                from selenium.webdriver.chrome.options import Options

                # Container-safe flags: /dev/shm is small unless shm_size is
                # raised (chromium needs --disable-dev-shm-usage) and the
                # sandbox is unavailable in most container runtimes.
                binary = _chromium_binary()
                opts = Options()
                if binary is not None:
                    opts.binary_location = binary
                opts.add_argument("--no-sandbox")
                opts.add_argument("--disable-dev-shm-usage")
                opts.add_argument("--disable-gpu")

                # Pin the driver to the installed chromium's major version:
                # uc otherwise fetches the latest chromedriver, which fails
                # with SessionNotCreated when the system chromium lags.
                version_main: int | None = None
                try:
                    out = subprocess.run(  # noqa: S603 - operator-owned path
                        [binary or _chromium_binary() or "", "--version"],
                        capture_output=True,
                        text=True,
                        timeout=10,
                    )
                    version_main = int(out.stdout.split()[1].split(".")[0])
                except Exception:
                    logger.debug("uc_chrome_version_detect_failed", exc_info=True)

                self._uc_driver = uc.Chrome(
                    headless=True,
                    use_subprocess=True,
                    options=opts,
                    **({"version_main": version_main} if version_main else {}),
                )
            return self._uc_driver

    async def close(self) -> None:
        """Close all pooled browsers (graceful shutdown)."""
        if self._closed:
            return
        self._closed = True
        if self._playwright_browser is not None:
            try:
                await self._playwright_browser.close()
            except Exception:
                logger.debug("pool_playwright_close_failed", exc_info=True)
            self._playwright_browser = None
        if self._playwright is not None:
            try:
                await self._playwright.stop()
            except Exception:
                logger.debug("pool_playwright_stop_failed", exc_info=True)
            self._playwright = None
        if self._uc_driver is not None:
            try:
                self._uc_driver.quit()
            except Exception:
                logger.debug("pool_uc_quit_failed", exc_info=True)
            self._uc_driver = None

    def reset(self) -> None:
        """Drop all cached browser references without closing them.

        Used by tests to guarantee isolation between cases (a module-level
        singleton would otherwise leak a mocked driver across tests).
        """
        self._playwright = None
        self._playwright_browser = None
        self._uc_driver = None
        self._closed = False


# Process-level singleton: ALL scraper instances (across workers / threads in
# this process) share this one pool. Created lazily on first use.
_pool: BrowserPool | None = None
_pool_lock = threading.Lock()


def get_browser_pool() -> BrowserPool:
    """Return the process-level singleton BrowserPool, creating it on first use.

    Every ``UltimateScraper`` instance (and any other browser consumer) calls
    this instead of constructing its own pool, so the whole process shares a
    single Playwright browser / undetected-chromedriver / Camoufox.
    """
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                _pool = BrowserPool()
    return _pool


async def close_browsers() -> None:
    """Close all pooled browsers. Call during graceful shutdown.

    Closes the process-level singleton pool (Playwright + undetected-chromedriver)
    and delegates to Camoufox's own module-level pool inside the integration.
    """
    await get_browser_pool().close()
    # Camoufox maintains its own module-level pool inside the integration.
    try:
        from pry.engine.camoufox_integration import close_browsers as _close_camoufox

        await _close_camoufox()
    except Exception:
        logger.debug("camoufox_pool_close_failed", exc_info=True)
