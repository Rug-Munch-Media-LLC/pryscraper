# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for TRON TRC-20 USDT payment verifier — T1 win #1.

Verifies that TRON TRC-20 USDT payments are correctly verified on-chain
via the TRON Grid ``/walletsolidity/gettransactioninfobyid`` endpoint.
"""

from __future__ import annotations

from unittest.mock import patch

import httpx
import pytest

from pry.payments.x402.tron_verifier import (
    TRANSFER_EVENT_TOPIC0,
    TRON_USDT_CONTRACT,
    TRON_USDT_CONTRACT_HEX,
    _iter_trc20_transfers,
    _tron_hex_to_base58,
    verify_tron_trc20_payment,
)


class TestTronAddressNormalization:
    """TRON address hex normalization."""

    def test_hex_with_prefix(self) -> None:
        result = _tron_hex_to_base58("41abcdef1234567890abcdef1234567890abcdef12")
        assert result == "abcdef1234567890abcdef1234567890abcdef12"

    def test_hex_without_prefix(self) -> None:
        result = _tron_hex_to_base58("abcdef1234567890abcdef1234567890abcdef12")
        assert result == "abcdef1234567890abcdef1234567890abcdef12"

    def test_lowercase_output(self) -> None:
        result = _tron_hex_to_base58("41ABCDEF1234567890ABCDEF1234567890ABCDEF12")
        assert result == result.lower()


class TestIterTrc20Transfers:
    """Decode TRC-20 Transfer events from contract result."""

    def test_iter_finds_transfer_event(self) -> None:
        result = {
            "log": [
                {
                    "address": TRON_USDT_CONTRACT_HEX,
                    "topics": [
                        TRANSFER_EVENT_TOPIC0,
                        "0x000000000000000000000000" + "a" * 40,
                        "0x000000000000000000000000" + "b" * 40,
                    ],
                    "data": "0x00000000000000000000000000000000000000000000000000000000000f4240",
                },
            ],
        }
        events = _iter_trc20_transfers(result)
        assert len(events) == 1
        assert events[0]["to"] == "41" + "b" * 40
        assert events[0]["value"] == 1_000_000  # 1 USDT

    def test_iter_rejects_non_usdt_contract(self) -> None:
        """Scam-token Transfer events (wrong emitting contract) are dropped."""
        scam_contract = "41" + "d" * 40
        result = {
            "log": [
                {
                    "address": scam_contract,
                    "topics": [
                        TRANSFER_EVENT_TOPIC0,
                        "0x000000000000000000000000" + "a" * 40,
                        "0x000000000000000000000000" + "b" * 40,
                    ],
                    "data": "0x00000000000000000000000000000000000000000000000000000000000f4240",
                },
            ],
        }
        events = _iter_trc20_transfers(result)
        assert len(events) == 0

    def test_iter_fails_closed_on_missing_address(self) -> None:
        """Logs without an emitting contract address are dropped (fail closed)."""
        result = {
            "log": [
                {
                    "topics": [
                        TRANSFER_EVENT_TOPIC0,
                        "0x000000000000000000000000" + "a" * 40,
                        "0x000000000000000000000000" + "b" * 40,
                    ],
                    "data": "0x00000000000000000000000000000000000000000000000000000000000f4240",
                },
            ],
        }
        events = _iter_trc20_transfers(result)
        assert len(events) == 0

    def test_iter_contract_match_is_case_insensitive(self) -> None:
        """Uppercase hex emitting address still matches the USDT contract."""
        result = {
            "log": [
                {
                    "address": TRON_USDT_CONTRACT_HEX.upper(),
                    "topics": [
                        TRANSFER_EVENT_TOPIC0,
                        "0x000000000000000000000000" + "a" * 40,
                        "0x000000000000000000000000" + "b" * 40,
                    ],
                    "data": "0x00000000000000000000000000000000000000000000000000000000000f4240",
                },
            ],
        }
        events = _iter_trc20_transfers(result)
        assert len(events) == 1

    def test_iter_skips_non_transfer_events(self) -> None:
        result = {
            "log": [
                {
                    "topics": [
                        "0x0000000000000000000000000000000000000000000000000000000000000000",
                        "0x" + "a" * 64,
                    ],
                    "data": "0x0",
                },
            ],
        }
        events = _iter_trc20_transfers(result)
        assert len(events) == 0

    def test_iter_skips_malformed_logs(self) -> None:
        result = {"log": [{"topics": ["short"], "data": "0x0"}]}
        events = _iter_trc20_transfers(result)
        assert len(events) == 0

    def test_iter_handles_empty_logs(self) -> None:
        events = _iter_trc20_transfers({"log": []})
        assert len(events) == 0

    def test_iter_handles_missing_logs(self) -> None:
        events = _iter_trc20_transfers({})
        assert len(events) == 0


class TestVerifyTronTrc20Payment:
    """End-to-end TRON TRC-20 payment verification."""

    @pytest.mark.asyncio
    async def test_missing_tx_hash(self) -> None:
        result = await verify_tron_trc20_payment("", "recipient", 1.0, rpc_url="https://test.com")
        assert result["verified"] is False
        assert "missing" in result["reason"].lower()

    @pytest.mark.asyncio
    async def test_missing_recipient(self) -> None:
        result = await verify_tron_trc20_payment("tx_hash", "", 1.0, rpc_url="https://test.com")
        assert result["verified"] is False
        assert "missing" in result["reason"].lower()

    @pytest.mark.asyncio
    async def test_invalid_amount(self) -> None:
        result = await verify_tron_trc20_payment(
            "tx_hash", "recipient", -1.0, rpc_url="https://test.com"
        )
        assert result["verified"] is False
        assert "invalid" in result["reason"].lower()

    @pytest.mark.asyncio
    async def test_rpc_error_handled(self) -> None:
        """RPC errors should return verified=False, not raise."""
        with patch("httpx.AsyncClient.post", side_effect=httpx.RequestError("network error")):
            result = await verify_tron_trc20_payment(
                "tx_hash", "recipient", 1.0, rpc_url="https://test.com"
            )
        assert result["verified"] is False
        assert "rpc_error" in result["reason"]

    @pytest.mark.asyncio
    async def test_transaction_not_found(self) -> None:
        """Empty response returns verified=False."""
        request = httpx.Request("POST", "https://test.com")
        mock_response = httpx.Response(200, json={}, request=request)
        with patch("httpx.AsyncClient.post", return_value=mock_response):
            result = await verify_tron_trc20_payment(
                "tx_hash", "recipient", 1.0, rpc_url="https://test.com"
            )
        assert result["verified"] is False
        assert "not_found" in result["reason"]

    @pytest.mark.asyncio
    async def test_underpayment_detected(self) -> None:
        """Payment below required amount is rejected."""
        request = httpx.Request("POST", "https://test.com")
        mock_response = httpx.Response(
            200,
            json={
                "blockNumber": 12345,
                "blockTimeStamp": 1700000000000,
                "log": [
                    {
                        "address": TRON_USDT_CONTRACT_HEX,
                        "topics": [
                            TRANSFER_EVENT_TOPIC0,
                            "0x000000000000000000000000" + "a" * 40,
                            "0x000000000000000000000000" + "b" * 40,
                        ],
                        "data": "0x000000000000000000000000000000000000000000000000000000000007a120",
                    },
                ],
            },
            request=request,
        )
        with patch("httpx.AsyncClient.post", return_value=mock_response):
            result = await verify_tron_trc20_payment(
                "tx_hash", "41" + "b" * 40, 1.0, rpc_url="https://test.com"
            )
        assert result["verified"] is False
        assert "underpayment" in result["reason"]

    @pytest.mark.asyncio
    async def test_wrong_recipient_rejected(self) -> None:
        """Transfer to wrong recipient is rejected."""
        request = httpx.Request("POST", "https://test.com")
        mock_response = httpx.Response(
            200,
            json={
                "blockNumber": 12345,
                "blockTimeStamp": 1700000000000,
                "log": [
                    {
                        "address": TRON_USDT_CONTRACT_HEX,
                        "topics": [
                            TRANSFER_EVENT_TOPIC0,
                            "0x000000000000000000000000" + "a" * 40,
                            "0x000000000000000000000000" + "c" * 40,  # Wrong recipient
                        ],
                        "data": "0x00000000000000000000000000000000000000000000000000000000001e8480",
                    },
                ],
            },
            request=request,
        )
        with patch("httpx.AsyncClient.post", return_value=mock_response):
            result = await verify_tron_trc20_payment(
                "tx_hash", "41" + "b" * 40, 1.0, rpc_url="https://test.com"
            )
        assert result["verified"] is False
        assert "wrong_recipient" in result["reason"]

    @pytest.mark.asyncio
    async def test_successful_payment_verified(self) -> None:
        """Correct USDT payment to correct recipient verifies."""
        request = httpx.Request("POST", "https://test.com")
        mock_response = httpx.Response(
            200,
            json={
                "blockNumber": 12345,
                "blockTimeStamp": 1700000000000,
                "log": [
                    {
                        "address": TRON_USDT_CONTRACT_HEX,
                        "topics": [
                            TRANSFER_EVENT_TOPIC0,
                            "0x000000000000000000000000" + "a" * 40,
                            "0x000000000000000000000000" + "b" * 40,
                        ],
                        "data": "0x00000000000000000000000000000000000000000000000000000000001e8480",
                    },
                ],
            },
            request=request,
        )
        with patch("httpx.AsyncClient.post", return_value=mock_response):
            result = await verify_tron_trc20_payment(
                "tx_hash", "41" + "b" * 40, 1.0, rpc_url="https://test.com"
            )
        assert result["verified"] is True
        assert result["recipient"] == "41" + "b" * 40
        assert result["amount_raw"] == 2_000_000  # 2 USDT
        assert result["contract"] == TRON_USDT_CONTRACT

    @pytest.mark.asyncio
    async def test_scam_token_transfer_rejected(self) -> None:
        """A non-USDT TRC-20 token transfer to the treasury must NOT verify."""
        request = httpx.Request("POST", "https://test.com")
        mock_response = httpx.Response(
            200,
            json={
                "blockNumber": 12345,
                "blockTimeStamp": 1700000000000,
                "log": [
                    {
                        "address": "41" + "d" * 40,  # scam token contract
                        "topics": [
                            TRANSFER_EVENT_TOPIC0,
                            "0x000000000000000000000000" + "a" * 40,
                            "0x000000000000000000000000" + "b" * 40,
                        ],
                        "data": "0x000000000000000000000000000000000000000000000000000000000001e8480",
                    },
                ],
            },
            request=request,
        )
        with patch("httpx.AsyncClient.post", return_value=mock_response):
            result = await verify_tron_trc20_payment(
                "tx_hash", "41" + "b" * 40, 1.0, rpc_url="https://test.com"
            )
        assert result["verified"] is False
        assert "wrong_contract" in result["reason"]

    @pytest.mark.asyncio
    async def test_missing_log_address_fails_closed(self) -> None:
        """A Transfer log with no emitting address must NOT verify."""
        request = httpx.Request("POST", "https://test.com")
        mock_response = httpx.Response(
            200,
            json={
                "blockNumber": 12345,
                "blockTimeStamp": 1700000000000,
                "log": [
                    {
                        "topics": [
                            TRANSFER_EVENT_TOPIC0,
                            "0x000000000000000000000000" + "a" * 40,
                            "0x000000000000000000000000" + "b" * 40,
                        ],
                        "data": "0x00000000000000000000000000000000000000000000000000000000001e8480",
                    },
                ],
            },
            request=request,
        )
        with patch("httpx.AsyncClient.post", return_value=mock_response):
            result = await verify_tron_trc20_payment(
                "tx_hash", "41" + "b" * 40, 1.0, rpc_url="https://test.com"
            )
        assert result["verified"] is False
        assert result["reason"] != ""


class TestTronUsdtContract:
    """Verify the USDT contract constant."""

    def test_usdt_contract_is_valid_base58(self) -> None:
        """USDT contract should be a valid base58 string."""
        assert all(
            c in "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
            for c in TRON_USDT_CONTRACT
        )
        assert len(TRON_USDT_CONTRACT) == 34  # Standard TRON address length

    def test_usdt_contract_matches_official(self) -> None:
        """Verify USDT contract matches Tether's official TRON USDT."""
        assert TRON_USDT_CONTRACT == "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"

    def test_transfer_event_topic0(self) -> None:
        """Transfer event topic0 should match ERC-20/TRC-20 standard."""
        assert (
            TRANSFER_EVENT_TOPIC0
            == "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
        )

    def test_usdt_contract_hex_derivation(self) -> None:
        """Hex form must be the 41-prefixed decode of the base58 contract."""
        assert TRON_USDT_CONTRACT_HEX == "41a614f803b6fd780986a42c78ec9c7f77e6ded13c"
        assert len(TRON_USDT_CONTRACT_HEX) == 42
