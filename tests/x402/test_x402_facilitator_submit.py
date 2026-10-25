"""Tests for x402/facilitator.py — FacilitatorRouter, multi-provider fallback."""
from tests.x402._gate_support import db, no_owner_key  # noqa: F401
from tests.x402._x402_facilitator_support import _eip7702_ok, router  # noqa: F401
from pry.payments.x402.facilitator import FacilitatorRouter


def test_submit_and_check_auth(router: FacilitatorRouter):
    router.submit_authorization("pay_123", {"sig": "0xabc"})
    expected = {"sig": "0xabc"}
    assert router._pending_auths["pay_123"] == expected
