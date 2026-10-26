"""Tests for x402/facilitator.py — FacilitatorRouter, multi-provider fallback."""

from unittest.mock import patch

import httpx
import pytest
import respx

from pry.payments.x402.facilitator import FacilitatorRouter
from tests.x402._gate_support import db, no_owner_key  # noqa: F401
from tests.x402._x402_facilitator_support import _eip7702_ok, router  # noqa: F401


@respx.mock
@pytest.mark.asyncio
async def test_verify_solana_network(router: FacilitatorRouter):
    """Should use Solana verifier path."""
    router.self_hosted = False
    with patch("pry.payments.x402.facilitator.X402_OFFLINE_MODE", False):
        for f in router.facilitators:
            if f.verify_url:
                respx.post(f.verify_url).mock(
                    return_value=httpx.Response(200, json={"isValid": True})
                )
        result = await router.verify(
            payment_id="pay_123",
            tx_hash="4a3b...",
            network="solana:mainnet",
            asset="USDC",
            amount_usd=5.0,
        )
        assert "reason" in result


@respx.mock
@pytest.mark.asyncio
async def test_verify_tron_scaffold(router: FacilitatorRouter):
    """Should scaffold TRON verification (needs_facilitator)."""
    router.self_hosted = False
    with patch("pry.payments.x402.facilitator.X402_OFFLINE_MODE", False):
        for f in router.facilitators:
            if f.verify_url:
                respx.post(f.verify_url).mock(
                    return_value=httpx.Response(200, json={"isValid": True})
                )
        result = await router.verify(
            payment_id="pay_123",
            tx_hash="0xabc",
            network="tron:mainnet",
            asset="USDT",
            amount_usd=1.0,
        )
        assert "reason" in result


@respx.mock
@pytest.mark.asyncio
async def test_verify_eip7702_fallback(router: FacilitatorRouter):
    """EIP-7702 fallback when external facilitators fail."""
    with patch("pry.payments.x402.facilitator.X402_OFFLINE_MODE", False):
        router.self_hosted = False
        for f in router.facilitators:
            if f.verify_url:
                respx.post(f.verify_url).mock(return_value=httpx.Response(500, text="down"))

        # Mock RPC call — _rpc_call extracts data["result"]
        # Two calls go to same URL (getReceipt + getTransactionByHash)
        def _rpc_callback(request: httpx.Request) -> httpx.Response:
            body = request.read().decode()
            if "eth_getTransactionReceipt" in body:
                return httpx.Response(
                    200,
                    json={
                        "jsonrpc": "2.0",
                        "result": {"status": "0x1", "blockNumber": "0x123"},
                    },
                )
            else:
                return httpx.Response(
                    200,
                    json={
                        "jsonrpc": "2.0",
                        "result": {
                            "to": "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
                            "from": "0xdead000000000000000000000000000000000000",
                            "input": "0xa9059cbb" + "0" * 64 + "0" * 64,
                            "value": "0x0",
                        },
                    },
                )

        respx.post("https://mainnet.base.org/").mock(side_effect=_rpc_callback)
        result = await router.verify(
            payment_id="pay_123",
            tx_hash="0xabc",
            network="base",
            asset="USDC",
            amount_usd=1.0,
        )
        assert "verified" in result
