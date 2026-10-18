"""Render-wait tier — load a JS SPA in Playwright/Camoufox and wait for network-idle."""

# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

from typing import Any

from pry.core.errors import InvalidRequestError
from pry.engine.methods import _common
from pry.engine.methods._common import _DEFAULT_USER_AGENT, logger
from pry.engine.methods.render_page import RenderSpec, drive, pick_renderer
from pry.engine.page_lifecycle import (
    RENDER_TIMEOUT_S,
    closing_browser,
    open_page,
    run_bounded,
)
from pry.engine.url_guard import validate_url

_CHROMIUM_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--no-sandbox",
    "--disable-dev-shm-usage",
]


async def _render_with_playwright(
    url: str,
    wait_ms: int,
    *,
    selector: str,
    proxy: str,
    collect_json: bool,
) -> str | None:
    """Render a page in Playwright; never raises (returns None on failure)."""
    if not _common._HAS_PLAYWRIGHT:
        return None
    spec = RenderSpec(url, wait_ms, selector, collect_json, networkidle=True)
    try:
        async with _common.async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True, args=_CHROMIUM_ARGS)
            async with closing_browser(browser):
                context_kwargs: dict[str, Any] = {
                    "user_agent": _DEFAULT_USER_AGENT,
                    "locale": "en-US",
                    "timezone_id": "America/New_York",
                }
                if proxy:
                    context_kwargs["proxy"] = {"server": proxy}
                context = await browser.new_context(**context_kwargs)
                async with open_page(context) as page:
                    return await drive(page, spec, [])
    except Exception as e:  # noqa: BLE001 - never-raise guard
        logger.debug("fetch_rendered_playwright_failed", extra={"error": str(e)[:80]})
        return None


async def _render_real_camoufox(url: str, wait_ms: int, spec_kwargs: dict[str, Any]) -> str | None:
    """Render through the installed ``camoufox.AsyncCamoufox`` package."""
    spec = RenderSpec(url, wait_ms, **spec_kwargs)
    try:
        async with _common.AsyncCamoufox(headless=True) as browser:
            async with open_page(browser) as page:
                return await drive(page, spec, [])
    except Exception as e:  # noqa: BLE001 - never-raise guard
        logger.debug("fetch_rendered_camoufox_failed", extra={"error": str(e)[:80]})
        return None


async def _render_with_camoufox(
    url: str,
    wait_ms: int,
    *,
    selector: str,
    proxy: str,
    collect_json: bool,
) -> str | None:
    """Render a page in Camoufox; never raises (returns None on failure).

    Uses the real ``camoufox.AsyncCamoufox`` when the package is installed,
    otherwise falls back to the in-repo ``CamoufoxBrowser`` wrapper.
    """
    spec_kwargs = {"selector": selector, "collect_json": collect_json}
    if _common._HAS_CAMOUFOX and _common.AsyncCamoufox is not None:
        rendered = await _render_real_camoufox(url, wait_ms, spec_kwargs)
        if rendered is not None:
            return rendered
        # fall through to the in-repo wrapper
    if _common._HAS_CAMOUFOX_INTEGRATION and _common.CamoufoxBrowser is not None:
        try:
            browser = _common.CamoufoxBrowser()
            result = await browser.fetch(
                url,
                wait_selector=selector,
                wait_time=wait_ms,
                proxy=proxy,
            )
            if result.get("success"):
                content = result.get("content") or result.get("raw_html")
                return str(content) if content else None
        except Exception as e:  # noqa: BLE001 - never-raise guard
            logger.debug("fetch_rendered_camoufox_wrapper_failed", extra={"error": str(e)[:80]})
    return None


async def fetch_rendered(
    url: str,
    wait_ms: int = 3000,
    *,
    selector: str = "",
    proxy: str = "",
    collect_json: bool = False,
    prefer: str = "auto",
) -> str | None:
    """Render a JS SPA in a real browser and return the rendered output.

    Loads ``url``, waits for network-idle (best-effort) plus an optional
    ``selector`` (or a bounded ``wait_ms``), then returns the rendered HTML.
    When ``collect_json`` is True and JSON API responses were intercepted via
    ``page.on("response")``, returns them as a JSON array string instead.

    Args:
        url: Absolute http(s) URL of the SPA.
        wait_ms: Network-idle / selector wait in milliseconds (default 3000).
        selector: Optional CSS selector to wait for before returning.
        proxy: Optional proxy URL for the browser context.
        collect_json: When True, prefer intercepted JSON responses over HTML.
        prefer: Browser backend — ``"auto"`` (default), ``"playwright"`` or
            ``"camoufox"``.

    Returns:
        Rendered HTML (or a JSON array string when ``collect_json`` matched),
        or None on any failure. Never raises.
    """
    try:
        validate_url(url)
    except InvalidRequestError:
        logger.warning("silent_exception_swallowed", exc_info=True)
        return None
    renderer = pick_renderer(prefer)
    renderer_fn = _render_with_camoufox if renderer == "camoufox" else _render_with_playwright
    try:
        return await run_bounded(
            RENDER_TIMEOUT_S,
            lambda: renderer_fn(
                url, wait_ms, selector=selector, proxy=proxy, collect_json=collect_json
            ),
        )
    except TimeoutError:
        logger.warning(
            "fetch_rendered_timeout",
            extra={"url": url, "timeout_s": RENDER_TIMEOUT_S},
        )
        return None


__all__ = ["fetch_rendered"]
