"""Shared browser/page lifecycle: timeouts, close, body caps, JSON capture.

Both the Camoufox integration and the render tier use this module so page
cleanup, wall-clock ceilings and response caps have a single implementation.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

from pry.engine.body_limits import cap_text

logger = logging.getLogger(__name__)

#: Wall-clock ceiling for one browser fetch. camoufox's ``page.goto`` carries
#: no timeout, so a hung navigation would otherwise pin the worker forever.
BROWSER_TIMEOUT_S = 90.0

#: Wall-clock ceiling for one render. A hung browser otherwise pins the
#: worker forever; the tier contract turns the timeout into a None failure.
RENDER_TIMEOUT_S = 120.0


async def close_page(page: Any) -> None:
    """Close a page, swallowing teardown errors (never raises)."""
    with contextlib.suppress(Exception):
        await page.close()


async def close_browser(browser: Any) -> None:
    """Close a browser, logging teardown errors instead of raising."""
    try:
        await browser.close()
    except Exception:  # noqa: BLE001 - never-raise guard
        logger.debug("browser_cleanup_failed", exc_info=True)


@asynccontextmanager
async def open_page(browser: Any) -> AsyncIterator[Any]:
    """Open a page on ``browser`` and always close it afterwards."""
    page = await browser.new_page()
    try:
        yield page
    finally:
        await close_page(page)


@asynccontextmanager
async def closing_browser(browser: Any) -> AsyncIterator[Any]:
    """Yield a browser and close it on exit (never raises on close)."""
    try:
        yield browser
    finally:
        await close_browser(browser)


async def run_bounded(seconds: float, factory: Callable[[], Awaitable[Any]]) -> Any:
    """Await ``factory()`` under a wall-clock ceiling."""
    async with asyncio.timeout(seconds):
        return await factory()


def cap_document(result: dict[str, Any], url: str) -> bool:
    """Cap ``content``/``raw_html`` in ``result``; True when anything was cut."""
    truncated = False
    for key in ("content", "raw_html"):
        value = result.get(key)
        if not isinstance(value, str):
            continue
        capped, dropped = cap_text(value, url)
        if dropped:
            result[key] = capped
            truncated = True
    if truncated:
        result["truncated"] = True
    return truncated


async def cap_page_content(page: Any, url: str) -> str:
    """Return ``page.content()`` capped at the shared response limit."""
    content, _ = cap_text(await page.content(), url)
    return content


def attach_json_collector(page: Any, sink: list[str]) -> None:
    """Collect JSON response bodies from ``page`` into ``sink`` (best-effort)."""

    async def _on_response(response: Any) -> None:
        content_type = response.headers.get("content-type", "")
        if "json" not in content_type.lower():
            return
        try:
            text, _ = cap_text(await response.text(), str(getattr(response, "url", "")))
            sink.append(text)
        except Exception:  # noqa: BLE001 - never-raise guard
            logger.debug("fetch_rendered_json_capture_failed", exc_info=True)

    page.on("response", lambda r: asyncio.create_task(_on_response(r)))


__all__ = [
    "BROWSER_TIMEOUT_S",
    "RENDER_TIMEOUT_S",
    "attach_json_collector",
    "cap_document",
    "cap_page_content",
    "close_browser",
    "close_page",
    "closing_browser",
    "open_page",
    "run_bounded",
]
