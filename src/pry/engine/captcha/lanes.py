"""Pry — one function per free rung, plus the dispatch table.

Each rung is a small adapter over its engine module and returns a
:class:`LaneOutcome`: it never raises, so a broken engine degrades to a typed
``failed`` and the ladder keeps going. Rungs are addressed by tier id (T0..T5);
:func:`run_stage` stays as the legacy alias used by the detect routes.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

from pry.core.settings import settings
from pry.engine.captcha import (
    audio_asr,
    browser_integrity,
    clearance,
    image_ocr,
    t0_profile,
    vision,
)
from pry.engine.captcha.flaresolverr import flaresolverr_fetch, looks_unsolved

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Challenge:
    """Everything a rung may need about one blocked response."""

    url: str
    html: str | None = None
    captcha_type: str | None = None
    sitekey: str | None = None
    image: bytes | str | None = None
    audio: bytes | None = None
    background: bytes | None = None
    piece: bytes | None = None


@dataclass(slots=True)
class LaneOutcome:
    """Result of one rung: solved (with token/html) or why not."""

    outcome: str
    kind: str
    token: str | None = None
    html: str | None = None
    reason: str = ""


async def _cached(item: clearance.Clearance, url: str, remaining: float) -> str | None:
    """Replay a stored clearance: the cookie AND the UA that earned it."""
    headers = {"User-Agent": item.user_agent, "Cookie": item.cookie_header()}
    try:
        timeout = max(min(remaining, 20.0), 1.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(url, headers=headers)
    except httpx.HTTPError:
        logger.debug("best-effort fallback", exc_info=True)
        return None
    return (resp.text or None) if resp.status_code == 200 else None


async def _t0(challenge: Challenge, remaining: float) -> LaneOutcome:
    if settings.captcha_enabled and clearance.enabled():
        domain = clearance.domain_of(challenge.url)
        item = await clearance.store().get(domain)
        if item is not None:
            html = await _cached(item, challenge.url, remaining)
            if html and not looks_unsolved(html):
                return LaneOutcome("solved", "http", html=html, reason="clearance")
            if html:
                await clearance.store().invalidate(domain)
    html, reason = await t0_profile.fetch_clean(challenge.url, min(remaining, 20.0))
    if reason == "solved" and html:
        return LaneOutcome("solved", "http", html=html)
    return LaneOutcome(reason, "http")


async def _t1(challenge: Challenge, remaining: float) -> LaneOutcome:
    solution = await flaresolverr_fetch(challenge.url, remaining)
    if solution.ok and not looks_unsolved(solution.html):
        await clearance.record(challenge.url, solution.token, "T1")
        return LaneOutcome("solved", "js", token=solution.token, html=solution.html)
    return LaneOutcome("unsolved" if solution.ok else solution.error or "failed", "js")


async def _t2(challenge: Challenge, remaining: float) -> LaneOutcome:
    text, reason = await audio_asr.solve_audio(challenge.audio, min(remaining, 30.0))
    return LaneOutcome(reason, "audio", token=text)


async def _t3(challenge: Challenge, remaining: float) -> LaneOutcome:
    text, reason = await image_ocr.solve_image(challenge.image, min(remaining, 15.0))
    return LaneOutcome(reason, "image", token=text)


async def _t4(challenge: Challenge, remaining: float) -> LaneOutcome:
    offset, reason = await vision.solve_puzzle(
        challenge.background,
        challenge.piece,
        challenge.captcha_type or "slider",
        min(remaining, 10.0),
    )
    return LaneOutcome(reason, "vision", token=None if offset is None else str(offset))


async def _t5(challenge: Challenge, remaining: float) -> LaneOutcome:
    token, reason = await browser_integrity.solve_browser(
        challenge.url, challenge.captcha_type or "unknown", min(remaining, 45.0)
    )
    return LaneOutcome("solved" if reason == "solved" else reason, "browser", token=token)


_RUNNERS = {"T0": _t0, "T1": _t1, "T2": _t2, "T3": _t3, "T4": _t4, "T5": _t5}


async def run_tier(tier: str, challenge: Challenge, remaining: float) -> LaneOutcome:
    """Run one free rung by tier id; unknown ids are not applicable."""
    runner = _RUNNERS.get(tier)
    if runner is None:
        return LaneOutcome("not_applicable", "unknown", reason=f"unknown tier {tier}")
    return await runner(challenge, remaining)


async def run_stage(stage: str, challenge: Challenge, remaining: float) -> LaneOutcome:
    """Legacy alias: stage names map onto the free tier ids."""
    alias = {"flaresolverr": "T1", "image": "T3", "token": "T2"}
    return await run_tier(alias.get(stage, stage), challenge, remaining)
