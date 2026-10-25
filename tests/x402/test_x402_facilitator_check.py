"""Tests for x402/facilitator.py — FacilitatorRouter, multi-provider fallback."""
from tests.x402._x402_facilitator_support import _eip7702_ok, router  # noqa: F401
from pry.payments.x402.facilitator import FacilitatorRouter


def test_check_auth_nonexistent(router: FacilitatorRouter):
    assert router._pending_auths.get("no_such_payment") is None
