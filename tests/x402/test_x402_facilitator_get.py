"""Tests for x402/facilitator.py — FacilitatorRouter, multi-provider fallback."""
from pry.payments.x402.facilitator import get_facilitator_router


def test_get_router_singleton():
    import pry.payments.x402.facilitator as fac

    fac._facilitator_router = None
    r1 = get_facilitator_router()
    r2 = get_facilitator_router()
    assert r1 is r2
