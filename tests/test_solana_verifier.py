"""Tests for the Solana SPL USDC x402 verifier (x402/solana_verifier.py).

Covers the never-raise contract of ``verify_solana_payment``: valid USDC
``transferChecked`` to the expected recipient verifies True; wrong
recipient / wrong mint / underpayment / not-found / RPC error / malformed
all verify False with a precise reason. Also covers the
``FacilitatorRouter`` wiring (solana routes to the RPC verifier, not the
scaffold) and the scheme VERIFICATION_STATUS flip to "live".
"""
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx

from pry.payments.x402 import SOLANA_USDC_MINT, network_verification_status
from pry.payments.x402.facilitator import FacilitatorRouter
from pry.payments.x402.solana_verifier import (
    DEFAULT_SOLANA_RPC_URL,
    SPL_TOKEN_PROGRAM_ID,
    verify_solana_payment,
)

# A plausible Solana base58 wallet (44 chars, not a real address).
RECIPIENT = "3scSEc7HrLkv5J5JsCQSEzG2wPb2NfCWqTr9sCefhYQw"
OTHER_RECIPIENT = "9xQeWvG816bUx9EPjHmaT23yvVM2ZWbrrpZb9PusVFin"

USDC_AMOUNT_ATOMIC = 2_000_000  # 2 USDC


def _parsed_transfer_checked(
    mint: str,
    destination: str,
    amount: int,
    decimals: int = 6,
) -> dict[str, Any]:
    """Build a jsonParsed splToken transferChecked instruction fixture."""
    return {
        "program": "splToken",
        "programId": SPL_TOKEN_PROGRAM_ID,
        "parsed": {
            "type": "transferChecked",
            "info": {
                "amount": str(amount),
                "authority": "auth111111111111111111111111111111111111111",
                "destination": destination,
                "mint": mint,
                "source": "src11111111111111111111111111111111111111111",
                "tokenAmount": {
                    "amount": str(amount),
                    "decimals": decimals,
                    "uiAmount": amount / (10**decimals),
                },
            },
        },
    }


