"""Tests for x402/facilitator.py — FacilitatorRouter, multi-provider fallback."""
from tests.x402._x402_facilitator_support import _eip7702_ok, router  # noqa: F401
from unittest.mock import patch

import httpx
import pytest
import respx

from pry.payments.x402.facilitator import FacilitatorRouter


@pytest.mark.asyncio
async def test_verify_offline_always_succeeds(router: FacilitatorRouter):
    with patch("pry.payments.x402.facilitator.X402_OFFLINE_MODE", True):
        result = await router.verify(
            payment_id="pay_123",
            tx_hash="0xabc",
            network="base",
            asset="USDC",
            amount_usd=1.0,
        )
        assert result["verified"] is True
        assert result["reason"] == "offline_mode"
@pytest.mark.asyncio
async def test_verify_no_facilitators():
    empty = FacilitatorRouter(facilitators=[])
    with patch("pry.payments.x402.facilitator.X402_OFFLINE_MODE", False):
        result = await empty.verify(
            payment_id="pay_123",
            tx_hash="0xabc",
            network="base",
            asset="USDC",
            amount_usd=1.0,
        )
        assert result["verified"] is False
@pytest.mark.asyncio
async def test_verify_self_hosted_path(router: FacilitatorRouter):
    """When no facilitator handles the network, returns needs_facilitator."""
    router.self_hosted = False
    with patch("pry.payments.x402.facilitator.X402_OFFLINE_MODE", False):
        result = await router.verify(
            payment_id="pay_123",
            tx_hash="0xabc",
            network="tron:mainnet",
            asset="USDT",
            amount_usd=1.0,
        )
        assert "reason" in result
@pytest.mark.asyncio
async def test_verify_solana_path(router: FacilitatorRouter):
    """Solana uses the dedicated SPL verifier fallback."""
    with patch("pry.payments.x402.facilitator.X402_OFFLINE_MODE", False):
        result = await router.verify(
            payment_id="pay_123",
            tx_hash="4a3b...",
            network="tron:mainnet",
            asset="USDC",
            amount_usd=5.0,
        )
        assert "reason" in result
@respx.mock
@pytest.mark.asyncio
async def test_verify_via_external_facilitator(router: FacilitatorRouter):
    """Should verify via external facilitator HTTP call."""
    router.self_hosted = False
    with patch("pry.payments.x402.facilitator.X402_OFFLINE_MODE", False):
        for f in router.facilitators:
            if f.verify_url:
                respx.post(f.verify_url).mock(
                    return_value=httpx.Response(200, json={"isValid": True, "txHash": "0xabc"})
                )
        result = await router.verify(
            payment_id="pay_123",
            tx_hash="0xabc",
            network="base",
            asset="USDC",
            amount_usd=1.0,
        )
        assert result["verified"] is True
@respx.mock
@pytest.mark.asyncio
async def test_verify_external_http_error(router: FacilitatorRouter):
    """Should handle HTTP 500 from external facilitator gracefully."""
    router.self_hosted = False
    with patch("pry.payments.x402.facilitator.X402_OFFLINE_MODE", False):
        for f in router.facilitators:
            if f.verify_url:
                respx.post(f.verify_url).mock(return_value=httpx.Response(500, text="Server Error"))
        result = await router.verify(
            payment_id="pay_123",
            tx_hash="0xabc",
            network="tron:mainnet",
            asset="USDC",
            amount_usd=1.0,
        )
        assert "verified" in result
@respx.mock
@pytest.mark.asyncio
async def test_verify_external_network_error(router: FacilitatorRouter):
    """Should handle network error from external facilitator."""
    router.self_hosted = False
    with patch("pry.payments.x402.facilitator.X402_OFFLINE_MODE", False):
        for f in router.facilitators:
            if f.verify_url:
                respx.post(f.verify_url).mock(side_effect=httpx.ConnectError("connection refused"))
        result = await router.verify(
            payment_id="pay_123",
            tx_hash="0xabc",
            network="tron:mainnet",
            asset="USDC",
            amount_usd=1.0,
        )
        assert "verified" in result
@respx.mock
@pytest.mark.asyncio
async def test_verify_external_invalid_json(router: FacilitatorRouter):
    """Should handle non-JSON response from external facilitator."""
    router.self_hosted = False
    with patch("pry.payments.x402.facilitator.X402_OFFLINE_MODE", False):
        for f in router.facilitators:
            if f.verify_url:
                respx.post(f.verify_url).mock(return_value=httpx.Response(200, text="not-json"))
        result = await router.verify(
            payment_id="pay_123",
            tx_hash="0xabc",
            network="tron:mainnet",
            asset="USDC",
            amount_usd=1.0,
        )
        assert "verified" in result
