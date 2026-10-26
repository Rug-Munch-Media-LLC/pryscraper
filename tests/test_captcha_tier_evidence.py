"""The tier table is data: cost, p50 latency, IP requirement, closed classes.

A rung that cannot succeed here must be decidable from the table alone, before
the ladder spends a single millisecond on it. The capability probe is injected,
so the verdict is testable without patching anything.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from dataclasses import fields
from typing import TYPE_CHECKING

import pytest

from pry.engine.captcha.tiers import (
    RESIDENTIAL_ENV,
    TIERS,
    CaptchaClass,
    Tier,
    impossible_reason,
    is_impossible,
    ordered_tiers,
    residential_opt_in,
    spec,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

EVIDENCE_FIELDS = {
    "cost",
    "latency_p50_ms",
    "requires_residential_ip",
    "capability",
    "closed_for",
}


def _present(_capability: str) -> bool:
    """Every engine is installed: capability presence is isolated here."""
    return True


@contextmanager
def _residential(value: str | None) -> Iterator[None]:
    """Set or clear the opt-in for one block, then restore the real env."""
    saved = os.environ.get(RESIDENTIAL_ENV)
    try:
        if value is None:
            os.environ.pop(RESIDENTIAL_ENV, None)
        else:
            os.environ[RESIDENTIAL_ENV] = value
        yield
    finally:
        if saved is None:
            os.environ.pop(RESIDENTIAL_ENV, None)
        else:
            os.environ[RESIDENTIAL_ENV] = saved


@pytest.fixture(autouse=True)
def _no_opt_in() -> Iterator[None]:
    """Never inherit an operator's opt-in from the surrounding shell."""
    with _residential(None):
        yield


def test_every_rung_declares_the_evidence_fields() -> None:
    declared = {f.name for f in fields(Tier)}
    assert declared >= EVIDENCE_FIELDS
    for tier in TIERS:
        assert tier.cost > 0
        assert tier.latency_p50_ms > 0
        assert isinstance(tier.requires_residential_ip, bool)
        assert isinstance(tier.closed_for, tuple)
        assert all(isinstance(c, CaptchaClass) for c in tier.closed_for)


def test_static_rank_is_still_cost_times_p50_latency() -> None:
    assert {t.tier: t.rank for t in TIERS} == {
        "T0": 1.0,
        "T1": 10.0,
        "T3": 24.0,
        "T4": 40.0,
        "T2": 60.0,
        "T5": 180.0,
    }
    assert [t.tier for t in ordered_tiers()] == ["T0", "T1", "T3", "T4", "T2", "T5"]


def test_closed_class_is_impossible_before_any_budget_is_spent() -> None:
    reason = impossible_reason("T3", "turnstile", available=_present)
    assert reason is not None
    assert reason.startswith("closed.class")
    assert is_impossible("T3", "turnstile", available=_present) is True
    assert is_impossible("T3", "recaptcha_v2", available=_present) is False


def test_closed_for_accepts_the_strings_the_ladder_produces() -> None:
    assert is_impossible(spec("T2"), CaptchaClass.RECAPTCHA_V3, available=_present) is True
    assert is_impossible("T2", "recaptcha_v3", available=_present) is True
    assert CaptchaClass.parse("recaptcha_v3") is CaptchaClass.RECAPTCHA_V3


def test_residential_rung_is_never_chosen_by_default() -> None:
    tier = spec("T2")
    assert tier is not None
    assert tier.requires_residential_ip is True
    assert residential_opt_in() is False
    reason = impossible_reason("T2", "recaptcha_v2", available=_present)
    assert reason is not None
    assert "residential" in reason
    assert is_impossible("T2", "recaptcha_v2", available=_present) is True
    with _residential("1"):
        assert residential_opt_in() is True
        assert is_impossible("T2", "recaptcha_v2", available=_present) is False


@pytest.mark.parametrize("value", ["", "0", "false", "no", "off", "  ", "maybe"])
def test_only_an_explicit_opt_in_opens_the_residential_gate(value: str) -> None:
    with _residential(value):
        assert residential_opt_in() is False
        assert is_impossible("T2", "recaptcha_v2", available=_present) is True


def test_missing_capability_is_impossible_not_a_slow_failure() -> None:
    def _without_ocr(capability: str) -> bool:
        return capability != "onnx_ocr"

    reason = impossible_reason("T3", "recaptcha_v2", available=_without_ocr)
    assert reason is not None
    assert "onnx_ocr" in reason
    assert is_impossible("T3", "recaptcha_v2", available=_without_ocr) is True


def test_unknown_class_and_unknown_tier_are_safe() -> None:
    assert CaptchaClass.parse(None) is CaptchaClass.UNKNOWN
    assert CaptchaClass.parse("brand-new-challenge") is CaptchaClass.UNKNOWN
    assert is_impossible("T3", "brand-new-challenge", available=_present) is False
    assert is_impossible("T99", "recaptcha_v2", available=_present) is True


def test_verdicts_are_deterministic() -> None:
    first = [(t.tier, impossible_reason(t, "recaptcha_v2", available=_present)) for t in TIERS]
    second = [(t.tier, impossible_reason(t, "recaptcha_v2", available=_present)) for t in TIERS]
    assert first == second
