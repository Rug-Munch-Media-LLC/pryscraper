"""Pry — evidence-first ranking for ladder rungs.

:func:`rank` answers one question: given what we measured, which rung deserves
the next millisecond of budget? It returns measured value per unit of work —
successes per second of expected work — so a larger number is a better rung and
the caller sorts descending.

With no evidence, or fewer than :data:`MIN_SAMPLES` observations for the pair,
it falls back to :data:`PRIOR_SUCCESS_RATE`, which reproduces the hand-assigned
cost x latency order exactly (T0, T1, T3, T4, T2, T5). Evidence changes the
order; a guess never does.

Evidence is keyed by ``(tier, captcha_class)``: a tier's success rate for a
class is the only quantity that can rank tiers for that class, and a class's
overall rate would rank nothing.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from pry.engine.captcha.tiers import CaptchaClass, Tier, spec

if TYPE_CHECKING:
    from collections.abc import Mapping

#: Below this many observations a rung keeps its static prior.
MIN_SAMPLES = 10
#: Assume a coin flip until the ladder has measured otherwise.
PRIOR_SUCCESS_RATE = 0.5

StatsKey = tuple[str, str]


@dataclass(frozen=True, slots=True)
class ClassStats:
    """Observed outcomes for one ``(tier, captcha_class)`` pair."""

    samples: int
    successes: int

    @property
    def success_rate(self) -> float:
        """Successes per sample, clamped to [0, 1] against odd telemetry."""
        if self.samples <= 0:
            return 0.0
        return min(1.0, max(0.0, self.successes / self.samples))


def _resolve(tier: Tier | str) -> Tier | None:
    return tier if isinstance(tier, Tier) else spec(tier)


def _observed(
    tier: str, captcha_class: str | CaptchaClass, stats: Mapping[StatsKey, ClassStats] | None
) -> ClassStats | None:
    """The recorded stats for this pair, tolerating str or enum keys."""
    if not stats:
        return None
    wanted = CaptchaClass.parse(str(captcha_class))
    for (key_tier, key_class), value in stats.items():
        if key_tier == tier and CaptchaClass.parse(str(key_class)) is wanted:
            return value
    return None


def rank(
    tier: Tier | str,
    captcha_class: str | CaptchaClass,
    stats: Mapping[StatsKey, ClassStats] | None = None,
) -> float:
    """Value per unit of work for one (rung, class); higher is better.

    ``success_rate / (cost x p50 latency in seconds)`` once the pair has at
    least :data:`MIN_SAMPLES` samples, else the static prior over the same
    work. An unknown tier, or one with no measurable work, scores 0.0.
    """
    candidate = _resolve(tier)
    if candidate is None:
        return 0.0
    work = candidate.cost * (candidate.latency_p50_ms / 1000.0)
    if work <= 0:
        return 0.0
    observed = _observed(candidate.tier, captcha_class, stats)
    if observed is not None and observed.samples >= MIN_SAMPLES:
        return observed.success_rate / work
    return PRIOR_SUCCESS_RATE / work
