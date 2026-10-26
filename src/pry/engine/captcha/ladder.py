"""Pry — the free, tiered, cost-ordered CAPTCHA ladder.

Order comes from :func:`tiers.ordered_tiers` (cost x latency): T0 clean
profile, T1 FlareSolverr, T3 ONNX OCR, T4 vision, T2 audio ASR, T5 browser.
A rung whose engine is absent is skipped instantly and recorded as
``skipped``; a rung that fails three times for one CAPTCHA class is skipped by
its circuit breaker and recorded as ``skipped breaker.open``.

Robots.txt is a terminal refusal with zero attempts. Everything else returns a
full trail (``tier · outcome · ms · reason``) so diagnostics can prove what ran.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field

from pry.core.settings import settings
from pry.engine.captcha import probes
from pry.engine.captcha.breaker import TierBreaker
from pry.engine.captcha.guard import solver_allowed
from pry.engine.captcha.lanes import Challenge, run_tier
from pry.engine.captcha.outcomes import (
    BLOCKED_UNSOLVED,
    DISABLED,
    SKIPPED,
    SOLVED,
    TIMEOUT,
    TierOutcome,
)
from pry.engine.captcha.tiers import ordered_tiers

logger = logging.getLogger(__name__)

BREAK_LIMIT = 3


@dataclass(slots=True)
class LadderResult:
    """Outcome of a whole ladder run, attempts trail included."""

    status: str
    provider: str | None = None
    token: str | None = None
    html: str | None = None
    attempts: list[TierOutcome] = field(default_factory=list)
    captcha_class: str = "unknown"
    tiers_tried: list[str] = field(default_factory=list)
    elapsed_ms: int = 0

    def as_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "provider": self.provider,
            "token": self.token,
            "captcha_class": self.captcha_class,
            "tiers_tried": list(self.tiers_tried),
            "attempts": [a.line() for a in self.attempts],
            "elapsed_ms": self.elapsed_ms,
        }


#: Process-wide breaker: a rung that keeps failing for one class stays skipped.
_BREAKER = TierBreaker(limit=BREAK_LIMIT)


def _elapsed(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


@dataclass(slots=True)
class _Walk:
    """Mutable state of one ladder run: budget, trail, and breaker keys."""

    challenge: Challenge
    captcha_class: str
    started: float
    deadline: float
    breaker: TierBreaker
    attempts: list[TierOutcome] = field(default_factory=list)
    tried: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)

    def solved(self, tier: str, outcome: TierOutcome) -> LadderResult:
        """Successful run: the rung that solved it plus the full trail."""
        return LadderResult(
            status=SOLVED,
            provider=tier,
            token=outcome.token,
            html=outcome.html,
            attempts=self.attempts,
            captcha_class=self.captcha_class,
            tiers_tried=self.tried,
            elapsed_ms=_elapsed(self.started),
        )

    def unsolved(self) -> LadderResult:
        """Nothing solved: name the first missing engine, else blocked."""
        status = self.missing[0] if self.missing and not self.tried else BLOCKED_UNSOLVED
        result = LadderResult(
            status=status,
            attempts=self.attempts,
            captcha_class=self.captcha_class,
            tiers_tried=self.tried,
            elapsed_ms=_elapsed(self.started),
        )
        logger.warning(
            "captcha_unsolved status=%s class=%s tried=%s trail=%s",
            status,
            self.captcha_class,
            self.tried,
            [a.line() for a in self.attempts],
        )
        return result


def _skip(walk: _Walk, tier: str, capability: str, missing: str) -> TierOutcome | None:
    """Skipped outcome for a closed rung, or None when the rung may run."""
    key = f"{tier}:{walk.captcha_class}"
    if walk.breaker.is_open(key):
        return TierOutcome(tier, SKIPPED, 0, f"breaker.open {key}")
    if not probes.available(capability):
        walk.missing.append(missing)
        return TierOutcome(tier, SKIPPED, 0, f"{missing} {capability}")
    return None


async def _attempt(walk: _Walk, tier: str) -> TierOutcome | None:
    """Run one rung inside the remaining budget; None once the budget is gone."""
    remaining = walk.deadline - time.monotonic()
    if remaining <= 0:
        walk.attempts.append(TierOutcome(tier, SKIPPED, 0, "deadline"))
        return None
    lane_start = time.monotonic()
    try:
        async with asyncio.timeout(remaining):
            lane = await run_tier(tier, walk.challenge, remaining)
        status, detail, token, html = lane.outcome, lane.reason, lane.token, lane.html
    except TimeoutError:
        status, detail, token, html = TIMEOUT, "tier timeout", None, None
    outcome = TierOutcome(
        tier, status, int((time.monotonic() - lane_start) * 1000), detail, token, html
    )
    logger.info(
        "captcha_attempt tier=%s status=%s ms=%d reason=%s",
        outcome.tier,
        outcome.status,
        outcome.ms,
        outcome.reason,
    )
    return outcome


async def _walk(walk: _Walk) -> LadderResult | None:
    """Walk the tiers in cost order; return the solved result, else None."""
    for spec in ordered_tiers():
        skipped = _skip(walk, spec.tier, spec.capability, spec.missing)
        if skipped is not None:
            walk.attempts.append(skipped)
            continue
        outcome = await _attempt(walk, spec.tier)
        if outcome is None:
            break
        walk.attempts.append(outcome)
        walk.tried.append(spec.tier)
        walk.breaker.record(f"{spec.tier}:{walk.captcha_class}", outcome.status == SOLVED)
        if outcome.status == SOLVED:
            return walk.solved(spec.tier, outcome)
    return None


async def solve_ladder(
    challenge: Challenge,
    deadline_s: float | None = None,
    breaker: TierBreaker | None = None,
) -> LadderResult:
    """Walk the free tiers in cost order under one time budget."""
    started = time.monotonic()
    captcha_class = challenge.captcha_type or "unknown"
    if not settings.captcha_enabled:
        return LadderResult(status=DISABLED, captcha_class=captcha_class)
    allowed, reason = await solver_allowed(challenge.url)
    if not allowed:
        logger.info("captcha_refused url=%s reason=%s", challenge.url, reason)
        return LadderResult(
            status=reason, captcha_class=captcha_class, elapsed_ms=_elapsed(started)
        )
    budget = float(deadline_s if deadline_s is not None else settings.captcha_max_seconds)
    walk = _Walk(
        challenge=challenge,
        captcha_class=captcha_class,
        started=started,
        deadline=started + budget,
        breaker=breaker or _BREAKER,
    )
    solved = await _walk(walk)
    return solved if solved is not None else walk.unsolved()
