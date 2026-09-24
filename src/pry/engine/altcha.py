"""Pry — solve Mojeek's Altcha proof-of-work widget.

The widget ignores synthetic clicks: it only starts on a *trusted* pointer
event. A real ``page.mouse.down/up`` on the checkbox lets it solve its own
PoW. Its verification navigates, destroying the JS execution context, so the
resulting exception is the success signal rather than a failure.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_CHECKBOX = ".altcha-checkbox-wrap"


async def solve_altcha(page: object, attempts: int = 20) -> bool:
    """Click the widget and wait for verification. Never raises.

    Returns True when the widget verified (or navigated away, which only
    happens after a successful post).
    """
    box = await page.query_selector(_CHECKBOX)  # type: ignore[attr-defined]
    if not box:
        return False
    bounds = await box.bounding_box()  # type: ignore[attr-defined]
    if not bounds:
        return False
    await page.mouse.move(  # type: ignore[attr-defined]
        bounds["x"] + bounds["width"] / 2, bounds["y"] + bounds["height"] / 2
    )
    await page.mouse.down()  # type: ignore[attr-defined]
    await page.wait_for_timeout(150)  # type: ignore[attr-defined]
    await page.mouse.up()  # type: ignore[attr-defined]
    for _ in range(attempts):
        await page.wait_for_timeout(1500)  # type: ignore[attr-defined]
        try:
            state = await page.evaluate(  # type: ignore[attr-defined]
                "()=>document.querySelector('.altcha')?.getAttribute('data-state')"
            )
        except Exception:  # noqa: BLE001 - navigation IS the success path
            logger.debug("altcha_verified_by_navigation")
            return True
        if state in ("verified", None):
            return True
    return False


__all__ = ["solve_altcha"]
