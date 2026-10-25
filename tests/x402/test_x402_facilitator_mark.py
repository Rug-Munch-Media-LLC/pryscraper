"""Tests for x402/facilitator.py — FacilitatorRouter, multi-provider fallback."""
from pry.payments.x402.facilitator import FacilitatorRouter


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
