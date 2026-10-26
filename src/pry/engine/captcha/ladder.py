"""Pry — CAPTCHA solving ladder.

Priority order (free lanes first, paid token solvers after)::

    flaresolverr -> image (OCR) -> capsolver -> 2captcha -> token registry

Every lane is attempted in order until one returns a solution; the whole run is
capped by ``PRY_CAPTCHA_MAX_SECONDS`` (default 60 s). Each attempt logs exactly
one line: ``captcha_attempt provider=<name> type=<kind> ms=<n> outcome=<...>``.
A total miss returns ``blocked.captcha_unsolved`` and names the missing keys.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field

from pry.core.settings import settings
from pry.engine.captcha.guard import solver_allowed
from pry.engine.captcha.keys import load_captcha_keys, missing_token_keys
from pry.engine.captcha.lanes import Challenge, run_stage

logger = logging.getLogger(__name__)

LADDER_ORDER: tuple[str, ...] = ("flaresolverr", "image", "capsolver", "2captcha", "token")


@dataclass(slots=True)
class SolveAttempt:
    """One ladder attempt, rendered as a single log line."""

    provider: str
    kind: str
    ms: int
    outcome: str
    detail: str = ""

    def line(self) -> str:
        return f"{self.provider} {self.kind} {self.ms} {self.outcome}"


@dataclass(slots=True)
class LadderResult:
    """Outcome of a full ladder run."""

    status: str
    provider: str | None = None
    token: str | None = None
    html: str | None = None
    attempts: list[SolveAttempt] = field(default_factory=list)
    missing_keys: list[str] = field(default_factory=list)
    elapsed_ms: int = 0

    def as_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "provider": self.provider,
            "token": self.token,
            "attempts": [a.line() for a in self.attempts],
            "missing_keys": self.missing_keys,
            "elapsed_ms": self.elapsed_ms,
        }


async def solve_ladder(challenge: Challenge, deadline_s: float | None = None) -> LadderResult:
    """Attempt every solver lane in priority order under one time budget."""
    started = time.monotonic()
    budget = float(deadline_s if deadline_s is not None else settings.captcha_max_seconds)
    deadline = started + budget
    if not settings.captcha_enabled:
        return LadderResult(status="disabled")
    load_captcha_keys()
    allowed, reason = await solver_allowed(challenge.url)
    if not allowed:
        logger.info("captcha_refused url=%s reason=%s", challenge.url, reason)
        return LadderResult(status=reason, elapsed_ms=int((time.monotonic() - started) * 1000))
    attempts: list[SolveAttempt] = []
    result = LadderResult(status="blocked.captcha_unsolved")
    for stage in LADDER_ORDER:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            attempts.append(SolveAttempt(stage, "token", 0, "deadline"))
            break
        lane_start = time.monotonic()
        try:
            async with asyncio.timeout(remaining):
                lane = await run_stage(stage, challenge, remaining)
                outcome, token, solved_html, kind = (
                    lane.outcome,
                    lane.token,
                    lane.html,
                    lane.kind,
                )
        except TimeoutError:
            outcome, token, solved_html, kind = "timeout", None, None, "timeout"
        attempt = SolveAttempt(stage, kind, int((time.monotonic() - lane_start) * 1000), outcome)
        attempts.append(attempt)
        logger.info(
            "captcha_attempt provider=%s type=%s ms=%d outcome=%s",
            attempt.provider,
            attempt.kind,
            attempt.ms,
            attempt.outcome,
        )
        if outcome == "solved":
            result = LadderResult(
                status="solved",
                provider=stage,
                token=token,
                html=solved_html,
                attempts=attempts,
                elapsed_ms=int((time.monotonic() - started) * 1000),
            )
            break
    if result.status != "solved":
        result.attempts = attempts
        result.missing_keys = missing_token_keys()
        result.elapsed_ms = int((time.monotonic() - started) * 1000)
        logger.warning(
            "captcha_unsolved tried=%s missing_keys=%s",
            [a.line() for a in attempts],
            result.missing_keys,
        )
    return result
