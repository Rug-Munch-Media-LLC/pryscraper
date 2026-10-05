"""Pry — Camoufox human-behaviour simulation pass.

Runs an optional post-load interaction pass (scrolling, extra wait) in a
fresh browser to make a fetch look more human. Raises on failure so the
caller can record ``human_behavior_error`` rather than silently returning
direct-path HTML.
"""

# SPDX-License-Identifier: BSL-1.1
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — Stealth / Anti-Detection Module
# Licensed under Business Source License 1.1 — see LICENSE-BSL-STEALTH.
# Change Date: 2029-01-01 (converts to MIT).

from __future__ import annotations

import contextlib
import random
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pry.engine.camoufox_page import RouteGuard

# SystemRandom: crypto-grade entropy so human-behavior simulation is unpredictable.
_RNG = random.SystemRandom()


async def apply_human_behavior(
    url: str,
    config: dict[str, Any],
    route_guard: RouteGuard,
    human_behavior: dict[str, Any],
) -> str:
    """Run the human-behaviour pass in a fresh browser and return the HTML.

    The ``camoufox`` import is intentionally local so callers (and tests) can
    redirect it via ``sys.modules`` without importing the optional dependency
    at module load time.
    """
    from camoufox import AsyncCamoufox

    async with AsyncCamoufox(**config) as browser:
        page = await browser.new_page()
        try:
            await page.route("**/*", route_guard)
            await page.goto(url, wait_until="domcontentloaded")
            for scroll_y in human_behavior.get("scroll", []):
                await page.evaluate(f"window.scrollTo(0, {scroll_y})")
                await page.wait_for_timeout(_RNG.randint(200, 800))
            if human_behavior.get("wait_time"):
                await page.wait_for_timeout(human_behavior["wait_time"])
            return await page.content()
        finally:
            with contextlib.suppress(Exception):
                await page.close()
