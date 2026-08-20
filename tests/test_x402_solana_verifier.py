"""Tests for x402/solana_verifier.py — Solana on-chain verification."""

from __future__ import annotations

import pytest

from x402.solana_verifier import (
    _amount_usd_value,
    _failure,
    _iter_spl_instructions,
    _parse_amount,
    _success,
    verify_solana_payment,
)


def test_parse_amount_valid():
    result = _parse_amount({"amount": "1000000", "decimals": 6})
    assert result is not None
    assert result[0] == 1000000


def test_parse_amount_missing():
    assert _parse_amount({}) is None


def test_iter_spl_instructions_empty():
    assert list(_iter_spl_instructions({})) == []


def test_amount_usd_value():
    assert _amount_usd_value(1000000, 6, 1.0) == 1.0


def test_failure():
    r = _failure("test error")
    assert r["verified"] is False


def test_success():
    r = _success(
        recipient="0xsig",
        amount_raw=1000000,
        amount_decimals=6,
        amount_usd=1.0,
        mint="EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
        confirmed_at="2026-01-01T00:00:00Z",
        slot=123456,
    )
    assert r["verified"] is True


@pytest.mark.asyncio
async def test_verify_empty_tx():
    r = await verify_solana_payment("", "0xrecipient", 1.0)
    assert r["verified"] is False


@pytest.mark.asyncio
async def test_verify_empty_recipient():
    r = await verify_solana_payment("0xtx", "", 1.0)
    assert r["verified"] is False


@pytest.mark.asyncio
async def test_verify_valid_tx_no_crash():
    r = await verify_solana_payment("4a3b2c1d...", "0xrecipient", 5.0)
    assert isinstance(r, dict)
    assert "verified" in r
