# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Integration test: the REAL x402 verify chain (audit item #13).

Drives the production path end-to-end with ONLY the HTTP layer mocked
(respx) — the router, SelfFacilitator, CAIP-2 resolution, the EIP-3009
rejection, the EIP-7702 on-chain fallback and the settle fallback are all
real code:

    FacilitatorRouter.verify
      → _verify_self_hosted
        → SelfFacilitator.verify          (fails: plain transfer, no EIP-3009 auth)
        → _eip7702_verify(tx, network, …) (on-chain receipt fallback)
          → _eip7702_matches              (payTo + amount checks)

This guards the exact 3-bug chain fixed on 2026-09-01:
1. CAIP-2 resolution  — ``eip155:8453`` must reach the Base RPC (d2f51cf);
2. settle fallback    — a verified plain transfer must also SETTLE via the
  EIP-7702 receipt (verify ✓ → settle ✗ was a fail-closed 402 forever);
3. per-network payTo  — with the global ``X402_WALLET`` EMPTY (the prod
  condition that caught the bug), ``eip155:8453`` must resolve its payTo
  from ``X402_NETWORK_WALLETS``, not the empty global.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import httpx
import pytest
import respx

from pry.payments.x402.facilitator import FacilitatorRouter

# Test fixtures — NOT real wallets.
TEST_WALLET = "0x1111111111111111111111111111111111111111"
OTHER_WALLET = "0x2222222222222222222222222222222222222222"
USDC_BASE = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"
BASE_RPC = "https://mainnet.base.org/"
TX_HASH = "0xreal_tx"
AMOUNT_USD = 0.001  # USDC 6 decimals → 1000 atomic

RECEIPT = {"status": "0x1", "blockNumber": "0x123"}


def _transfer_calldata(recipient: str, atomic: int) -> str:
    """ERC-20 transfer(address,uint256) calldata: selector + padded args."""
    return "0xa9059cbb" + "0" * 24 + recipient[2:].lower() + hex(atomic)[2:].rjust(64, "0")


def _plain_transfer_tx(recipient: str, atomic: int) -> dict[str, Any]:
    """A real-shaped plain USDC transfer tx (eth_getTransactionByHash)."""
    return {
        "to": USDC_BASE,
        "from": "0xdead000000000000000000000000000000000000",
        "input": _transfer_calldata(recipient, atomic),
        "value": "0x0",
    }


def _rpc_responder(tx: dict[str, Any]):
    """respx side_effect serving receipt + tx lookup off one Base RPC URL."""

    def _callback(request: httpx.Request) -> httpx.Response:
        body = request.read().decode()
        if "eth_getTransactionReceipt" in body:
            return httpx.Response(200, json={"jsonrpc": "2.0", "result": dict(RECEIPT)})
        if "eth_getTransactionByHash" in body:
            return httpx.Response(200, json={"jsonrpc": "2.0", "result": dict(tx)})
        return httpx.Response(200, json={"jsonrpc": "2.0", "result": None})

    return _callback


@pytest.fixture
def router() -> FacilitatorRouter:
    """Self-hosted router with NO external facilitators (prod self-host mode)."""
    return FacilitatorRouter(facilitators=[], self_hosted=True)


@pytest.fixture
def chain_env():
    """Prod-shaped wallet config: global X402_WALLET EMPTY, per-network set.

    Patches the scheme-module globals that ``resolve_pay_to`` reads so
    ``eip155:8453`` resolves its payTo from ``X402_NETWORK_WALLETS`` — the
    exact condition that caught the per-network payTo bug.
    """
    with (
        patch("pry.payments.x402.facilitator.X402_OFFLINE_MODE", False),
        patch("pry.payments.x402.scheme.X402_WALLET", ""),
        patch(
            "pry.payments.x402.scheme.X402_NETWORK_WALLETS",
            {"eip155:8453": TEST_WALLET},
        ),
    ):
        yield


async def test_caip2_plain_transfer_verifies_end_to_end(router, chain_env):
    """CAIP-2 network + plain USDC transfer → verified via EIP-7702 fallback."""
    with respx.mock:
        rpc = respx.post(BASE_RPC).mock(
            side_effect=_rpc_responder(_plain_transfer_tx(TEST_WALLET, 1000))
        )
        result = await router.verify(
            "pay_1", TX_HASH, network="eip155:8453", asset="USDC", amount_usd=AMOUNT_USD
        )
    assert result["verified"] is True
    assert result["facilitator"] == "self-hosted-eip7702"
    # BOTH RPC legs ran: receipt + tx lookup.
    assert rpc.call_count == 2


async def test_wrong_recipient_rejected(router, chain_env):
    """A transfer to a DIFFERENT wallet must not verify (payTo mismatch)."""
    with respx.mock:
        respx.post(BASE_RPC).mock(
            side_effect=_rpc_responder(_plain_transfer_tx(OTHER_WALLET, 1000))
        )
        result = await router.verify(
            "pay_2", TX_HASH, network="eip155:8453", asset="USDC", amount_usd=AMOUNT_USD
        )
    assert result["verified"] is False
    assert "pay_to" in result["reason"] or "server wallet" in result["reason"]


async def test_underpayment_rejected(router, chain_env):
    """Paying 500 atomic when 1000 is required must not verify."""
    with respx.mock:
        respx.post(BASE_RPC).mock(side_effect=_rpc_responder(_plain_transfer_tx(TEST_WALLET, 500)))
        result = await router.verify(
            "pay_3", TX_HASH, network="eip155:8453", asset="USDC", amount_usd=AMOUNT_USD
        )
    assert result["verified"] is False
    assert "underpayment" in result["reason"]


async def test_chain_falls_back_when_eip3009_missing(router, chain_env):
    """Regression (CAIP-2 bug, d2f51cf): the EIP-7702 fallback RAN.

    The real SelfFacilitator.verify fails on a plain transfer ("missing
    EIP-3009 transferWithAuthorization"); the router must then reach the
    Base RPC. If the CAIP-2 → short-name resolution regresses, the fallback
    is skipped, the RPC is never contacted and verify fails with only the
    EIP-3009 reason.
    """
    with respx.mock:
        rpc = respx.post(BASE_RPC).mock(
            side_effect=_rpc_responder(_plain_transfer_tx(TEST_WALLET, 1000))
        )
        result = await router.verify(
            "pay_4", TX_HASH, network="eip155:8453", asset="USDC", amount_usd=AMOUNT_USD
        )
        assert rpc.call_count >= 1, "EIP-7702 fallback never contacted the Base RPC"
    assert result["verified"] is True
    assert result["facilitator"] == "self-hosted-eip7702"


async def test_settle_receipt_after_verified_plain_transfer(router, chain_env):
    """Settle fallback (bug #2): verified plain transfer must also settle.

    SelfFacilitator cannot broadcast a plain transfer (no authorization, no
    key/RPC → NOT_SETTLABLE), so the router must fall through to the
    EIP-7702 settlement receipt instead of failing closed forever.
    """
    with respx.mock:
        respx.post(BASE_RPC).mock(side_effect=_rpc_responder(_plain_transfer_tx(TEST_WALLET, 1000)))
        verified = await router.verify(
            "pay_5", TX_HASH, network="eip155:8453", asset="USDC", amount_usd=AMOUNT_USD
        )
        assert verified["verified"] is True

        settlement = await router.settle(
            "pay_5", TX_HASH, network="eip155:8453", asset="USDC", amount_usd=AMOUNT_USD
        )
    assert settlement["success"] is True
    assert settlement["facilitator"] == "eip-7702"
    assert settlement["transaction"] == TX_HASH
