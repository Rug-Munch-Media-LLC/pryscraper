"""Tests for x402/facilitator.py — FacilitatorRouter, multi-provider fallback."""
from tests.x402._gate_support import db, no_owner_key  # noqa: F401
from unittest.mock import patch

import httpx
import pytest
import respx

from pry.payments.x402.facilitator import FacilitatorRouter


@pytest.mark.asyncio
async def test_settle_offline(router: FacilitatorRouter):
    with patch("pry.payments.x402.facilitator.X402_OFFLINE_MODE", True):
        result = await router.settle(
            payment_id="pay_123",
            tx_hash="0xabc",
            network="base",
            asset="USDC",
            amount_usd=1.0,
        )
        assert result["success"] is True
        assert result["facilitator"] == "offline"
        assert result["transaction"] == "0xabc"
@pytest.mark.asyncio
async def test_settle_no_client_ip(router: FacilitatorRouter):
    """Settle works without needing a client_ip."""
    with patch("pry.payments.x402.facilitator.X402_OFFLINE_MODE", True):
        result = await router.settle(
            payment_id="pay_123",
            tx_hash="0xabc",
            network="base",
            asset="USDC",
            amount_usd=1.0,
        )
        assert result["success"] is True
        assert result["facilitator"] == "offline"
        assert result["payment_id"] == "pay_123"
@respx.mock
@pytest.mark.asyncio
async def test_settle_via_external_facilitator(router: FacilitatorRouter):
    """Should settle via external facilitator HTTP call."""
    with patch("pry.payments.x402.facilitator.X402_OFFLINE_MODE", False):
        router.self_hosted = False
        for f in router.facilitators:
            if f.settle_url:
                respx.post(f.settle_url).mock(
                    return_value=httpx.Response(200, json={"success": True, "txHash": "0xsettled"})
                )
        result = await router.settle(
            payment_id="pay_123",
            tx_hash="0xabc",
            network="base",
            asset="USDC",
            amount_usd=1.0,
        )
        # Weighted random selection picks any healthy facilitator; all are
        # mocked with the same success response, so the receipt must reflect
        # the on-chain tx and one of the configured facilitator names.
        assert result["success"] is True
        assert result["transaction"] == "0xabc"
        assert result["facilitator"] in {f.name for f in router.facilitators if f.settle_url}
@respx.mock
@pytest.mark.asyncio
@pytest.mark.usefixtures("_eip7702_ok")
async def test_settle_external_http_error(router: FacilitatorRouter):
    """Should handle HTTP error from external settle."""
    with patch("pry.payments.x402.facilitator.X402_OFFLINE_MODE", False):
        router.self_hosted = False
        for f in router.facilitators:
            if f.settle_url:
                respx.post(f.settle_url).mock(return_value=httpx.Response(500, text="error"))
        result = await router.settle(
            payment_id="pay_123",
            tx_hash="0xabc",
            network="base",
            asset="USDC",
            amount_usd=1.0,
        )
        # All external facilitators failed (HTTP 500) → EIP-7702 fallback
        # settlement receipt for the EVM chain.
        assert result["success"] is True
        assert result["facilitator"] == "eip-7702"
        assert result["transaction"] == "0xabc"
@respx.mock
@pytest.mark.asyncio
async def test_settle_self_hosted(router: FacilitatorRouter):
    """Should settle via self-hosted path."""
    with patch("pry.payments.x402.facilitator.X402_OFFLINE_MODE", False):
        router.self_hosted = True
        result = await router.settle(
            payment_id="pay_123",
            tx_hash="0xabc",
            network="optimism",
            asset="USDC",
            amount_usd=1.0,
        )
        # SelfFacilitator has no RPC/key to broadcast, so the EVM settle falls
        # through to the EIP-7702 settlement receipt.
        assert result["success"] is True
        assert result["facilitator"] == "eip-7702"
        assert result["transaction"] == "0xabc"
@respx.mock
@pytest.mark.asyncio
@pytest.mark.usefixtures("_eip7702_ok")
async def test_settle_external_all_fail(router: FacilitatorRouter):
    """When all external facilitators fail, the EIP-7702 fallback settles."""
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
        # All external facilitators unreachable → EIP-7702 settlement receipt.
        assert result["success"] is True
        assert result["facilitator"] == "eip-7702"
        assert result["transaction"] == "0xabc"
