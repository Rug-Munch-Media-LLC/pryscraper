# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Licensed under MIT. See LICENSE.
"""Tests for x402/facilitator.py — FacilitatorRouter, multi-provider fallback."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pry.payments.x402.facilitator import (
    DEFAULT_FACILITATORS,
    FacilitatorRouter,
)


@pytest.fixture
def router() -> FacilitatorRouter:
    """Return a fresh FacilitatorRouter with default facilitators."""
    return FacilitatorRouter(facilitators=list(DEFAULT_FACILITATORS))


# ---------------------------------------------------------------------------
# FacilitatorConfig
# ---------------------------------------------------------------------------


def test_scaffold_non_evm_verify(router: FacilitatorRouter):
    """Scaffold verify for non-EVM chains returns structured response."""
    result = router._scaffold_non_evm_verify(
        "pay_123",
        "0xabc",
        "tron:mainnet",
        "USDT",
        1.0,
    )
    assert result["verified"] is False
    assert "reason" in result


# ---------------------------------------------------------------------------
# SelfFacilitator integration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_settle_self_hosted_without_impl(router: FacilitatorRouter):
    """Self-hosted settle without a registered impl uses SelfFacilitator."""
    router.self_hosted = True
    with patch("pry.payments.x402.facilitator.X402_OFFLINE_MODE", False):
        result = await router.settle(
            payment_id="pay_123",
            tx_hash="0xabc",
            network="optimism",
            asset="USDC",
            amount_usd=1.0,
        )
        # SelfFacilitator can't broadcast (no RPC/key) → EIP-7702 fallback.
        assert result["success"] is True
        assert result["facilitator"] == "eip-7702"
        assert result["transaction"] == "0xabc"


# ---------------------------------------------------------------------------
# _verify_self_hosted with custom impl
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_verify_self_hosted_custom_impl(router: FacilitatorRouter):
    """Self-hosted verify with a registered custom impl."""
    from pry.payments.x402.self_facilitator import VerifyResult

    router.self_hosted = True
    mock_impl = MagicMock()
    mock_impl.verify = AsyncMock(
        return_value=VerifyResult(
            verified=True,
            reason="",
            signer="0xabc",
            amount_atomic=1000000,
            asset="USDC",
            network="solana:mainnet",
        )
    )
    router.register_facilitator("solana:mainnet", mock_impl)
    with patch("pry.payments.x402.facilitator.X402_OFFLINE_MODE", False):
        result = await router.verify(
            payment_id="pay_123",
            tx_hash="0xabc",
            network="solana:mainnet",
            asset="USDC",
            amount_usd=1.0,
        )
        assert result["verified"] is True


# ---------------------------------------------------------------------------
# _verify_self_hosted without any impl
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_verify_self_hosted_no_impl(router: FacilitatorRouter):
    """Self-hosted verify without specific impl uses SelfFacilitator."""
    router.self_hosted = True
    with patch("pry.payments.x402.facilitator.X402_OFFLINE_MODE", False):
        result = await router.verify(
            payment_id="pay_123",
            tx_hash="0xabc",
            network="unknown:chain",
            asset="USDC",
            amount_usd=1.0,
        )
        assert "reason" in result


def test_eip7702_matches_uses_per_network_wallet(monkeypatch):
    """The EIP-7702 match check must resolve payTo PER NETWORK.

    Regression: the check read the global X402_WALLET (unset on prod where
    only PRY_X402_WALLET_* per-network wallets are configured), so every
    real payment failed with "server wallet not configured" even though the
    challenge quoted the correct per-network payTo.
    """
    import pry.payments.x402.facilitator as fac
    import pry.payments.x402.scheme as scheme_mod

    wallet = "0x1E3AC01d0fdb976179790BDD02823196A92705C9"
    token = __import__(
        "pry.payments.x402", fromlist=["EIP7702_TOKEN_ADDRESSES"]
    ).EIP7702_TOKEN_ADDRESSES["base"]["USDC"]
    calldata = "0xa9059cbb" + "0" * 24 + wallet[2:].lower() + hex(1000)[2:].rjust(64, "0")
    tx = {"to": token.lower(), "input": calldata, "value": "0x0"}

    monkeypatch.setattr(scheme_mod, "X402_WALLET", "")  # global unset (prod state)
    # The per-network wallet map is the resolution source in that state —
    # set it explicitly so the test is hermetic (CI has no wallet env).
    monkeypatch.setattr(scheme_mod, "X402_NETWORK_WALLETS", {"eip155:8453": wallet})
    result = fac.FacilitatorRouter._eip7702_matches(None, tx, "eip155:8453", "USDC", 0.001)
    assert result[0] is True, f"per-network wallet must satisfy the payTo check: {result}"
