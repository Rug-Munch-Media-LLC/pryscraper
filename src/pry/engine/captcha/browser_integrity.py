"""Pry — T5: browser-integrity last resort.

For Turnstile-class walls that only a real browser can clear, drive a patched
Chromium (patchright, nodriver fallback) with human-ish pointer movement. The
rung is time-boxed by the ladder and answers ``blocked.captcha_unsolved`` with
the CAPTCHA class it could not clear — it never hangs and never claims success
without clearance evidence.

Both engines are optional: absent -> ``capability()`` False -> the ladder
reports ``unavailable.browser``.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

import asyncio
import json
import os
import random

from pry.engine.captcha.flaresolverr import looks_unsolved

_JITTER = random.SystemRandom()

CHROME_ENV = "PRY_CHROME_PATH"
CHROME_CANDIDATES = (
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
    "/usr/bin/google-chrome",
)


def _engine() -> str | None:
    """Return the importable browser engine name, if any."""
    for name in ("patchright", "nodriver"):
        try:
            __import__(name)
        except ImportError:
            continue
        return name
    return None


def chrome_path() -> str | None:
    """Locate a Chromium binary the engine can drive."""
    override = os.environ.get(CHROME_ENV, "")
    if override and os.path.exists(override):
        return override
    return next((p for p in CHROME_CANDIDATES if os.path.exists(p)), None)


def capability() -> bool:
    """True when both a browser engine and a binary are available."""
    return _engine() is not None and chrome_path() is not None


async def _drive(url: str, engine: str, timeout_s: float) -> str:
    """Load the page and nudge it with human-ish motion; return the HTML."""
    if engine == "patchright":
        from patchright.async_api import async_playwright
    else:
        from nodriver import start

    if engine != "patchright":
        browser = await start(headless=True, browser_executable_path=chrome_path())
        page = await browser.get(url)
        await asyncio.sleep(min(2.0, timeout_s))
        html = await page.get_content()
        return html or ""

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True, executable_path=chrome_path())
        page = await browser.new_page()
        await page.goto(url, timeout=timeout_s * 1000, wait_until="domcontentloaded")
        for _ in range(6):
            await page.mouse.move(_JITTER.uniform(40, 400), _JITTER.uniform(40, 400), steps=8)
            await asyncio.sleep(0.25)
        html = await page.content()
        await browser.close()
        return html or ""


async def solve_browser(
    url: str, captcha_class: str, timeout_s: float = 45.0
) -> tuple[str | None, str]:
    """Human-ish clearance attempt -> (token, reason)."""
    if not url:
        return None, "not_applicable"
    engine = _engine()
    if engine is None or chrome_path() is None:
        return None, "unavailable.browser"
    try:
        async with asyncio.timeout(timeout_s):
            html = await _drive(url, engine, timeout_s)
    except TimeoutError:
        return None, "timeout"
    except (OSError, RuntimeError, ValueError):
        return None, "failed"
    if looks_unsolved(html):
        return None, f"blocked.captcha_unsolved class={captcha_class}"
    return json.dumps({"html": len(html), "engine": engine}), "solved"
