"""Pry — hCaptcha provider.

Solves hCaptcha via a pluggable 2captcha-style API or Capsolver.
Returns None when no API key is configured.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

from typing import Any

from captcha.base import CaptchaProvider
from captcha.registry import register
from captcha.token_api import solve_token_with_fallback


class HCaptchaProvider(CaptchaProvider):
    """Solve hCaptcha via multi-provider fallback chain."""

    captcha_type = "hcaptcha"

    async def solve(
        self,
        *,
        sitekey: str | None = None,
        url: str | None = None,
        **_: Any,
    ) -> str | None:
        if not sitekey or not url:
            return None
        return await solve_token_with_fallback(
            "hcaptcha",
            sitekey=sitekey,
            url=url,
        )


register(HCaptchaProvider())
