# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Deep tests for X402Handler uncovered paths.

Targets the previously-uncovered branches: constructor/_load_payments
corrupt-file tolerance, _record_payment/_record_settlement IO errors,
create_payment_required multi-asset shape, verify_payment/settle_payment
router error handling, require_payment 402 shape, is_paid expiry/replay
logic, get_stats shape.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from pry.payments.x402.handler import X402Handler


class TestConstructorAndLoad:
    def test_load_payments_corrupt_file_tolerated(self, tmp_path: Path) -> None:
        """Corrupt JSON file must not crash constructor - empty list used."""
        payments_file = tmp_path / "payments.jsonl"
        payments_file.write_text("{not json at all")
        handler = X402Handler(payments_file=payments_file)
        assert handler.payments == []

    def test_load_payments_empty_file(self, tmp_path: Path) -> None:
        payments_file = tmp_path / "payments.jsonl"
        payments_file.write_text("")
        handler = X402Handler(payments_file=payments_file)
        assert handler.payments == []

    def test_load_payments_valid_entries(self, tmp_path: Path) -> None:
        payments_file = tmp_path / "payments.jsonl"
        payments_file.write_text(
            '{"payment_id": "p1", "verified": true}\n{"payment_id": "p2", "verified": false}\n'
        )
        handler = X402Handler(payments_file=payments_file)
        assert len(handler.payments) == 2
        assert handler.payments[0]["payment_id"] == "p1"

    def test_constructor_defaults(self, tmp_path: Path) -> None:
        handler = X402Handler(payments_file=tmp_path / "p.jsonl")
        assert handler.wallet == "pry-default-wallet"
        assert handler.facilitator_url == "https://x402.facilitator.pryscraper.com"
        assert handler.router is not None


