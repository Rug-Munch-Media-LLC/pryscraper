"""Pry — Browser actions engine (Firecrawl-style pre-extraction interactions).

Before extracting content, callers can specify a sequence of actions to
perform on the page — click elements, scroll, type text, wait for elements,
press keys, run JS, and more. This lets you interact with dynamic pages
(login forms, cookie banners, infinite scroll, expandable sections) before
scraping.

Design contract:
- Async functions, never raise. ``execute_actions`` returns ``{}`` on failure;
  ``execute_action`` returns ``False`` on failure.
- Uses the shared process-level Playwright browser from
  ``pry.engine.browser_pool`` — one browser launch per process, isolated
  context per call.
"""

# SPDX-License-Identifier: BSL-1.1
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — Stealth / Anti-Detection Module
# Licensed under Business Source License 1.1 — see LICENSE-BSL-STEALTH.
# Change Date: 2029-01-01 (converts to MIT).

from __future__ import annotations

import asyncio
import base64
import contextlib
import importlib.util
import logging
from typing import Any

from pry.engine.browser_pool import get_browser_pool
from pry.engine.url_guard import validate_url

_has_markdownify = importlib.util.find_spec("markdownify") is not None

__all__ = ["execute_action", "execute_actions"]

logger = logging.getLogger(__name__)

# Per-action timeout (seconds) — a single stuck action must not hang the chain.
_ACTION_TIMEOUT = 10.0
# Default wait after navigation before running actions (seconds).
_NAV_SETTLE = 1.0
# Hard cap on actions per call (abuse guard).
_MAX_ACTIONS = 50


async def execute_actions(url: str, actions: list[dict], extract_after: bool = True) -> dict:
    """Navigate to ``url``, run a sequence of browser actions, then extract.

    Returns ``{"url", "actions_executed", "content", "markdown", "title",
    "screenshot" (if requested)}`` or ``{}`` on any failure. Never raises.
    """
    try:
        validate_url(url)
    except Exception as e:  # noqa: BLE001 — contract: never raise
        logger.debug("actions_url_rejected", extra={"url": url, "error": str(e)[:120]})
        return {}

    if not isinstance(actions, list) or not actions:
        return {}
    actions = actions[:_MAX_ACTIONS]

    pool = get_browser_pool()
    try:
        browser = await pool.get_playwright_browser()
    except Exception as e:  # noqa: BLE001
        logger.debug("actions_browser_unavailable", extra={"error": str(e)[:120]})
        return {}

    context = None
    try:
        context = await browser.new_context()
        page = await context.new_page()
        await page.goto(url, timeout=30_000, wait_until="domcontentloaded")
        await asyncio.sleep(_NAV_SETTLE)

        executed = 0
        screenshot_b64: str | None = None
        for action in actions:
            if not isinstance(action, dict):
                continue
            if await execute_action(page, action):
                executed += 1
            if action.get("type") == "screenshot" and screenshot_b64 is None:
                with contextlib.suppress(Exception):
                    raw = await page.screenshot(full_page=True)
                    screenshot_b64 = base64.b64encode(raw).decode()

        result: dict[str, Any] = {
            "url": url,
            "actions_executed": executed,
        }

        if extract_after:
            html = await page.content()
            result["content"] = await page.inner_text("body")
            result["title"] = await page.title()
            if _has_markdownify:
                with contextlib.suppress(Exception):
                    from markdownify import markdownify

                    result["markdown"] = markdownify(
                        html, heading_arrows=False, strip=["script", "style"]
                    )
            else:
                result["markdown"] = result["content"]
            result["html"] = html
        if screenshot_b64 is not None:
            result["screenshot"] = screenshot_b64
        return result
    except Exception as e:  # noqa: BLE001 — contract: never raise
        logger.debug("actions_execute_failed", extra={"url": url, "error": str(e)[:200]})
        return {}
    finally:
        if context is not None:
            with contextlib.suppress(Exception):
                await context.close()


async def execute_action(page: Any, action: dict) -> bool:
    """Execute a single browser action on a Playwright page.

    Supported action types: click, type, scroll, wait (selector or ms),
    press, screenshot, evaluate, select, check, uncheck, hover, focus.
    Returns ``True`` on success, ``False`` on any failure. Never raises.
    """
    if not isinstance(action, dict):
        return False
    action_type = action.get("type")
    selector = action.get("selector")

    try:
        if action_type == "click":
            if not selector:
                return False
            await page.click(selector, timeout=_ACTION_TIMEOUT * 1000)
            return True

        if action_type == "type":
            if not selector or "text" not in action:
                return False
            await page.fill(selector, str(action["text"]), timeout=_ACTION_TIMEOUT * 1000)
            return True

        if action_type == "scroll":
            direction = action.get("direction", "down")
            amount = int(action.get("amount", 500))
            sign = -1 if direction == "up" else 1
            await page.evaluate(f"window.scrollBy(0, {sign * amount})")
            return True

        if action_type == "wait":
            if action.get("selector"):
                await page.wait_for_selector(action["selector"], timeout=_ACTION_TIMEOUT * 1000)
                return True
            if "ms" in action:
                ms = min(int(action["ms"]), 30_000)
                await asyncio.sleep(ms / 1000)
                return True
            return False

        if action_type == "press":
            key = action.get("key")
            if not key:
                return False
            await page.keyboard.press(str(key))
            return True

        if action_type == "screenshot":
            await page.screenshot(full_page=True)
            return True

        if action_type == "evaluate":
            script = action.get("script")
            if not script:
                return False
            await page.evaluate(script)
            return True

        if action_type == "select":
            if not selector or "value" not in action:
                return False
            await page.select_option(selector, str(action["value"]), timeout=_ACTION_TIMEOUT * 1000)
            return True

        if action_type == "check":
            if not selector:
                return False
            await page.check(selector, timeout=_ACTION_TIMEOUT * 1000)
            return True

        if action_type == "uncheck":
            if not selector:
                return False
            await page.uncheck(selector, timeout=_ACTION_TIMEOUT * 1000)
            return True

        if action_type == "hover":
            if not selector:
                return False
            await page.hover(selector, timeout=_ACTION_TIMEOUT * 1000)
            return True

        if action_type == "focus":
            if not selector:
                return False
            await page.focus(selector, timeout=_ACTION_TIMEOUT * 1000)
            return True

        return False
    except Exception as e:  # noqa: BLE001 — contract: never raise
        logger.debug(
            "action_failed",
            extra={"type": str(action_type), "error": str(e)[:120]},
        )
        return False
