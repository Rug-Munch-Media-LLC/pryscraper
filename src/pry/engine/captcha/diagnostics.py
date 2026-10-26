"""Pry — CAPTCHA ladder diagnostics.

``captcha_diagnostics()`` is the single truthful answer to "can we solve right
now?": which lanes exist, which token providers are unavailable for lack of a
key, and where to provision one. Missing keys are reported loudly, never
silently swallowed.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import os

from pry.core.settings import settings
from pry.engine.captcha.flaresolverr import LOOPBACK_FALLBACKS
from pry.engine.captcha.keys import CAPTCHA_ENV_FILE, load_captcha_keys, missing_token_keys
from pry.engine.captcha.ladder import LADDER_ORDER
from pry.engine.captcha.registry import REGISTRY


def captcha_diagnostics() -> dict[str, object]:
    """Return the ladder state, missing keys and provisioning path."""
    load_captcha_keys()
    missing = missing_token_keys()
    available = sorted(REGISTRY)
    free_lanes = ["flaresolverr", "image"]
    return {
        "enabled": bool(settings.captcha_enabled),
        "ladder": list(LADDER_ORDER),
        "available_providers": available,
        "free_lanes": free_lanes,
        "token_providers_unavailable": missing,
        "keys_file": str(CAPTCHA_ENV_FILE),
        "keys_file_present": CAPTCHA_ENV_FILE.is_file(),
        "flaresolverr_url": settings.flaresolverr_url,
        "flaresolverr_fallbacks": list(LOOPBACK_FALLBACKS),
        "ocr_backend": os.environ.get("PRY_CAPTCHA_OCR_BACKEND", "pytesseract"),
        "max_seconds": settings.captcha_max_seconds,
    }