class TestRecordPayment:
    def test_record_payment_appends_and_persists(self, tmp_path: Path) -> None:
        payments_file = tmp_path / "payments.jsonl"
        handler = X402Handler(payments_file=payments_file)
        record = {"payment_id": "p1", "verified": True}
        handler._record_payment(record)
        assert len(handler.payments) == 1
        # File persisted
        content = payments_file.read_text().strip()
        assert '"payment_id": "p1"' in content

    def test_record_payment_io_error_logged_not_raised(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Write failure must be logged, not crash."""
        payments_file = tmp_path / "payments.jsonl"
        handler = X402Handler(payments_file=payments_file)
        # Make file a directory -> write fails
        payments_file.mkdir()
        with caplog.at_level("WARNING"):
            handler._record_payment({"payment_id": "p1"})
        assert any("x402_payment_record_failed" in r.message for r in caplog.records)


class TestRecordSettlement:
    def test_record_settlement_appends_and_persists(self, tmp_path: Path) -> None:
        settlements_file = tmp_path / "settlements.jsonl"
        handler = X402Handler(settlements_file=settlements_file)
        settlement = {"payment_id": "p1", "tx_hash": "0xabc"}
        handler._record_settlement(settlement)
        content = settlements_file.read_text().strip()
        assert '"payment_id": "p1"' in content

    def test_record_settlement_io_error_logged_not_raised(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        settlements_file = tmp_path / "settlements.jsonl"
        handler = X402Handler(settlements_file=settlements_file)
        settlements_file.mkdir()
        with caplog.at_level("WARNING"):
            handler._record_settlement({"payment_id": "p1"})
        assert any("x402_settlement_record_failed" in r.message for r in caplog.records)


class TestCreatePaymentRequired:
    def test_legacy_single_asset_shape(self, tmp_path: Path) -> None:
        handler = X402Handler(payments_file=tmp_path / "p.jsonl")
        body, headers = handler.create_payment_required("scrape")
        assert body["x402Version"] == 1
        assert body["accepts"][0]["asset"] == "USDC"
        assert body["accepts"][0]["network"] == "base"
        assert "PAYMENT-REQUIRED" in headers
        assert headers["X-Payment-Required"] == "true"

    def test_multi_asset_shape_includes_supported_assets(self, tmp_path: Path) -> None:
        handler = X402Handler(payments_file=tmp_path / "p.jsonl")
        body, headers = handler.create_payment_required("scrape", multi_asset=True)
        assert body["x402Version"] == 1
        assert "supported_assets" in body
        assert "supported_networks" in body
        assert len(body["accepts"]) >= 2  # multiple assets
        # Each accept has network + asset
        for acc in body["accepts"]:
            assert "asset" in acc
            assert "network" in acc

    def test_preferred_networks_assets_filter(self, tmp_path: Path) -> None:
        handler = X402Handler(payments_file=tmp_path / "p.jsonl")
        body, _ = handler.create_payment_required(
            "scrape",
            multi_asset=True,
            preferred_networks=["base"],
            preferred_assets=["USDC"],
        )
        for acc in body["accepts"]:
            assert acc["network"] == "base"
            assert acc["asset"] == "USDC"


class TestVerifyPayment:
    @pytest.mark.asyncio
    async def test_verify_payment_router_error_returns_false(self, tmp_path: Path) -> None:
        """Router exception must be caught and returned as verified=False."""
        handler = X402Handler(payments_file=tmp_path / "p.jsonl")
        handler.router = MagicMock()
        handler.router.verify = AsyncMock(side_effect=RuntimeError("facilitator down"))
        result = await handler.verify_payment("pid", "tx123")
        assert result["verified"] is False
        assert "facilitator down" in result["reason"]

    @pytest.mark.asyncio
    async def test_verify_payment_uses_operation_price(self, tmp_path: Path) -> None:
        """When operation provided, server-side price overrides amount_usd."""
        handler = X402Handler(payments_file=tmp_path / "p.jsonl")
        handler.router = MagicMock()
        handler.router.verify = AsyncMock(return_value={"verified": True, "reason": ""})
        await handler.verify_payment("pid", "tx", operation="scrape", amount_usd=999.0)
        # Router called with resolved price, not 999
        call_args = handler.router.verify.call_args
        assert call_args.kwargs["amount_usd"] < 10.0  # scrape price is small

    @pytest.mark.asyncio
    async def test_verify_payment_records_payment(self, tmp_path: Path) -> None:
        handler = X402Handler(payments_file=tmp_path / "p.jsonl")
        handler.router = MagicMock()
        handler.router.verify = AsyncMock(
            return_value={"verified": True, "reason": "", "facilitator": "test"}
        )
        await handler.verify_payment("pid", "tx", caller_key="caller1")
        assert len(handler.payments) == 1
        p = handler.payments[0]
        assert p["payment_id"] == "pid"
        assert p["verified"] is True
        assert p["caller_key"] == "caller1"
        assert "expires_at" in p
        assert "verified_at" in p


class TestSettlePayment:
    @pytest.mark.asyncio
    async def test_settle_payment_router_error_propagates(self, tmp_path: Path) -> None:
        """Router settle exception propagates (not caught like verify)."""
        handler = X402Handler(payments_file=tmp_path / "p.jsonl")
        handler.router = MagicMock()
        handler.router.settle = AsyncMock(side_effect=RuntimeError("settlement failed"))
        with pytest.raises(RuntimeError, match="settlement failed"):
            await handler.settle_payment("pid", "tx")

    @pytest.mark.asyncio
    async def test_settle_payment_records_settlement(self, tmp_path: Path) -> None:
        handler = X402Handler(settlements_file=tmp_path / "s.jsonl")
        handler.router = MagicMock()
        handler.router.settle = AsyncMock(return_value={"tx_hash": "0xabc", "status": "settled"})
        result = await handler.settle_payment("pid", "tx")
        assert result["tx_hash"] == "0xabc"
        # Settlement recorded
        content = handler.settlements_file.read_text().strip()
        assert '"payment_id": "pid"' in content


class TestRequirePayment:
    def test_require_payment_returns_402_shape(self, tmp_path: Path) -> None:
        handler = X402Handler(payments_file=tmp_path / "p.jsonl")
        resp = handler.require_payment("scrape")
        assert resp["status_code"] == 402
        assert "headers" in resp
        assert "body" in resp
        assert resp["headers"]["X-Payment-Required"] == "true"
        assert "PAYMENT-REQUIRED" in resp["headers"]


class TestIsPaid:
    @pytest.mark.asyncio
    async def test_is_paid_true_when_verified_unexpired_caller_matches(
        self, tmp_path: Path
    ) -> None:
        handler = X402Handler(payments_file=tmp_path / "p.jsonl")
        future = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
        handler.payments = [
            {
                "payment_id": "pid",
                "verified": True,
                "expires_at": future,
                "caller_key": "caller1",
            }
        ]
        assert handler.is_paid("pid", "caller1") is True

    @pytest.mark.asyncio
    async def test_is_paid_false_when_expired(self, tmp_path: Path) -> None:
        handler = X402Handler(payments_file=tmp_path / "p.jsonl")
        past = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
        handler.payments = [{"payment_id": "pid", "verified": True, "expires_at": past}]
        assert handler.is_paid("pid") is False

    @pytest.mark.asyncio
    async def test_is_paid_false_when_no_expiry(self, tmp_path: Path) -> None:
        handler = X402Handler(payments_file=tmp_path / "p.jsonl")
        handler.payments = [{"payment_id": "pid", "verified": True}]
        assert handler.is_paid("pid") is False

    @pytest.mark.asyncio
    async def test_is_paid_false_when_malformed_expiry(self, tmp_path: Path) -> None:
        handler = X402Handler(payments_file=tmp_path / "p.jsonl")
        handler.payments = [{"payment_id": "pid", "verified": True, "expires_at": "not-a-date"}]
        assert handler.is_paid("pid") is False

    @pytest.mark.asyncio
    async def test_is_paid_false_when_caller_mismatch(self, tmp_path: Path) -> None:
        handler = X402Handler(payments_file=tmp_path / "p.jsonl")
        future = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
        handler.payments = [
            {
                "payment_id": "pid",
                "verified": True,
                "expires_at": future,
                "caller_key": "caller1",
            }
        ]
        assert handler.is_paid("pid", "caller2") is False

    @pytest.mark.asyncio
    async def test_is_paid_false_when_not_verified(self, tmp_path: Path) -> None:
        handler = X402Handler(payments_file=tmp_path / "p.jsonl")
        future = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
        handler.payments = [{"payment_id": "pid", "verified": False, "expires_at": future}]
        assert handler.is_paid("pid") is False


class TestGetStats:
    def test_get_stats_shape(self, tmp_path: Path) -> None:
        handler = X402Handler(payments_file=tmp_path / "p.jsonl")
        stats = handler.get_stats()
        assert "total_payments" in stats
        assert "wallet" in stats
        assert "facilitator" in stats
        assert stats["wallet"] == "pry-default-wallet"
        assert stats["facilitator"] == "https://x402.facilitator.pryscraper.com"
