"""Tests for x402/facilitator.py — FacilitatorRouter, multi-provider fallback."""
from tests.x402._gate_support import db, no_owner_key  # noqa: F401
from tests.x402._x402_facilitator_support import _eip7702_ok, router  # noqa: F401
from unittest.mock import MagicMock

from pry.payments.x402.facilitator import FacilitatorRouter


def test_impl_for_network_family_fallback(router: FacilitatorRouter):
    """Should fall back to network family when exact match not found."""
    mock_impl = MagicMock()
    router.register_facilitator("solana", mock_impl)
    result = router._impl_for("solana:mainnet")
    assert result is mock_impl
def test_impl_for_exact_match(router: FacilitatorRouter):
    """Exact network match should take precedence over the family fallback."""
    exact = MagicMock()
    family = MagicMock()
    # Register an exact CAIP-2 impl and a family impl. The family name "evm"
    # does NOT normalize to the exact key, so the two registrations are
    # distinct and _impl_for must prefer the exact match.
    router.register_facilitator("eip155:8453", exact)
    router.register_facilitator("evm", family)
    result = router._impl_for("eip155:8453")
    assert result is exact
