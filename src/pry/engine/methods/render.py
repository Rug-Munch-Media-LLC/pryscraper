"""Render-wait tier — load a JS SPA in Playwright/Camoufox and wait for network-idle."""

# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import asyncio
import contextlib
import json
from typing import Any

from pry.core.errors import InvalidRequestError
from pry.engine.body_limits import cap_text
from pry.engine.methods import _common
from pry.engine.methods._common import _DEFAULT_USER_AGENT, logger
from pry.engine.route_guard import install_route_guard
from pry.engine.url_guard import validate_url

#: Wall-clock ceiling for one render. A hung browser otherwise pins the
#: worker forever; the tier contract turns the timeout into a None failure.
_RENDER_TIMEOUT_S = 120.0


def _pick_renderer(prefer: str) -> str:
    """Choose the browser backend for :func:`fetch_rendered`."""
    if prefer == "camoufox":
        return "camoufox"
    if prefer == "playwright":
        return "playwright"
    # auto: prefer the real Camoufox package when present, else Playwright.
    # The in-repo CamoufoxBrowser wrapper exists even without the package, but
    # it can't launch without it, so Playwright is the safer default.
    if _common._HAS_CAMOUFOX:
        return "camoufox"
    return "playwright"


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
    try:
        json_bodies: list[str] = []

        async def _on_response(response: Any) -> None:
            content_type = response.headers.get("content-type", "")
            if "json" not in content_type.lower():
                return
            try:
                text, _ = cap_text(await response.text(), str(getattr(response, 'url', '')))
                json_bodies.append(text)
            except Exception:  # noqa: BLE001 - never-raise guard
                logger.debug("fetch_rendered_json_capture_failed", exc_info=True)

        async with _common.async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                ],
            )
            try:
                context_kwargs: dict[str, Any] = {
                    "user_agent": _DEFAULT_USER_AGENT,
                    "locale": "en-US",
                    "timezone_id": "America/New_York",
                }
                if proxy:
                    context_kwargs["proxy"] = {"server": proxy}
                context = await browser.new_context(**context_kwargs)
                page = await context.new_page()
                install_route_guard(page)
                if collect_json:
                    page.on("response", lambda r: asyncio.create_task(_on_response(r)))
                await page.goto(url, wait_until="domcontentloaded", timeout=max(wait_ms, 30000))
                with contextlib.suppress(Exception):  # network-idle is best-effort
                    await page.wait_for_load_state("networkidle", timeout=wait_ms)
                if selector:
                    with contextlib.suppress(Exception):  # selector wait is best-effort
                        await page.wait_for_selector(selector, timeout=wait_ms)
                else:
                    await page.wait_for_timeout(min(wait_ms, 5000))
                if collect_json and json_bodies:
                    return json.dumps(json_bodies, ensure_ascii=False)
                content, _ = cap_text(await page.content(), url)
                return content
            finally:
                try:
                    await browser.close()
                except Exception:  # noqa: BLE001 - never-raise guard
                    logger.debug("fetch_rendered_playwright_close_failed", exc_info=True)
    except Exception as e:  # noqa: BLE001 - never-raise guard
        logger.debug("fetch_rendered_playwright_failed", extra={"error": str(e)[:80]})
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
    if _common._HAS_CAMOUFOX and _common.AsyncCamoufox is not None:
        try:
            json_bodies: list[str] = []

            async def _on_response(response: Any) -> None:
                content_type = response.headers.get("content-type", "")
                if "json" not in content_type.lower():
                    return
                try:
                    text, _ = cap_text(await response.text(), str(getattr(response, 'url', '')))
                    json_bodies.append(text)
                except Exception:  # noqa: BLE001 - never-raise guard
                    logger.debug("fetch_rendered_json_capture_failed", exc_info=True)

            async with _common.AsyncCamoufox(headless=True) as browser:
                page = await browser.new_page()
                install_route_guard(page)
                if collect_json:
                    page.on("response", lambda r: asyncio.create_task(_on_response(r)))
                await page.goto(
                    url, wait_until="domcontentloaded", timeout=max(wait_ms, 30000)
                )
                if selector:
                    with contextlib.suppress(Exception):  # selector wait is best-effort
                        await page.wait_for_selector(selector, timeout=wait_ms)
                else:
                    await page.wait_for_timeout(wait_ms)
                if collect_json and json_bodies:
                    return json.dumps(json_bodies, ensure_ascii=False)
                content, _ = cap_text(await page.content(), url)
                return content
        except Exception as e:  # noqa: BLE001 - never-raise guard
            logger.debug("fetch_rendered_camoufox_failed", extra={"error": str(e)[:80]})
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
    renderer = _pick_renderer(prefer)
    try:
        async with asyncio.timeout(_RENDER_TIMEOUT_S):
            if renderer == "camoufox":
                return await _render_with_camoufox(
                    url, wait_ms, selector=selector, proxy=proxy, collect_json=collect_json
                )
            return await _render_with_playwright(
                url, wait_ms, selector=selector, proxy=proxy, collect_json=collect_json
            )
    except TimeoutError:
        logger.warning(
            "fetch_rendered_timeout",
            extra={"url": url, "timeout_s": _RENDER_TIMEOUT_S},
        )
        return None


__all__ = ["fetch_rendered"]
