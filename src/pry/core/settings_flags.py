"""Pry — feature flag / toggle settings (split from settings.py).

Mixin holding boolean feature toggles: CAPTCHA enablement, stealth browser
flags, IP rotation mode, and output toggles. Combined into `PrySettings` in
`pry.core.settings`.

Pure code move — no config values or logic changed.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

from pydantic import AliasChoices, Field


class FlagsSettings:
    """Boolean feature toggles and behavior switches."""

    # CAPTCHA solving ladder (see captcha/ package). ON by default: the
    # directive is to solve when a challenge blocks the content; the only
    # refusals are robots-disallowed paths and paid/logged-in APIs.
    captcha_enabled: bool = Field(
        default=True,
        validation_alias=AliasChoices("PRY_CAPTCHA_ENABLED", "CAPTCHA_ENABLED"),
    )
    # Whole-ladder wall clock budget in seconds.
    captcha_max_seconds: float = Field(
        default=60.0,
        validation_alias=AliasChoices("PRY_CAPTCHA_MAX_SECONDS", "CAPTCHA_MAX_SECONDS"),
    )

    # IP rotation mode (legacy env alias): "off" | "per_request" | ...
    ip_rotation: str = Field(
        default="off",
        validation_alias=AliasChoices("PRY_IP_ROTATION", "IP_ROTATION"),
    )

    # Stealth
    webdriver_override: bool = True
    canvas_noise: bool = True
    webrtc_disable: bool = True
    geolocation_spoof: bool = True

    # Output
    include_links: bool = True
