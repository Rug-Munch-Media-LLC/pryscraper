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

Launch lives here; teardown lives in ``browser_pool_teardown`` and binary /
Playwright discovery in ``browser_pool_config``.
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
import logging
import threading
from typing import Any

from pry.core.chromium import CHROMIUM_CHANNEL
from pry.engine.browser_pool_config import (
    BrowserUnavailableError,
    async_playwright,
    chromium_binary,
)
from pry.engine.browser_pool_teardown import PoolTeardownMixin, close_browsers

logger = logging.getLogger(__name__)

__all__ = ["BrowserPool", "close_browsers", "get_browser_pool"]


class BrowserPool(PoolTeardownMixin):
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
                    if async_playwright is None:
                        raise BrowserUnavailableError(
                            "browser_unavailable: playwright async API is not importable"
                        )
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
                    except Exception as exc:
                        if self._playwright is not None:
                            with contextlib.suppress(Exception):
                                await self._playwright.stop()
                            self._playwright = None
                        # A browser that cannot launch is a broken dependency,
                        # not evidence about any target: surface it as such so
                        # the caller excludes it from the tier record.
                        raise BrowserUnavailableError(f"browser_unavailable: {exc}") from exc
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
                self._uc_driver = _launch_uc_driver()
            return self._uc_driver


def _launch_uc_driver() -> Any:
    """Build the undetected-chromedriver instance (caller holds the lock)."""
    import subprocess

    import undetected_chromedriver as uc
    from selenium.webdriver.chrome.options import Options

    # Container-safe flags: /dev/shm is small unless shm_size is
    # raised (chromium needs --disable-dev-shm-usage) and the
    # sandbox is unavailable in most container runtimes.
    binary = chromium_binary()
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
            [binary or chromium_binary() or "", "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        version_main = int(out.stdout.split()[1].split(".")[0])
    except Exception:
        logger.debug("uc_chrome_version_detect_failed", exc_info=True)

    return uc.Chrome(
        headless=True,
        use_subprocess=True,
        options=opts,
        **({"version_main": version_main} if version_main else {}),
    )


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
