"""Pry — Camoufox launch-profile catalog.

The profile catalog maps a human-readable profile name to the Camoufox
launch arguments (``os`` / ``browser`` / ``screen`` / ``window``) used to
build a fresh anti-detection Firefox. Kept separate from the fetching
machinery so profile data can be inspected and tested in isolation.
"""

# SPDX-License-Identifier: BSL-1.1
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — Stealth / Anti-Detection Module
# Licensed under Business Source License 1.1 — see LICENSE-BSL-STEALTH.
# Change Date: 2029-01-01 (converts to MIT).

from __future__ import annotations

from typing import Any

#: Profile used when the requested profile name is unknown.
FALLBACK_PROFILE = "chrome_windows"

#: Launch-argument catalog keyed by profile name.
DEFAULT_CONFIGS: dict[str, dict[str, Any]] = {
    "chrome_windows": {
        "headless": True,
        "os": "windows",
        "browser": "chrome",
        "screen": (1920, 1080),
        "window": (1920, 1080),
    },
    "firefox_windows": {
        "headless": True,
        "os": "windows",
        "browser": "firefox",
        "screen": (1920, 1080),
        "window": (1920, 1080),
    },
    "chrome_mac": {
        "headless": True,
        "os": "macos",
        "browser": "chrome",
        "screen": (2560, 1600),
        "window": (1440, 900),
    },
    "firefox_linux": {
        "headless": True,
        "os": "linux",
        "browser": "firefox",
        "screen": (1920, 1080),
        "window": (1920, 1080),
    },
}


def resolve_config(profile_name: str) -> dict[str, Any]:
    """Return a copy of the launch config for ``profile_name``.

    Unknown profile names fall back to :data:`FALLBACK_PROFILE`.
    """
    selected = DEFAULT_CONFIGS.get(profile_name, DEFAULT_CONFIGS[FALLBACK_PROFILE])
    return dict(selected)
