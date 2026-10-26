"""Tests for x402/facilitator.py — FacilitatorRouter, multi-provider fallback."""
from pry.payments.x402.facilitator import FacilitatorRouter
from tests.x402._gate_support import db, no_owner_key  # noqa: F401
from tests.x402._x402_facilitator_support import _eip7702_ok, router  # noqa: F401


def test_build_payment_with_auth(router: FacilitatorRouter):
    router.submit_authorization("pay_123", {"sig": "0xsig"})
    payment = router._build_payment("pay_123", "0xabc", "base", "USDC", 1.0)
    assert payment["payment_id"] == "pay_123"
    assert payment["tx_hash"] == "0xabc"
    assert payment["network"] == "base"
    assert payment["asset"] == "USDC"
    assert payment["amount_usd"] == 1.0
    expected = {"sig": "0xsig"}
    assert payment["authorization"] == expected
def test_build_payment_no_auth(router: FacilitatorRouter):
    payment = router._build_payment("pay_456", "0xdef", "solana", "USDC", 5.0)
    assert "authorization" not in payment
