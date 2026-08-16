"""Pry — reCAPTCHA v2 provider.

Solves reCAPTCHA v2 via a pluggable 2captcha-style API (when
``PRY_CAPTCHA_2CAPTCHA_API_KEY`` is set) or Capsolver (when
``PRY_CAPTCHA_CAPSOLVER_API_KEY`` is set). Returns None when no API key
is configured — keys are never hardcoded.
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


class RecaptchaV2Provider(CaptchaProvider):
    """Solve reCAPTCHA v2 via 2captcha-compatible or Capsolver API."""

    captcha_type = "recaptcha_v2"

    async def solve(
        self,
        *,
        sitekey: str | None = None,
        url: str | None = None,
        **_: Any,
    ) -> str | None:
        if not sitekey or not url:
            return None
        if settings.captcha_2captcha_api_key:
            token = await solve_2captcha(
                settings.captcha_2captcha_api_key,
                "userrecaptcha",
                sitekey=sitekey,
                url=url,
            )
            if token:
                return token
        if settings.captcha_capsolver_api_key:
            return await solve_capsolver(
                settings.captcha_capsolver_api_key,
                "ReCaptchaV2Task",
                sitekey=sitekey,
                url=url,
            )
        return None


register(RecaptchaV2Provider())
