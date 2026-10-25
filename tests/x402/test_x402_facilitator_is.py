"""Tests for x402/facilitator.py — FacilitatorRouter, multi-provider fallback."""
from pry.payments.x402.facilitator import FacilitatorRouter


def test_is_healthy_after_many_failures(router: FacilitatorRouter):
    fac = router.facilitators[0]
    for _ in range(10):
        router._mark_failure(fac)
    assert not router._is_healthy(fac)
