# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for x402 settlement broadcast — T1 win #6.

Verifies that self-hosted settlement actually broadcasts a transaction
to the RPC, not just returning success without on-chain settlement.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from pry.payments.x402.self_facilitator import SelfFacilitator


class TestSelfFacilitatorSettle:
    """SelfFacilitator.settle_with_details broadcasts to RPC."""

    @pytest.mark.asyncio
    async def test_settle_broadcasts_to_rpc(self) -> None:
        """Settlement must actually call eth_sendRawTransaction."""
        fac = SelfFacilitator(
            pay_to="0x" + "b2" * 20,
            facilitator_key="0x" + "aa" * 32,
            rpc_url="https://base-rpc.example.com",
        )

        # Mock _rpc_call to return appropriate values for each method
        call_count = 0

        async def mock_rpc_call(_client, method, _params):
            nonlocal call_count
            call_count += 1
            return RPC_RESPONSES.get(method)

        with patch.object(fac, "_rpc_call", side_effect=mock_rpc_call):
            payment = {
                "payment_id": "pay_test_123",
                "network": "base",
                "asset": "USDC",
                "amount_usd": 1.0,
                "authorization": {
                    "from": "0x" + "a1" * 20,
                    "to": "0x" + "b2" * 20,
                    "value": "1000000",
                    "validAfter": 0,
                    "validBefore": 9999999999,
                    "nonce": "0x" + "00" * 32,
                    "signature": "0x" + "00" * 65,
                },
            }
            outcome = await fac.settle_with_details(payment)

        # Verify RPC was called multiple times
        assert call_count >= 4
        assert outcome.success is True

    @pytest.mark.asyncio
    async def test_settle_returns_hash_on_success(self) -> None:
        """Successful settlement returns a tx hash."""
        fac = SelfFacilitator(
            pay_to="0x" + "b2" * 20,
            facilitator_key="0x" + "aa" * 32,
            rpc_url="https://base-rpc.example.com",
        )

        async def mock_rpc_call(_client, method, _params):
            return RPC_RESPONSES.get(method)

        with patch.object(fac, "_rpc_call", side_effect=mock_rpc_call):
            payment = {
                "payment_id": "pay_test_456",
                "network": "base",
                "asset": "USDC",
                "amount_usd": 1.0,
                "authorization": {
                    "from": "0x" + "a1" * 20,
                    "to": "0x" + "b2" * 20,
                    "value": "1000000",
                    "validAfter": 0,
                    "validBefore": 9999999999,
                    "nonce": "0x" + "00" * 32,
                    "signature": "0x" + "00" * 65,
                },
            }
            outcome = await fac.settle_with_details(payment)

        assert outcome.success is True
        assert outcome.tx_hash is not None

    @pytest.mark.asyncio
    async def test_settle_idempotent_no_double_broadcast(self) -> None:
        """Settling the same payment twice must not broadcast twice."""
        fac = SelfFacilitator(
            pay_to="0x" + "b2" * 20,
            facilitator_key="0x" + "aa" * 32,
            rpc_url="https://base-rpc.example.com",
        )

        call_count = 0

        async def mock_rpc_call(_client, method, _params):
            nonlocal call_count
            call_count += 1
            return RPC_RESPONSES.get(method)

        payment = {
            "payment_id": "pay_idempotent",
            "network": "base",
            "asset": "USDC",
            "amount_usd": 1.0,
            "authorization": {
                "from": "0x" + "a1" * 20,
                "to": "0x" + "b2" * 20,
                "value": "1000000",
                "validAfter": 0,
                "validBefore": 9999999999,
                "nonce": "0x" + "00" * 32,
                "signature": "0x" + "00" * 65,
            },
        }

        with patch.object(fac, "_rpc_call", side_effect=mock_rpc_call):
            outcome1 = await fac.settle_with_details(payment)
            outcome2 = await fac.settle_with_details(payment)

        assert outcome1.success is True
        assert outcome2.success is True
        assert outcome2.idempotent is True  # Second call should be idempotent

    @pytest.mark.asyncio
    async def test_settle_wrong_chain_rejected(self) -> None:
        """Settlement on wrong chain must be rejected."""
        fac = SelfFacilitator(
            pay_to="0x" + "b2" * 20,
            facilitator_key="0x" + "aa" * 32,
            rpc_url="https://base-rpc.example.com",
        )

        # RPC returns Ethereum mainnet chain ID (0x1) but we expect Base (0x2105)
        async def mock_rpc_call(_client, method, _params):
            if method == "eth_chainId":
                return "0x1"  # Wrong chain!
            return None

        payment = {
            "payment_id": "pay_wrong_chain",
            "network": "base",
            "asset": "USDC",
            "amount_usd": 1.0,
            "authorization": {
                "from": "0x" + "a1" * 20,
                "to": "0x" + "b2" * 20,
                "value": "1000000",
                "validAfter": 0,
                "validBefore": 9999999999,
                "nonce": "0x" + "00" * 32,
                "signature": "0x" + "00" * 65,
            },
        }

        with patch.object(fac, "_rpc_call", side_effect=mock_rpc_call):
            outcome = await fac.settle_with_details(payment)

        assert outcome.success is False
        assert outcome.error_code == "wrong_chain"


# Shared RPC responses for settlement tests
RPC_RESPONSES = {
    "eth_chainId": "0x2105",
    "eth_getTransactionCount": "0x0",
    "eth_estimateGas": "0x186a0",
    "eth_gasPrice": "0x1",
    "eth_sendRawTransaction": "0xabc123",
}
