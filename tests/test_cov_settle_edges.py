"""Branch coverage for settle helpers, hooks and idempotency sources."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

from typing import TYPE_CHECKING

from pry.payments.x402 import handler_settle as hs
from tests.test_cov_x402_support import Exc, Router, SettleHost, ok_receipt

if TYPE_CHECKING:
    import pytest


async def test_none_receipt_skips_extension_header() -> None:
    host = SettleHost(Router([None]))

    out = await host.settle_payment("pay_1", "0x2", network="base")

    # A mute facilitator fails CLOSED: the caller sees an explicit failure.
    assert out == {"success": False, "reason": "empty settlement response"}
    assert host.records[0]["payment_id"] == "pay_1"
    assert host._settled_txs == {}


def test_retry_after_parses_header_and_clamps() -> None:
    assert hs._retry_after_seconds(Exc("7"), 0) == 7.0
    assert hs._retry_after_seconds(Exc("999"), 0) == 30.0
    assert hs._retry_after_seconds(Exc("-9"), 0) == 0.5
    assert hs._retry_after_seconds(Exc("abc"), 2) == 2.0
    assert hs._retry_after_seconds(Exc(), 1) == 1.0


def test_resolve_amount_prefers_server_price_for_operation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(hs, "resolve_price_usd", lambda *a, **k: 0.42)
    assert hs._resolve_amount("pay_1", "base", "USDC", 99.0, "scrape") == 0.42
    assert hs._resolve_amount("unknown-pay", "base", "USDC", 0.0, "") == 0.001


def test_enrich_record_keeps_existing_identity() -> None:
    out = hs._enrich_record({"success": True, "tx_hash": "orig"}, "pay_1", "0xnew", "base", "USDC")
    assert out["tx_hash"] == "orig"
    assert out["payment_id"] == "pay_1"
    assert out["network"] == "base"
    assert out["asset"] == "USDC"


def test_db_idempotency_requires_db_and_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "pry.payments.x402.ledger_store.settlement_by_key",
        lambda key: {"success": True, "cached": key},
    )
    host = SettleHost(Router([]), use_db=True)
    assert hs._db_idempotent_cached(host, "base:0xfeed") == {
        "success": True,
        "cached": "base:0xfeed",
    }
    assert host._settled_txs == {"base:0xfeed": {"success": True, "cached": "base:0xfeed"}}

    monkeypatch.setattr(
        "pry.payments.x402.ledger_store.settlement_by_key",
        lambda key: {"success": False},
    )
    assert hs._db_idempotent_cached(host, "base:0xdead") is None
    assert hs._db_idempotent_cached(SettleHost(Router([]), use_db=False), "k") is None


def test_db_idempotency_failure_falls_through(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(_key: str) -> dict:
        raise RuntimeError("db down")

    monkeypatch.setattr("pry.payments.x402.ledger_store.settlement_by_key", boom)
    host = SettleHost(Router([]), use_db=True)
    assert hs._db_idempotent_cached(host, "base:0x3") is None


async def test_post_settle_hook_error_does_not_break_settle() -> None:
    host = SettleHost(Router([ok_receipt()]))
    seen: list[dict] = []

    def boom(record: dict) -> None:
        raise RuntimeError("hook down")

    host._post_settle_hooks.extend([boom, seen.append])

    out = await host.settle_payment("pay_1", "0xfeed", network="base")

    assert out["success"] is True
    assert [r["tx_hash"] for r in seen] == ["0xfeed"]


async def test_webhook_failure_is_swallowed_but_usage_is_recorded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def explode(_record: dict) -> None:
        raise RuntimeError("webhook down")

    monkeypatch.setattr("pry.payments.x402.handler.fire_settlement_webhook", explode)
    host = SettleHost(Router([ok_receipt()]))

    out = await host.settle_payment("pay_1", "0xfeed", network="base", amount_usd=0.25)

    assert out["success"] is True
    assert host.usage.calls == [("pay_1", 0.25, "base")]
