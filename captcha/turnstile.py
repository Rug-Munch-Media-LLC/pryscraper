"""Pry — Cloudflare Turnstile provider.

Solves Turnstile via a pluggable 2captcha-style API or Capsolver.
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
from captcha.token_api import solve_2captcha, solve_capsolver
from settings import settings


class TurnstileProvider(CaptchaProvider):
    """Solve Cloudflare Turnstile via 2captcha-compatible or Capsolver API."""

    captcha_type = "turnstile"

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
                "turnstile",
                sitekey=sitekey,
                url=url,
            )
            if token:
                return token
        if settings.captcha_capsolver_api_key:
            return await solve_capsolver(
                settings.captcha_capsolver_api_key,
                "TurnstileTask",
                sitekey=sitekey,
                url=url,
            )
        return None


register(TurnstileProvider())
