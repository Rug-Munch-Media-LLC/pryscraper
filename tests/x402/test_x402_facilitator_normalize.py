"""Tests for x402/facilitator.py — FacilitatorRouter, multi-provider fallback."""
from pry.payments.x402.facilitator import FacilitatorRouter
from tests.x402._gate_support import db, no_owner_key  # noqa: F401
from tests.x402._x402_facilitator_support import _eip7702_ok, router  # noqa: F401


def test_normalize_settlement_with_required(router: FacilitatorRouter):
    """Should normalize settlement with required fields."""
    raw = {"blockNumber": 12345, "blockHash": "0xblock"}
    norm = router._normalize_settlement(raw, "pay_123", "0xabc", "base", "test-fac")
    assert norm["transaction"] == "0xabc"
    assert norm["payment_id"] == "pay_123"
    assert norm["network"] == "base"
    assert norm["facilitator"] == "test-fac"
    assert norm["block_number"] == 12345
def test_normalize_settlement_empty(router: FacilitatorRouter):
    """Should normalize empty settlement."""
    norm = router._normalize_settlement({}, "pay_123", "0xabc", "base", "test-fac")
    assert norm["transaction"] == "0xabc"
