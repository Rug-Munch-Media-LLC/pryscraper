"""Breaker granularity is (tier, domain): one site's block must not park a rung.

A rung is only globally parked once it has failed across several distinct
domains — that is the difference between "this site blocks T1" and "T1 is
broken". Window and decay semantics are unchanged.
"""

from __future__ import annotations

import pytest
from hypothesis import given, settings, strategies as st

from pry.engine.captcha.breaker import DEFAULT_GLOBAL_DOMAINS, TierBreaker

SITE_A = "a.example"
SITE_B = "b.example"
SITE_C = "c.example"
SITE_D = "d.example"


def _clock(start: float = 0.0) -> tuple[list[float], object]:
    now = [start]
    return now, lambda: now[0]


def _fail(breaker: TierBreaker, tier: str, domain: str, times: int = 3) -> None:
    for _ in range(times):
        breaker.record(tier, ok=False, domain=domain)


def test_one_domain_failure_does_not_disable_the_tier_elsewhere() -> None:
    breaker = TierBreaker(limit=3, window_s=60.0, domains=3)
    _fail(breaker, "T1", SITE_A)
    assert breaker.is_open("T1", SITE_A) is True
    assert breaker.is_open("T1", SITE_B) is False
    assert breaker.is_open("T1", SITE_C) is False
    assert list(breaker.snapshot()) == [f"T1:{SITE_A}"]


def test_global_fallback_only_after_n_distinct_domains() -> None:
    breaker = TierBreaker(limit=3, window_s=60.0, domains=DEFAULT_GLOBAL_DOMAINS)
    _fail(breaker, "T1", SITE_A)
    _fail(breaker, "T1", SITE_B)
    assert breaker.is_open("T1", SITE_D) is False
    _fail(breaker, "T1", SITE_C)
    assert breaker.is_open("T1", SITE_D) is True


def test_scattered_failures_across_domains_do_not_open_the_tier() -> None:
    breaker = TierBreaker(limit=3, window_s=60.0, domains=3)
    for site in (SITE_A, SITE_B, SITE_C):
        breaker.record("T1", ok=False, domain=site)
    assert breaker.is_open("T1", SITE_D) is False


def test_success_closes_only_its_own_domain() -> None:
    breaker = TierBreaker(limit=2, window_s=60.0, domains=10)
    _fail(breaker, "T1", SITE_A, 2)
    _fail(breaker, "T1", SITE_B, 2)
    breaker.record("T1", domain=SITE_A)
    assert breaker.is_open("T1", SITE_A) is False
    assert breaker.is_open("T1", SITE_B) is True


def test_window_decay_still_expires_old_failures() -> None:
    now, clock = _clock()
    breaker = TierBreaker(limit=2, window_s=30.0, domains=10, clock=clock)
    _fail(breaker, "T1", SITE_A, 2)
    assert breaker.is_open("T1", SITE_A) is True
    now[0] = 31.0
    assert breaker.is_open("T1", SITE_A) is False
    assert breaker.snapshot() == {}


def test_urls_are_normalised_to_their_host() -> None:
    breaker = TierBreaker(limit=1, window_s=60.0, domains=10)
    breaker.record("T1", ok=False, domain="https://A.example:8443/path?q=1")
    assert breaker.is_open("T1", "a.example") is True
    assert breaker.is_open("T1", "https://a.example/other") is True
    assert breaker.is_open("T1", "b.example") is False


def test_unscoped_calls_keep_the_single_argument_shape() -> None:
    breaker = TierBreaker(limit=3, window_s=60.0)
    for _ in range(3):
        breaker.record("T1:recaptcha_v2", ok=False)
    assert breaker.is_open("T1:recaptcha_v2") is True
    assert breaker.snapshot() == {"T1:recaptcha_v2": 3}


def test_breaker_is_per_construction_not_global() -> None:
    first = TierBreaker(limit=1, window_s=60.0)
    second = TierBreaker(limit=1, window_s=60.0)
    _fail(first, "T1", SITE_A, 1)
    assert first.is_open("T1", SITE_A) is True
    assert second.is_open("T1", SITE_A) is False


@given(
    st.integers(min_value=1, max_value=5),
    st.integers(min_value=0, max_value=8),
)
@settings(max_examples=50, deadline=None)
def test_failures_on_one_domain_never_open_another(limit: int, times: int) -> None:
    breaker = TierBreaker(limit=limit, window_s=60.0, domains=10**6)
    _fail(breaker, "T1", SITE_A, times)
    assert breaker.is_open("T1", SITE_A) is (times >= limit)
    assert breaker.is_open("T1", SITE_B) is False


@given(st.floats(min_value=30.001, max_value=10_000.0))
@settings(max_examples=25, deadline=None)
def test_any_failure_decays_outside_the_window(age: float) -> None:
    now, clock = _clock()
    breaker = TierBreaker(limit=1, window_s=30.0, domains=10**6, clock=clock)
    breaker.record("T1", ok=False, domain=SITE_A)
    assert breaker.is_open("T1", SITE_A) is True
    now[0] = age
    assert breaker.is_open("T1", SITE_A) is False


def test_a_failing_tier_still_needs_a_failure_to_open() -> None:
    breaker = TierBreaker(limit=3, window_s=60.0)
    assert breaker.is_open("T9", SITE_A) is False
    for _ in range(2):
        breaker.record("T9", domain=SITE_A)
    assert breaker.is_open("T9", SITE_A) is False
    assert pytest.approx(breaker.limit) == 3
