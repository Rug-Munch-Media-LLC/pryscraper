"""Pry Automator — step handlers.

Each handler mutates ``result`` exactly like the previous inline if/elif branch
in ``run_steps``. Inputs are validated before reaching Playwright.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

import asyncio
import base64
from typing import Any


async def step_navigate(page: Any, step: dict[str, Any], result: dict[str, Any]) -> None:
    url = str(step.get("url", "")).strip()
    if not url or not url.startswith(("http://", "https://", "file://")):
        result["status"] = "error"
        result["error"] = "Invalid URL"
        return
    wait_until = step.get("wait_until", "networkidle")
    timeout = min(int(step.get("timeout", 30000)), 120000)
    await page.goto(url, wait_until=wait_until, timeout=timeout)
    result["url"] = page.url
    result["title"] = await page.title()


async def step_click(page: Any, step: dict[str, Any], result: dict[str, Any]) -> None:
    selector = str(step.get("selector", ""))
    if not selector:
        result["status"] = "error"
        result["error"] = "No selector provided"
        return
    timeout = min(int(step.get("timeout", 10000)), 30000)
    await page.wait_for_selector(selector, timeout=timeout)
    await page.click(selector)


async def step_type(page: Any, step: dict[str, Any], result: dict[str, Any]) -> None:
    selector = str(step.get("selector", ""))
    value = str(step.get("value", ""))
    if not selector:
        result["status"] = "error"
        result["error"] = "No selector provided"
        return
    timeout = min(int(step.get("timeout", 10000)), 30000)
    await page.wait_for_selector(selector, timeout=timeout)
    await page.fill(selector, value)


async def step_select(page: Any, step: dict[str, Any], result: dict[str, Any]) -> None:
    selector = str(step.get("selector", ""))
    value = str(step.get("value", ""))
    if selector:
        await page.select_option(selector, value)
    else:
        result["status"] = "error"
        result["error"] = "No selector"


async def step_wait(page: Any, step: dict[str, Any], result: dict[str, Any]) -> None:
    ms = max(100, min(int(step.get("timeout", 2000)), 60000))
    await asyncio.sleep(ms / 1000)


async def step_wait_for_selector(page: Any, step: dict[str, Any], result: dict[str, Any]) -> None:
    selector = str(step.get("selector", ""))
    if selector:
        timeout = min(int(step.get("timeout", 30000)), 60000)
        await page.wait_for_selector(selector, timeout=timeout)
    else:
        result["status"] = "error"
        result["error"] = "No selector"


async def step_screenshot(page: Any, step: dict[str, Any], result: dict[str, Any]) -> None:
    full_page = bool(step.get("full_page", True))
    screenshot_bytes = await page.screenshot(full_page=full_page)
    result["screenshot"] = base64.b64encode(screenshot_bytes).decode()


async def step_extract(page: Any, step: dict[str, Any], result: dict[str, Any]) -> None:
    selector = str(step.get("selector", ""))
    extract_type = step.get("extract", "text")
    attribute = step.get("attribute")
    if not selector:
        result["status"] = "error"
        result["error"] = "No selector"
    else:
        elements = await page.query_selector_all(selector)
        if extract_type == "text":
            result["texts"] = [await el.inner_text() for el in elements]
        elif extract_type == "html":
            result["htmls"] = [await el.inner_html() for el in elements]
        elif extract_type == "attribute" and attribute:
            result["values"] = [await el.get_attribute(attribute) for el in elements]
    result["title"] = await page.title()
    result["url"] = page.url


async def step_scroll(page: Any, step: dict[str, Any], result: dict[str, Any]) -> None:
    dx = int(step.get("dx", 0))
    dy = int(step.get("dy", 500))
    # Scroll values are safely cast to int — no injection possible
    await page.evaluate(f"window.scrollBy({dx}, {dy})")
    await asyncio.sleep(0.3)


async def step_submit(page: Any, step: dict[str, Any], result: dict[str, Any]) -> None:
    selector = str(step.get("selector", ""))
    if selector:
        await page.wait_for_selector(selector, timeout=5000)
        await page.click(selector)
    else:
        await page.keyboard.press("Enter")


async def step_evaluate(page: Any, step: dict[str, Any], result: dict[str, Any]) -> None:
    js = str(step.get("script", ""))
    if js:
        result["return"] = await page.evaluate(js)
    else:
        result["status"] = "error"
        result["error"] = "No script provided"
