"""Tests for x402/facilitator.py — FacilitatorRouter, multi-provider fallback."""
from pry.payments.x402.facilitator import FacilitatorRouter


def test_check_auth_nonexistent(router: FacilitatorRouter):
    assert router._pending_auths.get("no_such_payment") is None
