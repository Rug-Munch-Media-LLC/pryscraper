"""Pry — browser pool configuration: Playwright availability + Chromium binary.

Split out of ``browser_pool`` to keep launch configuration separate from pool
lifecycle. Nothing here holds state.
"""

# SPDX-License-Identifier: BSL-1.1
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — Stealth / Anti-Detection Module
# Licensed under Business Source License 1.1 — see LICENSE-BSL-STEALTH.
# Change Date: 2029-01-01 (converts to MIT).

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

_has_playwright = importlib.util.find_spec("playwright") is not None

async_playwright: Any = None
if _has_playwright:
    pass

# The image ships Playwright's Chromium only (no distro ``chromium`` package).
# undetected-chromedriver still needs a concrete binary, so point it at the
# Playwright build instead of a hard-coded /usr/bin/chromium that no longer
# exists. A distro path still wins when present (local/dev images).
_PLAYWRIGHT_CHROMIUM = tuple(
    str(p)
    for pattern in ("chromium-*/chrome-linux64/chrome", "chromium-*/chrome-linux/chrome")
    for p in sorted(Path("/ms-playwright").glob(pattern), reverse=True)
)


def chromium_binary() -> str | None:
    """Return the first usable Chromium executable, or None."""
    for candidate in ("/usr/bin/chromium", "/usr/bin/chromium-browser", *_PLAYWRIGHT_CHROMIUM):
        if Path(candidate).is_file():
            return candidate
    return None
