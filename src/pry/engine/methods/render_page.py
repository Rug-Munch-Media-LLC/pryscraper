"""Render-page driving: navigation, waits and capture for both backends.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

from __future__ import annotations

import contextlib
import json
from dataclasses import dataclass
from typing import Any

from pry.engine.methods import _common
from pry.engine.page_lifecycle import attach_json_collector, cap_page_content


@dataclass
class RenderSpec:
    """One render request: where to go, how long to wait, what to capture."""

    url: str
    wait_ms: int
    selector: str = ""
    collect_json: bool = False
    networkidle: bool = False


def pick_renderer(prefer: str) -> str:
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


async def settle(page: Any, spec: RenderSpec) -> None:
    """Navigate and wait for the page to be usable (best-effort waits)."""
    await page.goto(spec.url, wait_until="domcontentloaded", timeout=max(spec.wait_ms, 30000))
    if spec.networkidle:
        with contextlib.suppress(Exception):  # network-idle is best-effort
            await page.wait_for_load_state("networkidle", timeout=spec.wait_ms)
    if spec.selector:
        with contextlib.suppress(Exception):  # selector wait is best-effort
            await page.wait_for_selector(spec.selector, timeout=spec.wait_ms)
    else:
        bounded = min(spec.wait_ms, 5000) if spec.networkidle else spec.wait_ms
        await page.wait_for_timeout(bounded)


async def drive(page: Any, spec: RenderSpec, json_bodies: list[str]) -> str:
    """Guard, navigate, settle and capture the rendered output."""
    from pry.engine.route_guard import install_route_guard

    install_route_guard(page)
    if spec.collect_json:
        attach_json_collector(page, json_bodies)
    await settle(page, spec)
    if spec.collect_json and json_bodies:
        return json.dumps(json_bodies, ensure_ascii=False)
    return await cap_page_content(page, spec.url)


__all__ = ["RenderSpec", "drive", "pick_renderer", "settle"]
