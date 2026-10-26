"""Tests for x402/facilitator.py — FacilitatorRouter, multi-provider fallback."""

from unittest.mock import patch

from pry.payments.x402.facilitator import FacilitatorRouter
from tests.x402._gate_support import db, no_owner_key  # noqa: F401
from tests.x402._x402_facilitator_support import _eip7702_ok, router  # noqa: F401


def test_readiness_returns_dict(router: FacilitatorRouter):
    status = router.readiness()
    assert isinstance(status, dict)
    assert "mode" in status
    assert "ready" in status
    assert "wallet_configured" in status


def test_readiness_counts_facilitators(router: FacilitatorRouter):
    status = router.readiness()
    assert status["mode"] in ("self_hosted", "external")


def test_readiness_self_hosted():
    """Self-hosted mode readiness should indicate wallet information."""
    with patch("pry.payments.x402.facilitator.X402_WALLET", "0xRealWallet"):
        r = FacilitatorRouter(self_hosted=True)
        status = r.readiness()
        assert status["mode"] == "self_hosted"
        assert "ready" in status
        assert "wallet_configured" in status
