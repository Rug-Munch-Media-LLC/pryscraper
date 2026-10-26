"""Tests for x402/facilitator.py — FacilitatorRouter, multi-provider fallback."""

from unittest.mock import patch

import httpx
import pytest
import respx

from pry.payments.x402.facilitator import FacilitatorRouter
from tests.x402._gate_support import db, no_owner_key  # noqa: F401


@respx.mock
@pytest.mark.asyncio
@pytest.mark.usefixtures("_eip7702_ok")
async def test_settle_external_json_error(router: FacilitatorRouter):
    """Handle non-JSON response from external settle."""
    with patch("pry.payments.x402.facilitator.X402_OFFLINE_MODE", False):
        router.self_hosted = False
        for f in router.facilitators:
            if f.settle_url:
                respx.post(f.settle_url).mock(return_value=httpx.Response(200, text="not-json"))
        result = await router.settle(
            payment_id="pay_123",
            tx_hash="0xabc",
            network="base",
            asset="USDC",
            amount_usd=1.0,
        )
        # All external facilitators returned non-JSON → EIP-7702 fallback.
        assert result["success"] is True
        assert result["facilitator"] == "eip-7702"
        assert result["transaction"] == "0xabc"


@respx.mock
@pytest.mark.asyncio
async def test_settle_external_fail_without_receipt_is_not_success(
    router: FacilitatorRouter, monkeypatch
):
    """P0: no healthy facilitator AND no on-chain receipt => success False."""
    from pry.payments.x402.facilitator import FacilitatorRouter

    async def _not_verified(*_a, **_k):
        return {"verified": False, "reason": "receipt not found"}

    monkeypatch.setattr(FacilitatorRouter, "_eip7702_verify", _not_verified)
    with patch("pry.payments.x402.facilitator.X402_OFFLINE_MODE", False):
        router.self_hosted = False
        for f in router.facilitators:
            if f.settle_url:
                respx.post(f.settle_url).mock(side_effect=httpx.ConnectError("all down"))
        result = await router.settle(
            payment_id="pay_123",
            tx_hash="0xabc",
            network="base",
            asset="USDC",
            amount_usd=1.0,
        )
    assert result["success"] is False
    assert result["reason"] == "receipt not found"


@pytest.mark.asyncio
async def test_settle_self_hosted_plain_transfer_gets_eip7702_receipt():
    """A verified plain transfer (no EIP-3009 authorization) must still SETTLE.

    Regression: verify ✓ (EIP-7702 receipt check) → settle ✗ (SelfFacilitator
    has nothing to broadcast) → middleware fail-closed 402 forever. The
    settle leg must fall through to the EIP-7702 settlement receipt exactly
    like the verify leg falls through to the EIP-7702 verify.
    """
    router = FacilitatorRouter(facilitators=[], self_hosted=True)
    result = await router._settle_self_hosted("pay_123", "0xabc", "eip155:8453", "USDC", 0.001)
    assert result["success"] is True
    assert result["facilitator"] == "eip-7702"
    assert result["transaction"] == "0xabc"
    assert result["network"] == "eip155:8453"


@pytest.mark.asyncio
async def test_settle_self_hosted_non_evm_still_fails_honestly():
    """Non-EVM chains have no settlement verifier — must stay an honest failure."""
    router = FacilitatorRouter(facilitators=[], self_hosted=True)
    result = await router._settle_self_hosted("pay_123", "sig123", "solana:mainnet", "USDC", 0.001)
    assert result["success"] is False
    assert "unavailable" in result["reason"]
