"""Ranking is evidence-first: measured success rate replaces the static prior."""

from __future__ import annotations

import math
from dataclasses import replace

import pytest
from hypothesis import given, settings, strategies as st

from pry.engine.captcha.ranking import (
    MIN_SAMPLES,
    PRIOR_SUCCESS_RATE,
    ClassStats,
    rank,
)
from pry.engine.captcha.tiers import TIERS, CaptchaClass, spec

CLASS = "recaptcha_v2"


def _static(tier_id: str) -> float:
    tier = spec(tier_id)
    assert tier is not None
    return PRIOR_SUCCESS_RATE / (tier.cost * tier.latency_p50_ms / 1000.0)


def _pair(
    tier_id: str, class_name: str, samples: int, successes: int
) -> dict[tuple[str, str], ClassStats]:
    return {(tier_id, class_name): ClassStats(samples, successes)}


def test_without_evidence_the_static_order_survives() -> None:
    order = sorted(TIERS, key=lambda tier: rank(tier, CLASS), reverse=True)
    assert [t.tier for t in order] == ["T0", "T1", "T3", "T4", "T2", "T5"]
    assert rank("T1", CLASS) == pytest.approx(_static("T1"))
    assert rank("T5", CLASS) == pytest.approx(_static("T5"))


def test_evidence_beats_the_static_rank_when_it_exists() -> None:
    assert rank("T1", CLASS) > rank("T4", CLASS)
    stats = {
        ("T1", CLASS): ClassStats(20, 1),
        ("T4", CLASS): ClassStats(20, 18),
    }
    assert rank("T4", CLASS, stats) > rank("T1", CLASS, stats)


def test_a_tier_that_never_wins_sinks_to_zero() -> None:
    stats = _pair("T1", CLASS, 30, 0)
    assert rank("T1", CLASS, stats) == 0.0
    assert rank("T1", CLASS, stats) < rank("T0", CLASS, stats)


def test_the_sample_floor_is_the_gate() -> None:
    below = _pair("T1", CLASS, MIN_SAMPLES - 1, 0)
    assert rank("T1", CLASS, below) == pytest.approx(_static("T1"))
    at_floor = _pair("T1", CLASS, MIN_SAMPLES, 0)
    assert rank("T1", CLASS, at_floor) == 0.0


def test_evidence_is_scoped_to_its_own_tier_and_class() -> None:
    stats = {
        ("T1", "hcaptcha"): ClassStats(50, 0),
        ("T4", CLASS): ClassStats(50, 0),
    }
    assert rank("T1", CLASS, stats) == pytest.approx(_static("T1"))
    assert rank("T3", CLASS, stats) == pytest.approx(_static("T3"))


def test_ranking_is_pure_and_deterministic() -> None:
    stats = _pair("T1", CLASS, 40, 12)
    before = dict(stats)
    first = rank("T1", CLASS, stats)
    second = rank("T1", CLASS, stats)
    assert first == second
    assert stats == before


def test_every_rung_yields_a_finite_positive_score() -> None:
    for tier in TIERS:
        for captcha_class in CaptchaClass:
            score = rank(tier, captcha_class)
            assert math.isfinite(score)
            assert score > 0


def test_an_unmeasurable_rung_scores_zero_instead_of_dividing_by_zero() -> None:
    zero_work = replace(TIERS[0], tier="TX", cost=0, latency_p50_ms=0)
    assert rank(zero_work, CLASS) == 0.0


@pytest.mark.parametrize("tier_id", ["T0", "T1", "T3", "T4", "T2", "T5"])
def test_evidence_only_ever_reorders_by_measured_value(tier_id: str) -> None:
    tier = spec(tier_id)
    assert tier is not None
    work = tier.cost * tier.latency_p50_ms / 1000.0
    stats = _pair(tier_id, CLASS, 100, 25)
    assert rank(tier, CLASS, stats) == pytest.approx(0.25 / work)


@given(
    st.integers(min_value=0, max_value=1000),
    st.integers(min_value=0, max_value=1000),
)
@settings(max_examples=50, deadline=None)
def test_more_successes_never_rank_lower(a: int, b: int) -> None:
    low, high = sorted((a, b))
    low_stats = _pair("T1", CLASS, 1000, low)
    high_stats = _pair("T1", CLASS, 1000, high)
    assert rank("T1", CLASS, low_stats) <= rank("T1", CLASS, high_stats)
