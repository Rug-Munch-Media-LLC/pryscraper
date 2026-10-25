"""Tests for x402/facilitator.py — FacilitatorRouter, multi-provider fallback."""
from pry.payments.x402.facilitator import DEFAULT_FACILITATORS


def test_default_facilitators_nonempty():
    assert len(DEFAULT_FACILITATORS) >= 3
    names = {f.name for f in DEFAULT_FACILITATORS}
    assert "coinbase" in names
    assert "payai" in names
    assert "cloudflare" in names
