# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for the unified earnings tracker (pry.payments.earnings)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest


@pytest.fixture
def payments_file(tmp_path: Any) -> str:
    """payments.jsonl with two verified payments + one failed, all recent."""
    now = datetime.now(UTC)
    path = tmp_path / "payments.jsonl"
    rows = [
        {
            "amount_usd": 0.01,
            "verified": True,
            "verified_at": now.isoformat(),
            "network": "base",
            "asset": "USDC",
            "signer": "0xpayer1",
        },
        {
            "amount_usd": 0.02,
            "verified": True,
            "verified_at": (now - timedelta(days=1)).isoformat(),
            "network": "solana",
            "asset": "USDC",
            "signer": "0xpayer2",
        },
        {
            "amount_usd": 9.99,
            "verified": False,
            "verified_at": now.isoformat(),
            "network": "base",
            "asset": "USDC",
            "signer": "0xpayer3",
        },
    ]
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    return str(path)


@pytest.fixture
def settlements_file(tmp_path: Any) -> str:
    path = tmp_path / "settlements.jsonl"
    path.write_text(
        json.dumps(
            {
                "amount_usd": 0.03,
                "settled_at": datetime.now(UTC).isoformat(),
            }
        )
        + "\n"
    )
    return str(path)


@pytest.fixture
def db(tmp_path: Any, monkeypatch: pytest.MonkeyPatch):
    """Isolated SQLite DB (same pattern as test_api_keys_billing)."""
    monkeypatch.setenv("PRY_DATABASE_URL", f"sqlite:///{tmp_path}/test.db")
    import pry.core.db as db_pkg
    import pry.core.db.session as session_mod

    monkeypatch.setattr(db_pkg, "_engine", None, raising=False)
    monkeypatch.setattr(session_mod, "_engine", None, raising=False)

    from sqlalchemy import create_engine

    from pry.core.db import models as models_mod

    engine = create_engine(f"sqlite:///{tmp_path}/test.db")
    models_mod.Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def tracker(payments_file: str, settlements_file: str):
    from pry.payments.earnings import EarningsTracker

    return EarningsTracker(payments_file=payments_file, settlements_file=settlements_file)


@pytest.fixture(autouse=True)
def _clear_treasury_cache():
    from pry.payments import earnings as earnings_mod

    earnings_mod._treasury_cache.clear()
    yield
    earnings_mod._treasury_cache.clear()


# ── x402 stream ──────────────────────────────────────────────────────────────
class TestX402Stream:
    def test_only_verified_payments_counted(self, tracker) -> None:
        entries = tracker._x402_stream(30)
        assert len(entries) == 2
        assert all(e["amount_usd"] > 0 for e in entries)

    def test_total_earnings(self, tracker) -> None:
        total = tracker.get_total_earnings(30)
        assert total["by_stream"]["x402"] == pytest.approx(0.03)
        assert total["counts"]["x402"] == 2


# ── Pack purchases (billing ledger) ─────────────────────────────────────────
class TestPackStream:
    def test_pack_deposits_from_ledger(self, tracker, db) -> None:
        from pry.commerce import billing_service

        billing_service.credit("user1", 5.0, reason="deposit", reference="pack:inv_abc:0xtx")
        billing_service.credit("user1", 100.0, reason="deposit", reference="wire-transfer")
        billing_service.credit("user2", 2.5, reason="deposit", reference="pack:inv_def:0xtx2")
        billing_service.credit("user3", 50.0, reason="grant", reference="signup")

        entries = tracker._pack_stream(30)
        assert len(entries) == 2
        assert {e["amount_usd"] for e in entries} == {5.0, 2.5}
        assert tracker.get_total_earnings(30)["by_stream"]["packs"] == pytest.approx(7.5)

    def test_db_down_degrades_to_empty(self, tracker, monkeypatch) -> None:
        monkeypatch.setenv("PRY_DATABASE_URL", "sqlite:////nonexistent/x.db")
        import pry.core.db as db_pkg
        import pry.core.db.session as session_mod

        monkeypatch.setattr(db_pkg, "_engine", None, raising=False)
        monkeypatch.setattr(session_mod, "_engine", None, raising=False)
        assert tracker._pack_stream(30) == []  # never raises


# ── Subscriptions ────────────────────────────────────────────────────────────
class TestSubscriptionStream:
    @pytest.fixture
    def sub_state(self, monkeypatch):
        from pry.commerce.billing import subscription as sub

        monkeypatch.setattr(
            sub,
            "_INVOICES",
            {
                "inv_paid": {
                    "invoice_id": "inv_paid",
                    "tier": "pro",
                    "api_key": "key1",
                    "amount_usd": 49.0,
                    "chain": "base",
                    "status": "paid",
                    "payment": {"confirmed_at": datetime.now(UTC).isoformat()},
                },
                "inv_pending": {
                    "invoice_id": "inv_pending",
                    "tier": "team",
                    "amount_usd": 199.0,
                    "status": "pending",
                },
            },
        )
        monkeypatch.setattr(
            sub,
            "_SUBSCRIPTIONS",
            {
                "key1": {
                    "tier": "pro",
                    "expires_at": (datetime.now(UTC) + timedelta(days=20)).isoformat(),
                },
                "key2": {
                    "tier": "team",
                    "expires_at": (datetime.now(UTC) + timedelta(days=10)).isoformat(),
                },
                "key3": {
                    "tier": "pro",
                    "expires_at": (datetime.now(UTC) - timedelta(days=2)).isoformat(),
                },
                "key4": {
                    "tier": "free",
                    "expires_at": (datetime.now(UTC) + timedelta(days=30)).isoformat(),
                },
            },
        )
        return sub

    def test_only_paid_invoices_counted(self, tracker, sub_state) -> None:
        entries = tracker._subscription_stream(30)
        assert len(entries) == 1
        assert entries[0]["amount_usd"] == pytest.approx(49.0)
        assert entries[0]["tier"] == "pro"

    def test_mrr_counts_active_paid_tiers_only(self, tracker, sub_state) -> None:
        mrr = tracker.get_mrr()
        # key1 (pro, active) + key2 (team, active); key3 expired, key4 free
        assert mrr["mrr_usd"] == pytest.approx(49.0 + 199.0)
        assert mrr["arr_usd"] == pytest.approx((49.0 + 199.0) * 12)
        assert mrr["active_subscriptions"] == 2
        assert mrr["by_tier"] == {"pro": 1, "team": 1}


