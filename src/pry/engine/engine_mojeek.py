"""Pry — Mojeek search engine.

The only engine gated by an Altcha proof-of-work widget, so it needs a real
browser and a trusted click; see :mod:`pry.engine.altcha`. Mojeek
re-challenges under rapid querying, so a captcha on arrival triggers one
retry after a settle.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import quote_plus

from pry.engine.altcha import solve_altcha

logger = logging.getLogger(__name__)

_MOJEEK_URL = "https://www.mojeek.com/search?q={q}"
_SKIP = re.compile(r"mojeek\.com|\.css|\.js|\.png|\.svg|\.ico", re.I)
_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)
_SETTLE_MS = 9000
_GOTO = {"wait_until": "domcontentloaded"}


async def _settled_html(page: Any, url: str) -> str:
    """Reload once if Mojeek re-challenged us for querying too fast."""
    await page.goto(url, timeout=45000, **_GOTO)
    await page.wait_for_timeout(3000)
    return await page.content()


async def search_mojeek(query: str, num_results: int) -> list[dict[str, Any]]:
    """Search Mojeek, solving its Altcha gate. Returns [] on any failure."""
    try:
        from playwright.async_api import async_playwright
    except Exception as exc:  # noqa: BLE001 - optional dependency
        logger.debug("mojeek_playwright_missing", extra={"error": str(exc)})
        return []
    url = _MOJEEK_URL.format(q=quote_plus(query))
    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
            )
            try:
                ctx = await browser.new_context(
                    user_agent=_UA, locale="en-US", viewport={"width": 1400, "height": 900}
                )
                page = await ctx.new_page()
                await page.goto(url, timeout=60000, **_GOTO)
                await page.wait_for_timeout(2500)
                if await solve_altcha(page):
                    html = await _settled_html(page, url)
                else:
                    html = await page.content()
            finally:
                await browser.close()
    except Exception as exc:  # noqa: BLE001 - never raise
        logger.debug("mojeek_search_failed", extra={"error": str(exc)})
        return []
    return _rows(html, num_results)


def _rows(html: str, num_results: int) -> list[dict[str, Any]]:
    """Harvest result anchors, dropping Mojeek's own chrome."""
    links = re.findall(r'<a[^>]+class="ob"[^>]+href="(https?://[^"]+)"', html, re.I)
    if not links:
        links = re.findall(r'<h2><a[^>]+href="(https?://[^"]+)"', html, re.I)
    out: list[dict[str, Any]] = []
    for href in links:
        if _SKIP.search(href):
            continue
        out.append({"url": href, "title": "", "snippet": ""})
        if len(out) >= num_results:
            break
    return out


__all__ = ["search_mojeek"]
