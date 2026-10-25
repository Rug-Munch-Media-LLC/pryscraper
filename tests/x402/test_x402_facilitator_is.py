"""Tests for x402/facilitator.py — FacilitatorRouter, multi-provider fallback."""
from tests.x402._gate_support import db, no_owner_key  # noqa: F401
from tests.x402._x402_facilitator_support import _eip7702_ok, router  # noqa: F401
from pry.payments.x402.facilitator import FacilitatorRouter


def test_is_healthy_after_many_failures(router: FacilitatorRouter):
    fac = router.facilitators[0]
    for _ in range(10):
        router._mark_failure(fac)
    assert not router._is_healthy(fac)
