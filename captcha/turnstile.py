# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Pry — Cloudflare Turnstile provider.

Solves Turnstile via multi-provider fallback chain (2captcha → capsolver → deathbycaptcha → nextcaptcha).
Returns None when no API key is configured.
"""

from __future__ import annotations

from typing import Any

from captcha.base import CaptchaProvider
from captcha.registry import register
from captcha.token_api import solve_token_with_fallback


class TurnstileProvider(CaptchaProvider):
    """Solve Cloudflare Turnstile via multi-provider fallback chain."""

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
        return await solve_token_with_fallback(
            "turnstile",
            sitekey=sitekey,
            url=url,
        )


register(TurnstileProvider())
