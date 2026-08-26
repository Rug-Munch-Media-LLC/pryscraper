# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Deep behavioural tests for the Solana x402 payment verifier.

Covers the paths the trivial-helper tests skip: RPC error matrix,
instruction walking (top-level + inner), mint/recipient/amount matching
semantics, multi-transfer best-candidate selection, and underpayment
detection. All RPC traffic is mocked - no network.

These are payment-critical paths (AI Test Oracle Policy): assertions pin
exact reason strings and amounts, not just truthiness.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import httpx
import pytest

from pry.payments.x402.solana_verifier import (
    SOLANA_USDC_MINT,
    SPL_TOKEN_PROGRAM_ID,
    _confirmed_at,
    _iter_spl_instructions,
    _parse_amount,
    verify_solana_payment,
)

RECIPIENT = "9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM"
OTHER_RECIPIENT = "4Nd1mBQtrMJVYVfKf2PJy9NZUZdTAsp7D4xWLs4gDB4T"
MINT = SOLANA_USDC_MINT


def _transfer_checked(
    *,
    amount: str = "1000000",
    decimals: int = 6,
    mint: str = MINT,
    destination: str = RECIPIENT,
    program_id: str | None = SPL_TOKEN_PROGRAM_ID,
) -> dict[str, Any]:
    inst: dict[str, Any] = {
        "program": "splToken",
        "parsed": {
            "type": "transferChecked",
            "info": {
                "mint": mint,
                "destination": destination,
                "tokenAmount": {"amount": amount, "decimals": decimals},
            },
        },
    }
    if program_id is not None:
        inst["programId"] = program_id
    return inst


def _rpc_result(instructions: list[dict[str, Any]], *, slot: int = 12345, err: Any = None) -> dict:
    return {
        "transaction": {"message": {"instructions": instructions}},
        "meta": {"err": err, "innerInstructions": []},
        "slot": slot,
        "blockTime": 1756166400,
    }


def _rpc_response(result: Any) -> dict:
    return {"jsonrpc": "2.0", "id": 1, "result": result}


