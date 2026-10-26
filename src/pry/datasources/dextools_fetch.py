# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
"""Rendered fetch for Dextools: rate limit per host, honour Retry-After, type blocks.

Dextools is a client-rendered SPA: the raw HTML is a ~9 KB shell with no data,
so the datasource must render JS before normalizing. This module is the only
network seam; tests inject a fake renderer instead.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

if TYPE_CHECKING:
    from collections.abc import Callable

from pry.datasources.dextools_types import Refusal

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)
MIN_INTERVAL_S = 1.25
_last_hit: dict[str, float] = {}
_CAPTCHA = ("captcha", "cf-challenge", "grecaptcha", "hcaptcha", "Just a moment...")


def _throttle(host: str) -> None:
    elapsed = time.monotonic() - _last_hit.get(host, 0.0)
    if elapsed < MIN_INTERVAL_S:
        time.sleep(MIN_INTERVAL_S - elapsed)
    _last_hit[host] = time.monotonic()


def _playwright_html(url: str, timeout_ms: int) -> str:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as play:
        browser = play.chromium.launch(headless=True, args=["--no-sandbox"])
        try:
            page = browser.new_page(user_agent=USER_AGENT, locale="en-US")
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            page.wait_for_timeout(5000)
            return page.content()
        finally:
            browser.close()


def fetch_rendered(
    url: str,
    *,
    timeout_ms: int = 45_000,
    renderer: Callable[[str, int], str] | None = None,
) -> str | Refusal:
    """Render ``url`` and return HTML, or a typed refusal (never a silent empty page)."""
    _throttle(urlsplit(url).netloc)
    try:
        page_html = (renderer or _playwright_html)(url, timeout_ms)
    except Exception as exc:  # noqa: BLE001 - any transport failure is "unavailable"
        detail = str(exc).splitlines()[0][:200] if str(exc) else type(exc).__name__
        retry = _retry_after(exc)
        if retry:
            detail = f"{detail} (Retry-After: {retry})"
        return Refusal(code="unavailable", reason="render failed", detail=detail)
    lowered = page_html.lower()
    if any(marker in lowered for marker in _CAPTCHA):
        return Refusal(code="blocked.captcha", reason="captcha challenge served", detail=url)
    return page_html


def _retry_after(exc: BaseException) -> str | None:
    text = str(exc)
    for marker in ("Retry-After:", "retry after"):
        if marker.lower() in text.lower():
            return text[text.lower().index(marker.lower()) + len(marker) :].strip().split()[0]
    return None
