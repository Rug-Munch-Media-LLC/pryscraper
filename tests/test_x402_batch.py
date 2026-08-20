# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for x402/batch.py — batch payment registry and helpers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from x402.batch import (
    _batch_lock,
    _batch_payments,
    create_batch_payment,
    is_batch_paid,
    verify_batch_payment,
)


@pytest.fixture(autouse=True)
def clear_batch_registry():
    """Clear the in-memory batch registry before each test."""
    with _batch_lock:
        _batch_payments.clear()
    return


# ---------------------------------------------------------------------------
# create_batch_payment
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_single_op():
    result = await create_batch_payment(["scrape"])
    assert "batch_id" in result
    assert result["total_usd"] > 0
    assert len(result["operations"]) == 1
    assert "payment_required" in result


@pytest.mark.asyncio
async def test_create_multiple_ops():
    result = await create_batch_payment(["scrape", "monitor"])
    assert len(result["operations"]) >= 2
    assert result["total_usd"] > 0


@pytest.mark.asyncio
async def test_create_all_ops():
    result = await create_batch_payment(
        [
            "scrape",
            "crawl",
            "extract",
            "monitor",
            "llm_call",
            "bulk_crawl",
        ]
    )
    assert len(result["operations"]) >= 6
    assert result["total_usd"] > 0


@pytest.mark.asyncio
async def test_create_unknown_op():
    assert "error" in await create_batch_payment(["unknown_op"])


@pytest.mark.asyncio
async def test_create_all_unknown():
    assert "error" in await create_batch_payment(["op1", "op2"])


@pytest.mark.asyncio
async def test_create_empty():
    assert "error" in await create_batch_payment([])


@pytest.mark.asyncio
async def test_create_has_pricing():
    for op in (await create_batch_payment(["scrape", "monitor"]))["operations"]:
        assert op["price_usd"] > 0


@pytest.mark.asyncio
async def test_create_id_format():
    bid = (await create_batch_payment(["scrape"]))["batch_id"]
    assert bid.startswith("batch_")
    assert len(bid) > 10


# ---------------------------------------------------------------------------
# verify_batch_payment
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_verify_not_found():
    r = await verify_batch_payment("nonexistent", "0xdead")
    assert r["verified"] is False
    assert "not found" in r.get("reason", "").lower()


@pytest.mark.asyncio
async def test_verify_already_paid():
    r = await create_batch_payment(["scrape"])
    bid = r["batch_id"]
    with _batch_lock:
        _batch_payments[bid]["paid"] = True
        _batch_payments[bid]["tx_hash"] = "0xpaid"

    r2 = await verify_batch_payment(bid, "0xpaid")
    assert r2["verified"] is True
    assert "already paid" in r2.get("note", "").lower()


@pytest.mark.asyncio
async def test_verify_onchain_success():
    r = await create_batch_payment(["scrape"])
    bid = r["batch_id"]
    mock = AsyncMock()
    mock.verify.return_value = {"verified": True, "reason": ""}

    with patch("x402.batch.get_facilitator_router", return_value=mock):
        r2 = await verify_batch_payment(bid, "0xvalid")
        assert r2["verified"] is True
        assert r2["total_usd"] > 0


@pytest.mark.asyncio
async def test_verify_onchain_failure():
    r = await create_batch_payment(["scrape"])
    bid = r["batch_id"]
    mock = AsyncMock()
    mock.verify.return_value = {"verified": False, "reason": "insufficient"}

    with patch("x402.batch.get_facilitator_router", return_value=mock):
        r2 = await verify_batch_payment(bid, "0xinvalid")
        assert r2["verified"] is False


# ---------------------------------------------------------------------------
# is_batch_paid
# ---------------------------------------------------------------------------


def test_is_paid_no_such():
    assert is_batch_paid("no_such") is False


@pytest.mark.asyncio
async def test_is_paid_unpaid():
    r = await create_batch_payment(["scrape"])
    assert is_batch_paid(r["batch_id"]) is False


@pytest.mark.asyncio
async def test_is_paid_yes():
    r = await create_batch_payment(["scrape"])
    bid = r["batch_id"]
    with _batch_lock:
        _batch_payments[bid]["paid"] = True
    assert is_batch_paid(bid) is True


@pytest.mark.asyncio
async def test_is_paid_expired():
    r = await create_batch_payment(["scrape"])
    bid = r["batch_id"]
    with _batch_lock:
        _batch_payments[bid]["paid"] = True
        _batch_payments[bid]["expires_at"] = (datetime.now(UTC) - timedelta(seconds=10)).isoformat()
    assert is_batch_paid(bid) is False


@pytest.mark.asyncio
async def test_is_paid_bad_expiry():
    r = await create_batch_payment(["scrape"])
    bid = r["batch_id"]
    with _batch_lock:
        _batch_payments[bid]["paid"] = True
        _batch_payments[bid]["expires_at"] = "bad-date"
    assert is_batch_paid(bid) is False


@pytest.mark.asyncio
async def test_is_paid_no_expiry():
    r = await create_batch_payment(["scrape"])
    bid = r["batch_id"]
    with _batch_lock:
        _batch_payments[bid]["paid"] = True
        _batch_payments[bid].pop("expires_at", None)
    assert is_batch_paid(bid) is True
