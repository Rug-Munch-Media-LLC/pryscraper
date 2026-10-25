"""Tests for x402/facilitator.py — FacilitatorRouter, multi-provider fallback."""
from unittest.mock import patch

import httpx
import pytest
import respx

from pry.payments.x402.facilitator import FacilitatorRouter


@respx.mock
@pytest.mark.asyncio
async def test_verify_eip7702_fallback_caip2_network(router: FacilitatorRouter):
    """The EIP-7702 fallback fires when the flow passes a CAIP-2 network id.

    Regression test for the CAIP-2 → short-name gap: with CAIP-2 input the
    old ``network in EIP7702_RPC`` guard was always False, so the on-chain
    fallback was silently skipped for every EVM chain.
    """
    with patch("pry.payments.x402.facilitator.X402_OFFLINE_MODE", False):
        router.self_hosted = False
        for f in router.facilitators:
            if f.verify_url:
                respx.post(f.verify_url).mock(return_value=httpx.Response(500, text="down"))

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

        base_rpc = respx.post("https://mainnet.base.org/").mock(side_effect=_rpc_callback)
        result = await router.verify(
            payment_id="pay_123",
            tx_hash="0xabc",
            network="eip155:8453",
            asset="USDC",
            amount_usd=1.0,
        )
        assert "verified" in result
        # The Base RPC was actually contacted — proof the CAIP-2 id resolved.
        assert base_rpc.called
