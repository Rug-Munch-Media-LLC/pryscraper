"""Tests for x402/facilitator.py — FacilitatorRouter, multi-provider fallback."""
from unittest.mock import MagicMock

from pry.payments.x402.facilitator import (
    FacilitatorRouter,
    get_facilitator_router,
    register_facilitator,
)
from tests.x402._gate_support import db, no_owner_key  # noqa: F401
from tests.x402._x402_facilitator_support import _eip7702_ok, router  # noqa: F401


def test_register_network_facilitator(router: FacilitatorRouter):
    mock_impl = MagicMock()
    router.register_facilitator("solana", mock_impl)
    assert router._impl_for("solana") is mock_impl
def test_register_overwrites_existing(router: FacilitatorRouter):
    router.register_facilitator("solana", MagicMock())
    new_impl = MagicMock()
    router.register_facilitator("solana", new_impl)
    assert router._impl_for("solana") is new_impl
def test_register_facilitator_global():
    import pry.payments.x402.facilitator as fac

    fac._facilitator_router = None
    impl = MagicMock()
    register_facilitator("solana", impl)
    r = get_facilitator_router()
    assert r._impl_for("solana") is impl
