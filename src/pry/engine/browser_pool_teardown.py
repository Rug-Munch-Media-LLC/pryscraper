"""Pry — browser pool teardown and shutdown.

Owns graceful close/reset of pooled browsers and the process-wide shutdown
entry point, keeping lifecycle teardown out of the launch path.
"""

# SPDX-License-Identifier: BSL-1.1
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — Stealth / Anti-Detection Module
# Licensed under Business Source License 1.1 — see LICENSE-BSL-STEALTH.
# Change Date: 2029-01-01 (converts to MIT).

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class PoolTeardownMixin:
    """Close/reset behaviour for ``BrowserPool``."""

    async def close(self) -> None:
        """Close all pooled browsers (graceful shutdown)."""
        if self._closed:
            return
        self._closed = True
        await self._release()

    async def _release(self) -> None:
        """Release every pooled resource, ignoring shutdown errors."""
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


async def close_camoufox() -> None:
    """Delegate shutdown to Camoufox's own module-level pool."""
    try:
        from pry.engine.camoufox_integration import close_browsers as _close_camoufox

        await _close_camoufox()
    except Exception:
        logger.debug("camoufox_pool_close_failed", exc_info=True)


async def close_browsers() -> None:
    """Close all pooled browsers. Call during graceful shutdown.

    Closes the process-level singleton pool (Playwright + undetected-chromedriver)
    and delegates to Camoufox's own module-level pool inside the integration.
    """
    from pry.engine.browser_pool import get_browser_pool

    await get_browser_pool().close()
    await close_camoufox()
