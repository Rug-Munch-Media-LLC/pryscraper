# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for x402 Solana settlement verification — T1 win #6.

Verifies that Solana USDC payments are correctly verified on-chain
via the SPL RPC getTransaction jsonParsed method.
"""

from __future__ import annotations

from unittest.mock import patch

import httpx
import pytest

from pry.payments.x402.solana_verifier import (
    SOLANA_USDC_MINT,
    _iter_spl_instructions,
    _parse_amount,
    verify_solana_payment,
)


class TestParseAmount:
    """SPL transferChecked amount parsing."""

    def test_parse_amount_from_token_amount(self) -> None:
        info = {
            "tokenAmount": {"amount": "1000000", "decimals": 6},
        }
        result = _parse_amount(info)
        expected = (1000000, 6)
        assert result == expected

    def test_parse_amount_from_legacy_field(self) -> None:
        info = {"amount": "500000", "decimals": 6}
        result = _parse_amount(info)
        expected = (500000, 6)
        assert result == expected

    def test_parse_amount_malformed(self) -> None:
        info = {"amount": "not_a_number", "decimals": 6}
        result = _parse_amount(info)
        assert result is None

    def test_parse_amount_empty(self) -> None:
        result = _parse_amount({})
        assert result is None


class TestIterSplInstructions:
    """Walk parsed SPL instructions from a transaction."""

    def test_iter_finds_transfer_checked(self) -> None:
        result = {
            "transaction": {
                "message": {
                    "instructions": [
                        {
                            "program": "splToken",
                            "programId": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
                            "parsed": {
                                "type": "transferChecked",
                                "info": {
                                    "mint": SOLANA_USDC_MINT,
                                    "destination": "abc123",
                                    "tokenAmount": {"amount": "1000000", "decimals": 6},
                                },
                            },
                        },
                    ]
                }
            },
            "meta": {"innerInstructions": []},
        }
        instructions = _iter_spl_instructions(result)
        assert len(instructions) == 1
        assert instructions[0][0] == "transferChecked"

    def test_iter_skips_non_spl_instructions(self) -> None:
        result = {
            "transaction": {
                "message": {
                    "instructions": [
                        {"program": "system", "parsed": {"type": "transfer"}},
                    ]
                }
            },
            "meta": {"innerInstructions": []},
        }
        instructions = _iter_spl_instructions(result)
        assert len(instructions) == 0

    def test_iter_skips_wrong_program_id(self) -> None:
        result = {
            "transaction": {
                "message": {
                    "instructions": [
                        {
                            "program": "splToken",
                            "programId": "WrongProgramId",
                            "parsed": {"type": "transferChecked", "info": {}},
                        },
                    ]
                }
            },
            "meta": {"innerInstructions": []},
        }
        instructions = _iter_spl_instructions(result)
        assert len(instructions) == 0


class TestVerifySolanaPayment:
    """End-to-end Solana payment verification."""

    @pytest.mark.asyncio
    async def test_missing_tx_signature(self) -> None:
        result = await verify_solana_payment("", "recipient", 1.0, rpc_url="https://test.com")
        assert result["verified"] is False
        assert "missing" in result["reason"].lower()

    @pytest.mark.asyncio
    async def test_missing_recipient(self) -> None:
        result = await verify_solana_payment("tx_sig", "", 1.0, rpc_url="https://test.com")
        assert result["verified"] is False
        assert "missing" in result["reason"].lower()

    @pytest.mark.asyncio
    async def test_invalid_amount(self) -> None:
        result = await verify_solana_payment(
            "tx_sig", "recipient", -1.0, rpc_url="https://test.com"
        )
        assert result["verified"] is False
        assert "invalid" in result["reason"].lower()

    @pytest.mark.asyncio
    async def test_rpc_error_handled(self) -> None:
        """RPC errors should return verified=False, not raise."""
        with patch("httpx.AsyncClient.post", side_effect=httpx.RequestError("network error")):
            result = await verify_solana_payment(
                "tx_sig", "recipient", 1.0, rpc_url="https://test.com"
            )
        assert result["verified"] is False
        assert "rpc_error" in result["reason"]

    @pytest.mark.asyncio
    async def test_transaction_not_found(self) -> None:
        """Non-existent transaction returns verified=False."""
        request = httpx.Request("POST", "https://test.com")
        mock_response = httpx.Response(
            200,
            json={"jsonrpc": "2.0", "id": 1, "result": None},
            request=request,
        )
        with patch("httpx.AsyncClient.post", return_value=mock_response):
            result = await verify_solana_payment(
                "tx_sig", "recipient", 1.0, rpc_url="https://test.com"
            )
        assert result["verified"] is False
        assert "not_found" in result["reason"]

    @pytest.mark.asyncio
    async def test_underpayment_detected(self) -> None:
        """Payment below required amount is rejected."""
        request = httpx.Request("POST", "https://test.com")
        mock_response = httpx.Response(
            200,
            request=request,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "result": {
                    "slot": 12345,
                    "blockTime": 1700000000,
                    "meta": {"err": None, "innerInstructions": []},
                    "transaction": {
                        "message": {
                            "instructions": [
                                {
                                    "program": "splToken",
                                    "programId": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
                                    "parsed": {
                                        "type": "transferChecked",
                                        "info": {
                                            "mint": SOLANA_USDC_MINT,
                                            "destination": "recipient_wallet",
                                            "tokenAmount": {
                                                "amount": "500000",
                                                "decimals": 6,
                                            },  # $0.50
                                        },
                                    },
                                },
                            ]
                        }
                    },
                },
            },
        )
        with patch("httpx.AsyncClient.post", return_value=mock_response):
            result = await verify_solana_payment(
                "tx_sig", "recipient_wallet", 1.0, rpc_url="https://test.com"
            )
        assert result["verified"] is False
        assert "underpayment" in result["reason"]

    @pytest.mark.asyncio
    async def test_wrong_mint_rejected(self) -> None:
        """Transfer with wrong mint (not USDC) is rejected."""
        request = httpx.Request("POST", "https://test.com")
        mock_response = httpx.Response(
            200,
            request=request,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "result": {
                    "slot": 12345,
                    "blockTime": 1700000000,
                    "meta": {"err": None, "innerInstructions": []},
                    "transaction": {
                        "message": {
                            "instructions": [
                                {
                                    "program": "splToken",
                                    "programId": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
                                    "parsed": {
                                        "type": "transferChecked",
                                        "info": {
                                            "mint": "WRONG_MINT_ADDRESS",  # Not USDC
                                            "destination": "recipient_wallet",
                                            "tokenAmount": {"amount": "2000000", "decimals": 6},
                                        },
                                    },
                                },
                            ]
                        }
                    },
                },
            },
        )
        with patch("httpx.AsyncClient.post", return_value=mock_response):
            result = await verify_solana_payment(
                "tx_sig", "recipient_wallet", 1.0, rpc_url="https://test.com"
            )
        assert result["verified"] is False
        assert "wrong_mint" in result["reason"]

    @pytest.mark.asyncio
    async def test_successful_payment_verified(self) -> None:
        """Correct USDC payment to correct recipient verifies."""
        request = httpx.Request("POST", "https://test.com")
        mock_response = httpx.Response(
            200,
            request=request,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "result": {
                    "slot": 12345,
                    "blockTime": 1700000000,
                    "meta": {"err": None, "innerInstructions": []},
                    "transaction": {
                        "message": {
                            "instructions": [
                                {
                                    "program": "splToken",
                                    "programId": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
                                    "parsed": {
                                        "type": "transferChecked",
                                        "info": {
                                            "mint": SOLANA_USDC_MINT,
                                            "destination": "recipient_wallet",
                                            "tokenAmount": {
                                                "amount": "2000000",
                                                "decimals": 6,
                                            },  # $2.00 >= $1.00
                                        },
                                    },
                                },
                            ]
                        }
                    },
                },
            },
        )
        with patch("httpx.AsyncClient.post", return_value=mock_response):
            result = await verify_solana_payment(
                "tx_sig", "recipient_wallet", 1.0, rpc_url="https://test.com"
            )
        assert result["verified"] is True
        assert result["recipient"] == "recipient_wallet"
        assert result["amount_raw"] == 2000000
        assert result["mint"] == SOLANA_USDC_MINT


class TestSolanaUsdcMint:
    """Verify the USDC mint constant is correct."""

    def test_usdc_mint_is_valid_base58(self) -> None:
        """USDC mint should be a valid base58 string."""
        # Base58 characters only
        assert all(
            c in "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
            for c in SOLANA_USDC_MINT
        )
        assert len(SOLANA_USDC_MINT) == 44  # Standard Solana address length

    def test_usdc_mint_matches_circle(self) -> None:
        """Verify USDC mint matches Circle's official Solana USDC."""
        assert SOLANA_USDC_MINT == "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
