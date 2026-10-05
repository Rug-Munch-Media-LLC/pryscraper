"""Pry — Camoufox page-fetch mechanics.

Shared page-level navigation for the pooled, explicit-pooled and fresh
browser paths: install the SSRF route guard, inject cookies, navigate, wait,
then collect title / HTML / cookies. Kept free of browser lifecycle so the
pooling concern lives in the facade.
"""

# SPDX-License-Identifier: BSL-1.1
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — Stealth / Anti-Detection Module
# Licensed under Business Source License 1.1 — see LICENSE-BSL-STEALTH.
# Change Date: 2029-01-01 (converts to MIT).

from __future__ import annotations

import contextlib
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

#: A Playwright route handler (``CamoufoxBrowser._guarded_route``).
RouteGuard = Callable[[Any], Awaitable[None]]


@dataclass(frozen=True)
class FetchSpec:
    """Per-request navigation parameters."""

    url: str
    profile_name: str
    wait_selector: str = ""
    wait_time: int = 3000
    cookies: list[dict] | None = None


async def fetch_page(page: Any, spec: FetchSpec, route_guard: RouteGuard) -> dict[str, Any]:
    """Navigate ``page`` to ``spec.url`` and return a structured result."""
    start = time.time()
    # Route guard re-validates every request, including internal redirect
    # hops the browser follows on its own.
    await page.route("**/*", route_guard)
    if spec.cookies:
        for cookie in spec.cookies:
            await page.context.add_cookies([cookie])
    await page.goto(spec.url, wait_until="domcontentloaded")
    if spec.wait_selector:
        with contextlib.suppress(Exception):
            await page.wait_for_selector(spec.wait_selector, timeout=spec.wait_time)
    else:
        await page.wait_for_timeout(spec.wait_time)
    content = await page.content()
    title = await page.title()
    cookies_received = await page.context.cookies()
    return {
        "success": True,
        "url": spec.url,
        "title": title,
        "content": content,
        "raw_html": content,
        "status_code": 200,
        "elapsed": round(time.time() - start, 2),
        "profile": spec.profile_name,
        "cookies": cookies_received,
    }
