"""Pry — Camoufox (Firefox anti-detection) integration.

Camoufox patches Firefox at the source level to bypass fingerprinting more
effectively than Playwright/Puppeteer. This module is the public facade: it owns
optional-dependency detection and the process-level pooled browser, delegating
profiles, SSRF guarding, page mechanics and human-behaviour to sibling modules.
"""

# SPDX-License-Identifier: BSL-1.1
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — Stealth / Anti-Detection Module
# Licensed under Business Source License 1.1 — see LICENSE-BSL-STEALTH.
# Change Date: 2029-01-01 (converts to MIT).

from __future__ import annotations

import contextlib
import logging
from typing import Any, ClassVar

from pry.core.errors import InvalidRequestError  # noqa: F401 - re-export surface
from pry.engine.camoufox_config import DEFAULT_CONFIGS, resolve_config
from pry.engine.camoufox_guard import guard_route
from pry.engine.camoufox_page import FetchSpec, fetch_page
from pry.engine.camoufox_stealth import apply_human_behavior
from pry.engine.url_guard import validate_url

logger = logging.getLogger(__name__)

# Check for camoufox
AsyncCamoufox: Any = None
try:
    from camoufox import AsyncCamoufox

    _has_camoufox = True
except ImportError:
    logger.warning("silent_exception_swallowed", exc_info=True)
    _has_camoufox = False

# Module-level pooled Camoufox browser: launched once, reused across requests
# (a fresh page is closed after each). No-proxy path only.
_pooled_camoufox: Any = None
_pooled_camoufox_config: dict[str, Any] | None = None
_MISSING_ERROR = "camoufox not installed. Run: pip install camoufox && python -m camoufox fetch"


async def _get_pooled_camoufox(config: dict[str, Any]) -> Any:
    """Return the shared Camoufox browser, launching it once and caching it.

    A changed config closes the cached browser and relaunches with the new one.
    """
    global _pooled_camoufox, _pooled_camoufox_config
    if _pooled_camoufox is not None and _pooled_camoufox_config == config:
        return _pooled_camoufox
    if _pooled_camoufox is not None:
        try:
            await _pooled_camoufox.__aexit__(None, None, None)
        except Exception:
            logger.debug("browser_cleanup_failed", exc_info=True)
        _pooled_camoufox = None
    _pooled_camoufox = await AsyncCamoufox(**config).__aenter__()
    _pooled_camoufox_config = config
    return _pooled_camoufox


async def close_browsers() -> None:
    """Close the pooled Camoufox browser (graceful shutdown)."""
    global _pooled_camoufox, _pooled_camoufox_config
    if _pooled_camoufox is not None:
        try:
            await _pooled_camoufox.__aexit__(None, None, None)
        except Exception:
            logger.debug("browser_cleanup_failed", exc_info=True)
        _pooled_camoufox = None
        _pooled_camoufox_config = None


class CamoufoxBrowser:
    """Anti-detection Firefox browser using Camoufox."""

    DEFAULT_CONFIGS: ClassVar[dict[str, dict[str, Any]]] = DEFAULT_CONFIGS

    def __init__(self, default_profile: str = "chrome_windows"):
        self.default_profile = default_profile
        if not _has_camoufox:
            logger.warning(
                "camoufox_not_available",
                extra={"hint": "pip install camoufox && python -m camoufox fetch"},
            )

    async def _guarded_route(self, route: Any) -> None:
        """Playwright route guard: abort requests to SSRF-sensitive hosts."""
        await guard_route(route)

    async def _run_on_browser(self, browser: Any, spec: FetchSpec) -> dict[str, Any]:
        """Acquire an isolated page, fetch, and close only the page."""
        page = await browser.new_page()
        try:
            return await fetch_page(page, spec, self._guarded_route)
        finally:
            with contextlib.suppress(Exception):
                await page.close()

    async def fetch(
        self,
        url: str,
        profile: str = "",
        wait_selector: str = "",
        wait_time: int = 3000,
        proxy: str = "",
        cookies: list[dict] | None = None,
        browser: Any = None,
    ) -> dict[str, Any]:
        """Fetch a URL with Camoufox anti-detection.

        ``browser`` optionally supplies a shared browser to reuse (pooling): a
        fresh page is created per request and closed after use.
        """
        if not _has_camoufox:
            return {"success": False, "error": _MISSING_ERROR}
        profile_name = profile or self.default_profile
        config = resolve_config(profile_name)
        if proxy:
            config["proxy"] = proxy
        spec = FetchSpec(
            url=url,
            profile_name=profile_name,
            wait_selector=wait_selector,
            wait_time=wait_time,
            cookies=cookies,
        )
        try:
            validate_url(url)
            if browser is not None:
                # Explicit pooled path: reuse the caller's shared browser.
                return await self._run_on_browser(browser, spec)
            if not proxy:
                # No proxy: reuse the module-level pooled browser (launched
                # once) instead of launching a fresh Firefox per request.
                pooled = await _get_pooled_camoufox(config)
                return await self._run_on_browser(pooled, spec)
            async with AsyncCamoufox(**config) as fresh:
                return await self._run_on_browser(fresh, spec)
        except Exception as e:
            logger.warning("silent_exception_swallowed", exc_info=True)
            return {"success": False, "error": str(e)[:300], "url": url}

    async def fetch_with_stealth(
        self,
        url: str,
        human_behavior: dict | None = None,
        proxy: str = "",
    ) -> dict[str, Any]:
        """Fetch with built-in human behavior simulation.

        The result always reports whether the human-behaviour pass ran.
        ``human_behavior_applied`` is True only when a non-empty
        ``human_behavior`` was requested and fully executed; otherwise
        ``human_behavior_error`` names the failure — a direct-path success can
        never be read as "stealthed fetch".
        """
        result = await self.fetch(url, proxy=proxy)
        if not result.get("success"):
            return result
        if not human_behavior:
            result["human_behavior_applied"] = False
            result["human_behavior_error"] = None
            return result
        try:
            content = await self._apply_human_behavior(url, human_behavior, proxy)
        except Exception as e:
            reason = f"{type(e).__name__}: {e}"[:300]
            logger.warning(
                "human_behavior_pass_failed", extra={"url": url, "error": reason}, exc_info=True
            )
            result["human_behavior_applied"] = False
            result["human_behavior_error"] = reason
            return result
        result["content"] = content
        result["raw_html"] = content
        result["human_behavior_applied"] = True
        result["human_behavior_error"] = None
        return result

    async def _apply_human_behavior(self, url: str, human_behavior: dict, proxy: str) -> str:
        """Run the human-behaviour pass in a fresh browser and return the HTML."""
        config = dict(self.DEFAULT_CONFIGS.get(self.default_profile, {}))
        if proxy:
            config["proxy"] = proxy
        return await apply_human_behavior(url, config, self._guarded_route, human_behavior)

    def is_available(self) -> bool:
        return _has_camoufox

    def default_config(self) -> dict[str, Any]:
        """Return the config dict for the default profile (for pooling)."""
        return resolve_config(self.default_profile)

    @staticmethod
    def list_profiles() -> list[str]:
        return list(CamoufoxBrowser.DEFAULT_CONFIGS.keys())
