"""Pry — reCAPTCHA v3 provider.

Solves reCAPTCHA v3 via 2captcha-style or Capsolver APIs. v3 requires an
``action`` and a minimum score; sensible defaults are used when the
caller does not provide them.
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


class RecaptchaV3Provider(CaptchaProvider):
    """Solve reCAPTCHA v3 via multi-provider fallback chain."""

    captcha_type = "recaptcha_v3"
    DEFAULT_ACTION = "verify"
    DEFAULT_MIN_SCORE = 0.3

    async def solve(
        self,
        *,
        sitekey: str | None = None,
        url: str | None = None,
        action: str | None = None,
        min_score: float | None = None,
        **_: Any,
    ) -> str | None:
        if not sitekey or not url:
            return None
        action = action or self.DEFAULT_ACTION
        min_score = min_score if min_score is not None else self.DEFAULT_MIN_SCORE
        return await solve_token_with_fallback(
            "recaptcha_v3",
            sitekey=sitekey,
            url=url,
            extra={"action": action, "min_score": min_score},
            captcha_action=action,
            min_score=min_score,
        )


register(RecaptchaV3Provider())
