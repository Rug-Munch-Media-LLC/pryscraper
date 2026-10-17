"""Reconciliation regressions: clock, source of truth, revenue, invoices."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from pathlib import Path


def _write_payments(data_dir: Path, rows: list[dict[str, Any]]) -> None:
    pdir = data_dir / "x402"
    pdir.mkdir(parents=True, exist_ok=True)
    with open(pdir / "payments.jsonl", "w") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


@pytest.fixture(autouse=True)
def _jsonl_source(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force the JSONL fallback so tests never depend on a live database."""
    from pry.payments.x402 import ledger_store

    monkeypatch.setattr(ledger_store, "available", lambda: False)


@pytest.fixture
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    from pry.api.routers.core import admin

    monkeypatch.setattr(admin, "PRY_DATA_DIR", tmp_path)
    return tmp_path


def test_verified_at_only_row_included_in_seven_day_window(data_dir: Path) -> None:
    """The clock reads verified_at, not ts: a short window must not be empty."""
    from pry.api.routers.core.admin_shared import _get_x402_payments

    now = datetime.now(UTC)
    _write_payments(
        data_dir,
        [
            {
                "payment_id": "p_recent",
                "tx_hash": "0xabc",
                "amount_usd": 2.5,
                "verified": True,
                "verified_at": (now - timedelta(days=1)).isoformat(),
            }
        ],
    )
    payments = _get_x402_payments(days=7)
    assert len(payments) == 1
    assert payments[0]["payment_id"] == "p_recent"
    assert payments[0]["ts"]


def test_recent_payments_newest_first_and_count_pre_slice(data_dir: Path) -> None:
    """Ordering uses the canonical clock; count reflects the whole window."""
    from pry.api.routers.core import admin_payments

    now = datetime.now(UTC)
    rows = [
        {
            "payment_id": f"p{i}",
            "tx_hash": f"0x{i:02d}",
            "amount_usd": 0.01,
            "verified": True,
            "verified_at": (now - timedelta(minutes=i)).isoformat(),
        }
        for i in range(60)
    ]
    _write_payments(data_dir, rows)
    body = asyncio.run(admin_payments.admin_payments_recent())
    assert body["count"] == 60
    assert len(body["payments"]) == 50
    assert body["payments"][0]["payment_id"] == "p0"
    stamps = [row["ts"] for row in body["payments"]]
    assert stamps == sorted(stamps, reverse=True)


def test_unverified_rows_are_not_revenue(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A failed verification is a payment attempt, never income."""
    from pry.api.routers.core import admin_shared

    stamp = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    _write_payments(
        data_dir,
        [
            {"payment_id": "ok", "amount_usd": 2.0, "verified": True, "verified_at": stamp},
            {"payment_id": "fail", "amount_usd": 5.0, "verified": False, "verified_at": stamp},
        ],
    )
    monkeypatch.setattr(
        admin_shared,
        "_get_usage_costs",
        lambda days=30: {"total_cost": 0, "projected_monthly": 0},
    )
    profits = admin_shared._compute_profits(30)
    assert profits["x402"]["revenue_usd"] == 2.0
    assert profits["x402"]["payment_count"] == 2


def test_undated_invoice_skipped_not_dated_today(monkeypatch: pytest.MonkeyPatch) -> None:
    """No settled_at and no created_at means no date, not the current day."""
    from pry.commerce.billing import subscription as sub
    from pry.payments.earnings import EarningsTracker

    monkeypatch.setattr(sub, "_ensure_loaded", lambda: None)
    dated = (datetime.now(UTC) - timedelta(days=2)).isoformat()
    monkeypatch.setitem(
        sub._INVOICES,
        "inv_undated",
        {
            "invoice_id": "inv_undated",
            "status": "paid",
            "amount_usd": 9.0,
            "tier": "pro",
            "api_key": "key_undated",
        },
    )
    monkeypatch.setitem(
        sub._INVOICES,
        "inv_dated",
        {
            "invoice_id": "inv_dated",
            "status": "paid",
            "amount_usd": 1.0,
            "tier": "pro",
            "api_key": "key_dated",
            "created_at": dated,
        },
    )
    try:
        tracker = EarningsTracker(payments_file="", settlements_file="")
        entries = tracker._subscription_stream(30)
    finally:
        sub._INVOICES.pop("inv_undated", None)
        sub._INVOICES.pop("inv_dated", None)
    assert len(entries) == 1
    assert entries[0]["payer"] == "key_dated"
    assert entries[0]["amount_usd"] == 1.0
    assert entries[0]["date"] == dated[:10]
