"""Tests for x402/facilitator.py — FacilitatorRouter, multi-provider fallback."""
from pry.payments.x402.facilitator import FacilitatorRouter
from tests.x402._gate_support import db, no_owner_key  # noqa: F401
from tests.x402._x402_facilitator_support import _eip7702_ok, router  # noqa: F401


def test_check_auth_nonexistent(router: FacilitatorRouter):
    assert router._pending_auths.get("no_such_payment") is None
