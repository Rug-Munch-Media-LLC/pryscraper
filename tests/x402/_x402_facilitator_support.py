from __future__ import annotations

import pytest

from pry.payments.x402.facilitator import (
    DEFAULT_FACILITATORS,
    FacilitatorRouter,
)


@pytest.fixture
def _eip7702_ok(monkeypatch):
    """EIP-7702 settle fallback is only allowed with a verified receipt.

    The old tests asserted a free success receipt; the fallback now calls
    ``_eip7702_verify`` first. These tests exercise the "receipt exists" path.
    """
    from pry.payments.x402.facilitator import FacilitatorRouter

    async def _ok(*_a, **_k):
        return {"verified": True, "reason": ""}

    monkeypatch.setattr(FacilitatorRouter, "_eip7702_verify", _ok)

@pytest.fixture
def router() -> FacilitatorRouter:
    """Return a fresh FacilitatorRouter with default facilitators."""
    return FacilitatorRouter(facilitators=list(DEFAULT_FACILITATORS))
