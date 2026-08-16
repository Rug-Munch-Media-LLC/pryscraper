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
from captcha.token_api import solve_2captcha, solve_capsolver
from settings import settings


class RecaptchaV3Provider(CaptchaProvider):
    """Solve reCAPTCHA v3 via 2captcha-compatible or Capsolver API."""

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
        if settings.captcha_2captcha_api_key:
            token = await solve_2captcha(
                settings.captcha_2captcha_api_key,
                "recaptcha_v3",
                sitekey=sitekey,
                url=url,
                extra={"action": action, "min_score": min_score},
            )
            if token:
                return token
        if settings.captcha_capsolver_api_key:
            return await solve_capsolver(
                settings.captcha_capsolver_api_key,
                "ReCaptchaV3Task",
                sitekey=sitekey,
                url=url,
                extra={"pageAction": action, "minScore": min_score},
            )
        return None


register(RecaptchaV3Provider())