async def _verify_with_payload(payload: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    """Run verify_solana_payment against a canned RPC JSON body."""
    request = httpx.Request("POST", "https://rpc.test")
    response = httpx.Response(200, json=payload, request=request)

    async def fake_post(self: Any, url: str, **kw: Any) -> httpx.Response:
        return response

    with patch.object(httpx.AsyncClient, "post", new=fake_post):
        return await verify_solana_payment("sig123", RECIPIENT, 1.0, **kwargs)


# ── helpers ──────────────────────────────────────────────────────────────────


class TestParseAmount:
    def test_token_amount_path(self) -> None:
        info = {"tokenAmount": {"amount": "1500000", "decimals": 6}}
        assert _parse_amount(info) == (1_500_000, 6)

    def test_token_amount_bad_int_falls_to_zero(self) -> None:
        info = {"tokenAmount": {"amount": "abc", "decimals": 6}}
        assert _parse_amount(info) == (0, 6)

    def test_legacy_amount_path(self) -> None:
        info = {"amount": "250000", "decimals": 6}
        assert _parse_amount(info) == (250_000, 6)

    def test_legacy_bad_int_is_none(self) -> None:
        assert _parse_amount({"amount": "x.y"}) is None

    def test_missing_both_is_none(self) -> None:
        assert _parse_amount({}) is None

    def test_decimals_default_six(self) -> None:
        assert _parse_amount({"tokenAmount": {"amount": "1"}}) == (1, 6)


class TestIterSplInstructions:
    def test_top_level_found(self) -> None:
        result = _rpc_result([_transfer_checked()])
        found = _iter_spl_instructions(result)
        assert len(found) == 1
        assert found[0][0] == "transferChecked"

    def test_inner_instructions_found(self) -> dict:
        result = {
            "transaction": {"message": {"instructions": []}},
            "meta": {
                "innerInstructions": [
                    {"instructions": [_transfer_checked(amount="500")]},
                ]
            },
        }
        found = _iter_spl_instructions(result)
        assert len(found) == 1
        assert found[0][1]["tokenAmount"]["amount"] == "500"
        return {}

    def test_non_spl_token_program_skipped(self) -> None:
        inst = _transfer_checked()
        inst["program"] = "system"
        assert _iter_spl_instructions(_rpc_result([inst])) == []

    def test_wrong_program_id_skipped(self) -> None:
        inst = _transfer_checked(program_id="SpoofedProgramId11111111111111111111111111")
        assert _iter_spl_instructions(_rpc_result([inst])) == []

    def test_non_transfer_type_skipped(self) -> None:
        inst = {
            "program": "splToken",
            "programId": SPL_TOKEN_PROGRAM_ID,
            "parsed": {"type": "mintTo", "info": {}},
        }
        assert _iter_spl_instructions(_rpc_result([inst])) == []

    def test_malformed_entries_skipped_not_crash(self) -> None:
        result = _rpc_result(["nope", 42, {"program": "splToken"}, _transfer_checked()])
        found = _iter_spl_instructions(result)
        assert len(found) == 1


class TestConfirmedAt:
    def test_valid_block_time_iso_utc(self) -> None:
        out = _confirmed_at({"blockTime": 0})
        assert out == "1970-01-01T00:00:00+00:00"

    def test_missing_block_time_empty(self) -> None:
        assert _confirmed_at({}) == ""

    def test_garbage_block_time_empty(self) -> None:
        assert _confirmed_at({"blockTime": "not-a-number"}) == ""


# ── verify_solana_payment: argument guards ───────────────────────────────────


class TestArgumentGuards:
    @pytest.mark.asyncio
    async def test_missing_signature(self) -> None:
        out = await verify_solana_payment("", RECIPIENT, 1.0)
        assert out["verified"] is False
        assert out["reason"] == "missing tx signature"

    @pytest.mark.asyncio
    async def test_missing_recipient(self) -> None:
        out = await verify_solana_payment("sig", "", 1.0)
        assert out["reason"] == "missing expected recipient"

    @pytest.mark.asyncio
    async def test_negative_amount(self) -> None:
        out = await verify_solana_payment("sig", RECIPIENT, -1.0)
        assert out["reason"] == "invalid (negative) required amount"


# ── verify_solana_payment: RPC failure matrix ────────────────────────────────


class TestRpcFailures:
    @pytest.mark.asyncio
    async def test_http_status_error(self) -> None:
        request = httpx.Request("POST", "https://rpc.test")
        response = httpx.Response(503, request=request)

        async def fake_post(self: Any, url: str, **kw: Any) -> httpx.Response:
            raise httpx.HTTPStatusError("boom", request=request, response=response)

        with patch.object(httpx.AsyncClient, "post", new=fake_post):
            out = await verify_solana_payment("sig", RECIPIENT, 1.0)
        assert out["verified"] is False
        assert out["reason"] == "rpc_http_error: 503"

    @pytest.mark.asyncio
    async def test_network_error(self) -> None:
        async def fake_post(self: Any, url: str, **kw: Any) -> httpx.Response:
            raise httpx.ConnectError("refused")

        with patch.object(httpx.AsyncClient, "post", new=fake_post):
            out = await verify_solana_payment("sig", RECIPIENT, 1.0)
        assert out["verified"] is False
        assert out["reason"].startswith("rpc_error:")

    @pytest.mark.asyncio
    async def test_rpc_error_object(self) -> None:
        out = await _verify_with_payload(
            {
                "jsonrpc": "2.0",
                "error": {"code": -32007, "message": "Transaction signature not found."},
            }
        )
        assert out["reason"] == "rpc_error_response: -32007 Transaction signature not found."

    @pytest.mark.asyncio
    async def test_transaction_not_found(self) -> None:
        out = await _verify_with_payload(_rpc_response(None))
        assert out["reason"] == "transaction_not_found"


# ── verify_solana_payment: transaction semantics ─────────────────────────────


class TestVerificationSemantics:
    @pytest.mark.asyncio
    async def test_successful_verification_exact_amount(self) -> None:
        out = await _verify_with_payload(
            _rpc_response(_rpc_result([_transfer_checked(amount="1000000")]))
        )
        assert out["verified"] is True
        assert out["recipient"] == RECIPIENT
        assert out["amount_raw"] == 1_000_000
        assert out["amount_usd"] == pytest.approx(1.0)
        assert out["mint"] == MINT
        assert out["slot"] == 12345
        assert out["confirmed_at"].startswith("20")

    @pytest.mark.asyncio
    async def test_overpayment_verifies(self) -> None:
        out = await _verify_with_payload(
            _rpc_response(_rpc_result([_transfer_checked(amount="2500000")]))
        )
        assert out["verified"] is True
        assert out["amount_usd"] == pytest.approx(2.5)

    @pytest.mark.asyncio
    async def test_failed_transaction_rejected(self) -> None:
        out = await _verify_with_payload(
            _rpc_response(_rpc_result([_transfer_checked()], err={"InstructionError": [0]}))
        )
        assert out["verified"] is False
        assert out["reason"].startswith("transaction_failed:")

    @pytest.mark.asyncio
    async def test_unconfirmed_no_slot_rejected(self) -> None:
        result = _rpc_result([_transfer_checked()])
        result["slot"] = None
        out = await _verify_with_payload(_rpc_response(result))
        assert out["reason"] == "transaction_not_confirmed"

    @pytest.mark.asyncio
    async def test_wrong_recipient_named_in_reason(self) -> None:
        out = await _verify_with_payload(
            _rpc_response(_rpc_result([_transfer_checked(destination=OTHER_RECIPIENT)]))
        )
        assert out["verified"] is False
        assert out["reason"].startswith("wrong_recipient:")
        assert OTHER_RECIPIENT in out["reason"]

    @pytest.mark.asyncio
    async def test_wrong_mint_flagged(self) -> None:
        fake_usdc = "FakeUsdcMint11111111111111111111111111111111"
        out = await _verify_with_payload(
            _rpc_response(_rpc_result([_transfer_checked(mint=fake_usdc)]))
        )
        assert out["verified"] is False
        assert out["reason"].startswith("wrong_mint:")

    @pytest.mark.asyncio
    async def test_underpayment_rejected_with_amounts(self) -> None:
        out = await _verify_with_payload(
            _rpc_response(_rpc_result([_transfer_checked(amount="500000")]))
        )
        assert out["verified"] is False
        assert out["reason"].startswith("underpayment:")
        assert "0.500000" in out["reason"]
        assert out["amount_raw"] == 500_000

    @pytest.mark.asyncio
    async def test_multiple_transfers_picks_largest_match(self) -> None:
        instructions = [
            _transfer_checked(amount="300000"),  # small to recipient
            _transfer_checked(destination=OTHER_RECIPIENT, amount="9000000"),  # unrelated
            _transfer_checked(amount="2000000"),  # big to recipient
        ]
        out = await _verify_with_payload(_rpc_response(_rpc_result(instructions)))
        assert out["verified"] is True
        assert out["amount_raw"] == 2_000_000

    @pytest.mark.asyncio
    async def test_usdc_price_scaling(self) -> None:
        """Required USD converts via usdc_price_usd when pricing deviates."""
        out = await _verify_with_payload(
            _rpc_response(_rpc_result([_transfer_checked(amount="1000000")])),
            usdc_price_usd=2.0,
        )
        # paid 1 USDC; required 1.0/2.0 = 0.5 USDC -> verified
        assert out["verified"] is True

    @pytest.mark.asyncio
    async def test_never_raises_on_total_garbage(self) -> None:
        out = await _verify_with_payload({"weird": ["shape"]})
        assert out["verified"] is False
        assert isinstance(out["reason"], str)
