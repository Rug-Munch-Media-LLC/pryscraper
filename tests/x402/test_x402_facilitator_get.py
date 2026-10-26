"""Tests for x402/facilitator.py — FacilitatorRouter, multi-provider fallback."""
from pry.payments.x402.facilitator import get_facilitator_router
from tests.x402._gate_support import db, no_owner_key  # noqa: F401
from tests.x402._x402_facilitator_support import _eip7702_ok, router  # noqa: F401


def test_get_router_singleton():
    import pry.payments.x402.facilitator as fac

    fac._facilitator_router = None
    r1 = get_facilitator_router()
    r2 = get_facilitator_router()
    assert r1 is r2
