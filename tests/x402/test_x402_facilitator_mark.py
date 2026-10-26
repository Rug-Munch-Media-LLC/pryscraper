"""Tests for x402/facilitator.py — FacilitatorRouter, multi-provider fallback."""

from pry.payments.x402.facilitator import FacilitatorRouter
from tests.x402._gate_support import db, no_owner_key  # noqa: F401
from tests.x402._x402_facilitator_support import _eip7702_ok, router  # noqa: F401


def test_mark_failure_affects_health(router: FacilitatorRouter):
    fac = router.facilitators[0]
    key = router._health_key(fac)
    router._mark_failure(fac)
    assert router._failures.get(key, (0, 0))[0] == 1
    router._mark_failure(fac)
    assert router._failures[key][0] == 2


def test_mark_success_clears_failures(router: FacilitatorRouter):
    fac = router.facilitators[0]
    router._mark_failure(fac)
    router._mark_failure(fac)
    router._mark_success(fac)
    key = router._health_key(fac)
    assert router._failures.get(key, (0, 0))[0] == 1
