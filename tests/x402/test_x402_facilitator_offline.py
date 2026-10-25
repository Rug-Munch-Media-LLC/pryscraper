"""Tests for x402/facilitator.py — FacilitatorRouter, multi-provider fallback."""
from tests.x402._gate_support import db, no_owner_key  # noqa: F401
from tests.x402._x402_facilitator_support import _eip7702_ok, router  # noqa: F401
from pry.payments.x402.facilitator import FacilitatorRouter


def test_offline_settlement_format(router: FacilitatorRouter):
    """Should return correctly formatted offline settlement."""
    result = router._offline_settlement("pay_123", "0xabc", "base")
    assert result["success"] is True
    assert result["payment_id"] == "pay_123"
    assert result["transaction"] == "0xabc"
    assert result["network"] == "base"
    assert result["facilitator"] == "offline"
