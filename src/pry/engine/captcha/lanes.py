"""Pry — individual lanes of the CAPTCHA ladder.

``run_stage`` dispatches one lane by name; each lane is a small function that
returns a :class:`LaneOutcome`. Free lanes (flaresolverr, image OCR) never need
a key; paid lanes report ``no_key`` when nothing is provisioned.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

from dataclasses import dataclass

from pry.core.settings import settings
from pry.engine.captcha.flaresolverr import flaresolverr_fetch, looks_unsolved
from pry.engine.captcha.registry import REGISTRY
from pry.engine.captcha.token_api import solve_2captcha, solve_capsolver

#: captcha_type -> (2captcha method, capsolver task type)
TOKEN_METHODS: dict[str, tuple[str, str]] = {
    "recaptcha_v2": ("userrecaptcha", "ReCaptchaV2Task"),
    "recaptcha_v3": ("recaptcha_v3", "ReCaptchaV3Task"),
    "hcaptcha": ("hcaptcha", "HCaptchaTask"),
    "turnstile": ("turnstile", "TurnstileTask"),
}


@dataclass(frozen=True, slots=True)
class Challenge:
    """Everything a solver lane may need about one blocked response."""

    url: str
    html: str | None = None
    captcha_type: str | None = None
    sitekey: str | None = None
    image: bytes | str | None = None


@dataclass(slots=True)
class LaneOutcome:
    """Result of one lane: solved or why not."""

    outcome: str
    kind: str
    token: str | None = None
    html: str | None = None
    detail: str = ""


async def _flare(challenge: Challenge, remaining: float) -> LaneOutcome:
    solution = await flaresolverr_fetch(challenge.url, remaining)
    if solution.ok and not looks_unsolved(solution.html):
        return LaneOutcome("solved", "js", token=solution.token, html=solution.html)
    return LaneOutcome("unsolved" if solution.ok else solution.error or "failed", "js")


async def _image(challenge: Challenge, _remaining: float) -> LaneOutcome:
    provider = REGISTRY.get("image")
    if not challenge.image or provider is None:
        return LaneOutcome("no_input", "image")
    text = await provider.solve(image=challenge.image)
    return LaneOutcome("solved", "image", token=text) if text else LaneOutcome("unsolved", "image")


async def _paid(stage: str, challenge: Challenge, _remaining: float) -> LaneOutcome:
    kind = challenge.captcha_type or "token"
    if challenge.captcha_type not in TOKEN_METHODS or not challenge.sitekey:
        return LaneOutcome("not_applicable", kind)
    key = (
        settings.captcha_capsolver_api_key
        if stage == "capsolver"
        else settings.captcha_2captcha_api_key
    )
    if not key:
        return LaneOutcome("no_key", kind)
    method = TOKEN_METHODS[challenge.captcha_type]
    token = (
        await solve_capsolver(key, method[1], sitekey=challenge.sitekey, url=challenge.url)
        if stage == "capsolver"
        else await solve_2captcha(key, method[0], sitekey=challenge.sitekey, url=challenge.url)
    )
    return LaneOutcome("solved", kind, token=token) if token else LaneOutcome("unsolved", kind)


async def _registry(challenge: Challenge, _remaining: float) -> LaneOutcome:
    kind = challenge.captcha_type or "token"
    provider = REGISTRY.get(challenge.captcha_type or "")
    if provider is None or not challenge.sitekey:
        return LaneOutcome("not_applicable", kind)
    token = await provider.solve(sitekey=challenge.sitekey, url=challenge.url)
    return LaneOutcome("solved", kind, token=token) if token else LaneOutcome("unsolved", kind)


async def run_stage(stage: str, challenge: Challenge, remaining: float) -> LaneOutcome:
    """Run one named lane (free lanes first, paid lanes after)."""
    if stage == "flaresolverr":
        return await _flare(challenge, remaining)
    if stage == "image":
        return await _image(challenge, remaining)
    if stage in ("capsolver", "2captcha"):
        return await _paid(stage, challenge, remaining)
    return await _registry(challenge, remaining)
