"""Pry — solve a CAPTCHA/challenge that block_detector just reported.

This is the wiring seam: a caller that already holds the response (html,
status, headers) hands it here; when ``block_detection`` classifies it as a
captcha/challenge and solving is enabled, the ladder runs. Robots-disallowed
URLs return ``blocked.robots`` with zero solver attempts.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import re

from pry.core.settings import settings
from pry.engine.block_detection import detect_block
from pry.engine.captcha.ladder import solve_ladder
from pry.engine.captcha.lanes import Challenge

_SOLVABLE_KINDS = {"captcha", "cloudflare", "js_required"}
_SITEKEY_RE = re.compile(r'data-sitekey=["\']([^"\']+)', re.IGNORECASE)
_V3_MARKERS = ("grecaptcha.execute", "recaptcha/api.js?render=", "grecaptcha.ready")


def classify_captcha(html: str | None) -> tuple[str | None, str | None]:
    """Infer (captcha_type, sitekey) from page markup."""
    text = html or ""
    lowered = text.lower()
    match = _SITEKEY_RE.search(text)
    sitekey = match.group(1) if match else None
    if "cf-turnstile" in lowered or "challenges.cloudflare.com/turnstile" in lowered:
        return "turnstile", sitekey
    if "h-captcha" in lowered or "hcaptcha.com" in lowered:
        return "hcaptcha", sitekey
    if any(marker in lowered for marker in _V3_MARKERS):
        return "recaptcha_v3", sitekey
    if "g-recaptcha" in lowered or "recaptcha" in lowered:
        return "recaptcha_v2", sitekey
    return None, sitekey


async def maybe_solve_challenge(
    url: str,
    html: str | None,
    status_code: int = 200,
    headers: dict[str, str] | None = None,
) -> dict[str, object] | None:
    """Run the ladder when ``block_detection`` reports a solvable challenge."""
    if not settings.captcha_enabled:
        return None
    signal = detect_block(html=html or "", status=status_code, headers=headers)
    if signal.kind not in _SOLVABLE_KINDS:
        return None
    captcha_type, sitekey = classify_captcha(html)
    challenge = Challenge(url=url, html=html, captcha_type=captcha_type, sitekey=sitekey)
    result = await solve_ladder(challenge)
    return {"block_kind": signal.kind, **result.as_dict()}
