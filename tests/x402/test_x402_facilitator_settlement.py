"""Tests for x402/facilitator.py — FacilitatorRouter, multi-provider fallback."""
from pry.payments.x402.facilitator import FacilitatorRouter


def test_settlement_stats_defaults(router: FacilitatorRouter):
    stats = router.settlement_stats()
    assert isinstance(stats, dict)
    assert "nonces_seen" in stats