# ── Aggregations ─────────────────────────────────────────────────────────────
class TestAggregations:
    def test_daily_earnings_sorted_with_totals(self, tracker) -> None:
        daily = tracker.get_daily_earnings(30)
        assert [d["date"] for d in daily] == sorted(d["date"] for d in daily)
        for row in daily:
            streams = row["total_usd"]
            parts = sum(v for k, v in row.items() if k not in ("date", "total_usd"))
            assert streams == pytest.approx(parts)

    def test_revenue_by_chain(self, tracker) -> None:
        chains = tracker.get_revenue_by_chain(30)
        assert chains["base"]["total_usd"] == pytest.approx(0.01)
        assert chains["solana"]["total_usd"] == pytest.approx(0.02)

    def test_growth_rate(self, tracker) -> None:
        growth = tracker.get_growth_rate(30)
        assert growth["current_usd"] == pytest.approx(0.03)
        assert growth["previous_usd"] == pytest.approx(0.0)
        assert growth["growth_rate_pct"] == 100.0  # from zero -> 100%

    def test_export_csv(self, tracker) -> None:
        csv_text = tracker.export_csv(30)
        lines = csv_text.strip().splitlines()
        assert lines[0] == "date,x402,packs,subscriptions,apify_actors,total_usd"
        assert len(lines) >= 2
        total_col = lines[1].split(",")[-1]
        assert float(total_col := total_col) >= 0  # parseable


# ── Treasury balances (resilience) ──────────────────────────────────────────
class TestTreasuryBalances:
    def test_rpc_down_never_raises(self, tracker, monkeypatch) -> None:

        def boom(*a: Any, **k: Any) -> None:
            raise ConnectionError("rpc down")

        monkeypatch.setattr("httpx.get", boom)
        monkeypatch.setattr("httpx.post", boom)
        balances = tracker.get_treasury_balances()
        assert "error" in balances["evm"]
        assert "error" in balances["solana"]
        assert "error" in balances["tron"]

    def test_solana_balance_parsed(self, tracker, monkeypatch) -> None:
        class FakeResp:
            def raise_for_status(self) -> None:
                pass

            def json(self) -> dict[str, Any]:
                return {"result": {"value": 123_456_789}}  # lamports

        monkeypatch.setattr("httpx.post", lambda *a, **k: FakeResp())
        balances = tracker.get_treasury_balances()
        assert balances["solana"]["native_balance"] == pytest.approx(0.123456789, abs=1e-8)

    def test_tron_balance_parsed(self, tracker, monkeypatch) -> None:
        class FakeResp:
            def raise_for_status(self) -> None:
                pass

            def json(self) -> dict[str, Any]:
                return {"data": [{"balance": 25_000_000}]}  # sun

        monkeypatch.setattr("httpx.get", lambda *a, **k: FakeResp())
        balances = tracker.get_treasury_balances()
        assert balances["tron"]["native_balance"] == pytest.approx(25.0)

    def test_cache_hit_within_ttl(self, tracker, monkeypatch) -> None:
        calls = {"n": 0}

        class FakeResp:
            def raise_for_status(self) -> None:
                pass

            def json(self) -> dict[str, Any]:
                return {"data": [{"balance": 1_000_000}]}

        def fake_get(*a: Any, **k: Any) -> FakeResp:
            calls["n"] += 1
            return FakeResp()

        monkeypatch.setattr("httpx.get", fake_get)
        tracker._tron_balance()
        tracker._tron_balance()
        assert calls["n"] == 1  # second call served from cache


# ── Analytics delegation ─────────────────────────────────────────────────────
class TestAnalyticsDelegation:
    def test_analytics_delegates_to_tracker(self, tracker, payments_file, settlements_file) -> None:
        from pry.payments.analytics import PaymentAnalytics

        analytics = PaymentAnalytics(payments_file, settlements_file)
        assert analytics.get_total_earnings(30)["by_stream"]["x402"] == pytest.approx(0.03)
        assert analytics.get_revenue_by_stream(30)["x402"] == pytest.approx(0.03)
        assert isinstance(analytics.get_daily_earnings(30), list)
        assert "date" in analytics.export_earnings_csv(30).splitlines()[0]

    def test_default_ctor_uses_data_dir(self) -> None:
        from pry.payments.analytics import PaymentAnalytics

        a = PaymentAnalytics()
        assert a.payments_file.endswith("payments.jsonl")
        assert a.settlements_file.endswith("settlements.jsonl")
