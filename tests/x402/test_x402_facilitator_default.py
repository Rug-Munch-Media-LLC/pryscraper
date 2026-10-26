"""Tests for x402/facilitator.py — FacilitatorRouter, multi-provider fallback."""
from pry.payments.x402.facilitator import DEFAULT_FACILITATORS
from tests.x402._gate_support import db, no_owner_key  # noqa: F401
from tests.x402._x402_facilitator_support import _eip7702_ok, router  # noqa: F401


def test_default_facilitators_nonempty():
    assert len(DEFAULT_FACILITATORS) >= 3
    names = {f.name for f in DEFAULT_FACILITATORS}
    assert "coinbase" in names
    assert "payai" in names
    assert "cloudflare" in names