def _rpc_result(
    instructions: list[dict[str, Any]] | None = None,
    inner_instructions: list[dict[str, Any]] | None = None,
    err: Any = None,
    slot: int | None = 123,
    block_time: int | None = 1_700_000_000,
    transaction: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a getTransaction jsonParsed ``result`` fixture."""
    if transaction is None:
        transaction = {"message": {"instructions": instructions or []}}
    return {
        "slot": slot,
        "blockTime": block_time,
        "transaction": transaction,
        "meta": {"err": err, "innerInstructions": inner_instructions or []},
    }


def _ok_response(result: Any) -> httpx.Response:
    return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": result})


# ── verify_solana_payment: happy path ────────────────────────────────────────


@pytest.mark.asyncio
@respx.mock
async def test_verify_valid_usdc_transfer_checked() -> None:
    respx.post(DEFAULT_SOLANA_RPC_URL).mock(
        return_value=_ok_response(
            _rpc_result(
                instructions=[
                    _parsed_transfer_checked(SOLANA_USDC_MINT, RECIPIENT, USDC_AMOUNT_ATOMIC)
                ]
            )
        )
    )
    result = await verify_solana_payment("sig-abc", RECIPIENT, 1.0)
    assert result["verified"] is True
    assert result["reason"] == ""
    assert result["recipient"] == RECIPIENT
    assert result["amount_raw"] == USDC_AMOUNT_ATOMIC
    assert result["amount_decimals"] == 6
    assert result["amount_usd"] == 2.0
    assert result["mint"] == SOLANA_USDC_MINT
    assert result["confirmed_at"].startswith("2023-11-14T22:13:20")
    assert result["slot"] == 123


@pytest.mark.asyncio
@respx.mock
async def test_verify_valid_usdc_in_inner_instructions() -> None:
    """Inner (CPI) transferChecked instructions are walked too."""
    inner = [
        {
            "index": 0,
            "instructions": [
                _parsed_transfer_checked(SOLANA_USDC_MINT, RECIPIENT, USDC_AMOUNT_ATOMIC)
            ],
        }
    ]
    respx.post(DEFAULT_SOLANA_RPC_URL).mock(
        return_value=_ok_response(_rpc_result(inner_instructions=inner))
    )
    result = await verify_solana_payment("sig-abc", RECIPIENT, 1.0)
    assert result["verified"] is True
    assert result["amount_usd"] == 2.0


@pytest.mark.asyncio
@respx.mock
async def test_verify_multiple_transfers_takes_largest() -> None:
    """Several USDC transfers — the largest to the recipient wins."""
    respx.post(DEFAULT_SOLANA_RPC_URL).mock(
        return_value=_ok_response(
            _rpc_result(
                instructions=[
                    _parsed_transfer_checked(SOLANA_USDC_MINT, RECIPIENT, 500_000),
                    _parsed_transfer_checked(SOLANA_USDC_MINT, RECIPIENT, 7_500_000),
                ]
            )
        )
    )
    result = await verify_solana_payment("sig-abc", RECIPIENT, 1.0)
    assert result["verified"] is True
    assert result["amount_raw"] == 7_500_000
    assert result["amount_usd"] == 7.5


@pytest.mark.asyncio
@respx.mock
async def test_verify_overpayment_allowed() -> None:
    respx.post(DEFAULT_SOLANA_RPC_URL).mock(
        return_value=_ok_response(
            _rpc_result(
                instructions=[
                    _parsed_transfer_checked(SOLANA_USDC_MINT, RECIPIENT, USDC_AMOUNT_ATOMIC)
                ]
            )
        )
    )
    result = await verify_solana_payment("sig-abc", RECIPIENT, 0.1)
    assert result["verified"] is True


# ── verify_solana_payment: failure paths (never raise) ──────────────────────


@pytest.mark.asyncio
@respx.mock
async def test_verify_wrong_recipient() -> None:
    respx.post(DEFAULT_SOLANA_RPC_URL).mock(
        return_value=_ok_response(
            _rpc_result(
                instructions=[
                    _parsed_transfer_checked(SOLANA_USDC_MINT, OTHER_RECIPIENT, USDC_AMOUNT_ATOMIC)
                ]
            )
        )
    )
    result = await verify_solana_payment("sig-abc", RECIPIENT, 1.0)
    assert result["verified"] is False
    assert "wrong_recipient" in result["reason"]


@pytest.mark.asyncio
@respx.mock
async def test_verify_wrong_mint() -> None:
    """A transferChecked to the recipient of a NON-USDC mint is rejected."""
    other_mint = "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"  # USDT
    respx.post(DEFAULT_SOLANA_RPC_URL).mock(
        return_value=_ok_response(
            _rpc_result(
                instructions=[_parsed_transfer_checked(other_mint, RECIPIENT, USDC_AMOUNT_ATOMIC)]
            )
        )
    )
    result = await verify_solana_payment("sig-abc", RECIPIENT, 1.0)
    assert result["verified"] is False
    assert "wrong_mint" in result["reason"]


@pytest.mark.asyncio
@respx.mock
async def test_verify_insufficient_amount() -> None:
    respx.post(DEFAULT_SOLANA_RPC_URL).mock(
        return_value=_ok_response(
            _rpc_result(
                instructions=[_parsed_transfer_checked(SOLANA_USDC_MINT, RECIPIENT, 500_000)]
            )
        )
    )
    result = await verify_solana_payment("sig-abc", RECIPIENT, 1.0)
    assert result["verified"] is False
    assert "underpayment" in result["reason"]
    assert "paid 0.500000 USDC" in result["reason"]


@pytest.mark.asyncio
@respx.mock
async def test_verify_amount_with_usdc_price() -> None:
    """Required amount scales by usdc_price_usd (non-1:1 USDC price)."""
    respx.post(DEFAULT_SOLANA_RPC_URL).mock(
        return_value=_ok_response(
            _rpc_result(
                instructions=[_parsed_transfer_checked(SOLANA_USDC_MINT, RECIPIENT, 500_000)]
            )
        )
    )
    # 0.5 USDC at 0.5 USD/USDC covers a 0.25 USD requirement.
    result = await verify_solana_payment("sig-abc", RECIPIENT, 0.25, usdc_price_usd=0.5)
    assert result["verified"] is True
    assert result["amount_usd"] == 0.25


@pytest.mark.asyncio
@respx.mock
async def test_verify_transaction_not_found() -> None:
    respx.post(DEFAULT_SOLANA_RPC_URL).mock(return_value=_ok_response(None))
    result = await verify_solana_payment("sig-missing", RECIPIENT, 1.0)
    assert result["verified"] is False
    assert result["reason"] == "transaction_not_found"


@pytest.mark.asyncio
@respx.mock
async def test_verify_rpc_http_error() -> None:
    respx.post(DEFAULT_SOLANA_RPC_URL).mock(return_value=httpx.Response(500))
    result = await verify_solana_payment("sig-abc", RECIPIENT, 1.0)
    assert result["verified"] is False
    assert result["reason"] == "rpc_http_error: 500"


@pytest.mark.asyncio
@respx.mock
async def test_verify_rpc_network_error() -> None:
    respx.post(DEFAULT_SOLANA_RPC_URL).mock(side_effect=httpx.ConnectError("boom"))
    result = await verify_solana_payment("sig-abc", RECIPIENT, 1.0)
    assert result["verified"] is False
    assert "rpc_error" in result["reason"]


@pytest.mark.asyncio
@respx.mock
async def test_verify_rpc_jsonrpc_error_object() -> None:
    respx.post(DEFAULT_SOLANA_RPC_URL).mock(
        return_value=httpx.Response(
            200,
            json={"jsonrpc": "2.0", "id": 1, "error": {"code": -32000, "message": "invalid"}},
        )
    )
    result = await verify_solana_payment("sig-abc", RECIPIENT, 1.0)
    assert result["verified"] is False
    assert "rpc_error_response" in result["reason"]


@pytest.mark.asyncio
@respx.mock
async def test_verify_malformed_response_not_dict() -> None:
    respx.post(DEFAULT_SOLANA_RPC_URL).mock(
        return_value=httpx.Response(200, content=b"not json at all")
    )
    result = await verify_solana_payment("sig-abc", RECIPIENT, 1.0)
    assert result["verified"] is False
    assert result["reason"].startswith("rpc_invalid_json")


@pytest.mark.asyncio
@respx.mock
async def test_verify_malformed_result_type() -> None:
    respx.post(DEFAULT_SOLANA_RPC_URL).mock(return_value=_ok_response("oops"))
    result = await verify_solana_payment("sig-abc", RECIPIENT, 1.0)
    assert result["verified"] is False
    assert result["reason"] == "rpc_malformed_result"


@pytest.mark.asyncio
@respx.mock
async def test_verify_failed_transaction_meta_err() -> None:
    respx.post(DEFAULT_SOLANA_RPC_URL).mock(
        return_value=_ok_response(_rpc_result(err={"InstructionError": [0, {"Custom": 1}]}))
    )
    result = await verify_solana_payment("sig-abc", RECIPIENT, 1.0)
    assert result["verified"] is False
    assert result["reason"].startswith("transaction_failed")


@pytest.mark.asyncio
@respx.mock
async def test_verify_not_confirmed_no_slot() -> None:
    respx.post(DEFAULT_SOLANA_RPC_URL).mock(
        return_value=_ok_response(
            _rpc_result(
                slot=None,
                instructions=[
                    _parsed_transfer_checked(SOLANA_USDC_MINT, RECIPIENT, USDC_AMOUNT_ATOMIC)
                ],
            )
        )
    )
    result = await verify_solana_payment("sig-abc", RECIPIENT, 1.0)
    assert result["verified"] is False
    assert result["reason"] == "transaction_not_confirmed"


@pytest.mark.asyncio
@respx.mock
async def test_verify_no_transfer_instruction() -> None:
    respx.post(DEFAULT_SOLANA_RPC_URL).mock(
        return_value=_ok_response(
            _rpc_result(
                instructions=[
                    {
                        "program": "system",
                        "programId": "11111111111111111111111111111111",
                        "parsed": {"type": "transfer", "info": {}},
                    }
                ]
            )
        )
    )
    result = await verify_solana_payment("sig-abc", RECIPIENT, 1.0)
    assert result["verified"] is False
    assert "no_usdc_transfer_found" in result["reason"]


# ── verify_solana_payment: input validation (never raise, no RPC) ───────────


@pytest.mark.asyncio
async def test_verify_missing_signature() -> None:
    result = await verify_solana_payment("", RECIPIENT, 1.0)
    assert result["verified"] is False
    assert result["reason"] == "missing tx signature"


@pytest.mark.asyncio
async def test_verify_missing_recipient() -> None:
    result = await verify_solana_payment("sig-abc", "", 1.0)
    assert result["verified"] is False
    assert result["reason"] == "missing expected recipient"


@pytest.mark.asyncio
async def test_verify_negative_amount() -> None:
    result = await verify_solana_payment("sig-abc", RECIPIENT, -1.0)
    assert result["verified"] is False
    assert result["reason"] == "invalid (negative) required amount"


# ── FacilitatorRouter wiring: solana routes to the real verifier ────────────


@pytest.mark.asyncio
@respx.mock
async def test_facilitator_routes_solana_to_rpc_verifier(monkeypatch) -> None:
    respx.post(DEFAULT_SOLANA_RPC_URL).mock(
        return_value=_ok_response(
            _rpc_result(
                instructions=[
                    _parsed_transfer_checked(SOLANA_USDC_MINT, RECIPIENT, USDC_AMOUNT_ATOMIC)
                ]
            )
        )
    )
    monkeypatch.setattr(
        "pry.payments.x402.facilitator.X402_NETWORK_WALLETS", {"solana:mainnet": RECIPIENT}
    )
    router = FacilitatorRouter(self_hosted=True)
    result = await router.verify("pid-1", "sig-abc", "solana:mainnet", "USDC", 1.0)
    assert result["verified"] is True
    assert result["facilitator"] == "solana-rpc"
    assert result["network"] == "solana:mainnet"
    assert result["amount_usd"] == 2.0
    assert result.get("scaffolded") is None


@pytest.mark.asyncio
async def test_facilitator_solana_fails_closed_without_wallet(monkeypatch) -> None:
    monkeypatch.setattr("pry.payments.x402.facilitator.X402_NETWORK_WALLETS", {})
    monkeypatch.setattr("pry.payments.x402.facilitator.X402_WALLET", "pry-default-wallet")
    router = FacilitatorRouter(self_hosted=True)
    result = await router.verify("pid-1", "sig-abc", "solana:mainnet", "USDC", 1.0)
    assert result["verified"] is False
    assert "receiving wallet not configured" in result["reason"]


@pytest.mark.asyncio
@respx.mock
async def test_facilitator_solana_underpayment_reflects_onchain(monkeypatch) -> None:
    """The verify result reflects the on-chain amount, not the scaffold."""
    respx.post(DEFAULT_SOLANA_RPC_URL).mock(
        return_value=_ok_response(
            _rpc_result(
                instructions=[_parsed_transfer_checked(SOLANA_USDC_MINT, RECIPIENT, 100_000)]
            )
        )
    )
    monkeypatch.setattr(
        "pry.payments.x402.facilitator.X402_NETWORK_WALLETS", {"solana:mainnet": RECIPIENT}
    )
    router = FacilitatorRouter(self_hosted=True)
    result = await router.verify("pid-1", "sig-abc", "solana", "USDC", 1.0)
    assert result["verified"] is False
    assert "underpayment" in result["reason"]
    assert result["network"] == "solana:mainnet"


# ── Scheme status: solana is now live, tron stays scaffolded ────────────────


def test_solana_verification_status_is_live() -> None:
    assert network_verification_status("solana:mainnet") == "live"
    assert network_verification_status("solana") == "live"
    assert network_verification_status("tron:mainnet") == "scaffolded:needs_facilitator"
