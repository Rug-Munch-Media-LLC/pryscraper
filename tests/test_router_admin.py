# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for routers/admin.py — loopback-gated self-hosted admin backend.

Covers:
- The loopback-only security gate (_check_admin_access) for every access mode
- Every endpoint's happy-path response shape
- Profit computation from payments.jsonl + costing data
- Apify integration (unconfigured / API error / success)
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest
import respx
from fastapi import FastAPI
from fastapi.testclient import TestClient

import pry.api.routers.core.admin as admin_module
from pry.api.routers.core.admin import ADMIN_PREFIX, router as admin_router

if TYPE_CHECKING:
    from pathlib import Path

LOOPBACK = ("127.0.0.1", 51234)
REMOTE = ("203.0.113.7", 51234)


@pytest.fixture
def client() -> TestClient:
    """Minimal app carrying only the admin router (no global auth stack)."""
    a = FastAPI()
    a.include_router(admin_router)
    return TestClient(a, client=LOOPBACK, raise_server_exceptions=False)


@pytest.fixture
def remote_client() -> TestClient:
    a = FastAPI()
    a.include_router(admin_router)
    return TestClient(a, client=REMOTE, raise_server_exceptions=False)


@pytest.fixture
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isolate PRY_DATA_DIR so payment-log fixtures never touch real data."""
    monkeypatch.setattr(admin_module, "PRY_DATA_DIR", str(tmp_path))
    return tmp_path


def _write_payments(data_dir: Path, rows: list[dict[str, Any]]) -> None:
    pdir = data_dir / "x402"
    pdir.mkdir(parents=True, exist_ok=True)
    with open(pdir / "payments.jsonl", "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


# ── Security gate ────────────────────────────────────────────────────────────


class TestLoopbackGate:
    def test_loopback_client_allowed(self, client: TestClient) -> None:
        r = client.post(f"{ADMIN_PREFIX}/v1/admin/ping", json={})
        assert r.status_code == 200

    def test_remote_client_403_by_default(self, remote_client: TestClient) -> None:
        r = remote_client.post(f"{ADMIN_PREFIX}/v1/admin/ping", json={})
        assert r.status_code == 403
        assert "loopback-only" in r.json()["detail"].lower()

    def test_remote_allowed_when_loopback_only_disabled(
        self, remote_client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(admin_module, "ADMIN_LOOPBACK_ONLY", False)
        r = remote_client.post(f"{ADMIN_PREFIX}/v1/admin/ping", json={})
        assert r.status_code == 200

    def test_gate_applies_to_every_endpoint(self, remote_client: TestClient) -> None:
        for path in (
            "/v1/admin",
            "/v1/admin/dashboard",
            "/v1/admin/profits",
            "/v1/admin/health",
            "/v1/admin/apify",
            "/v1/admin/metrics",
            "/v1/admin/config",
        ):
            r = remote_client.get(f"{ADMIN_PREFIX}{path}")
            assert r.status_code == 403, path


# ── Endpoints ────────────────────────────────────────────────────────────────


class TestEndpoints:
    def test_ping_echoes_body(self, client: TestClient) -> None:
        r = client.post(f"{ADMIN_PREFIX}/v1/admin/ping", json={"hello": "world"})
        assert r.status_code == 200
        body = r.json()
        assert body["success"] is True
        assert body["pong"] is True
        assert body["echo"] == {"hello": "world"}

    def test_config_reports_state(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("APIFY_API_KEY", raising=False)
        r = client.get(f"{ADMIN_PREFIX}/v1/admin/config")
        assert r.status_code == 200
        body = r.json()
        assert body["success"] is True
        assert body["apify_api_key_set"] is False
        assert body["metrics_enabled"] is True

    def test_health_shape(self, client: TestClient) -> None:
        r = client.get(f"{ADMIN_PREFIX}/v1/admin/health")
        assert r.status_code == 200
        body = r.json()
        assert body["success"] is True
        assert body["status"] == "healthy"
        assert isinstance(body["uptime_seconds"], float)
        assert set(body["cache"]) == {"hit_rate", "size", "hits"}
        assert "version" in body

    def test_profits_math_with_payment_fixture(
        self, client: TestClient, data_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write_payments(
            data_dir,
            [
                {"amount_usd": 1.00},
                {"amount_usd": 0.50},
                {"amount_usd": "not-a-number"},  # corrupt row: counts as 0, never 500s
            ],
        )
        monkeypatch.setattr(
            "pry.commerce.costing.get_cost_dashboard",
            lambda: {"total_cost": 0.10, "projected_monthly": 3.0},
            raising=False,
        )
        r = client.get(f"{ADMIN_PREFIX}/v1/admin/profits")
        assert r.status_code == 200
        profits = r.json()["data"]
        # 1.00 + 0.50 revenue (corrupt row coerced to 0); 2% fee; minus cost.
        assert profits["x402"]["revenue_usd"] == 1.5
        assert profits["x402"]["payment_count"] == 3
        assert profits["x402"]["processing_fee_usd"] == 0.03
        assert profits["x402"]["net_profit_usd"] == 1.37
        assert profits["costs"]["total_operating_cost_usd"] == 0.1
        assert profits["period_days"] == 30

    def test_profits_days_window_filters_old_payments(
        self, client: TestClient, data_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Regression: the days cutoff used to be a no-op ('or True')."""
        from datetime import UTC, datetime, timedelta

        now = datetime.now(UTC)
        old_ts = (now - timedelta(days=90)).isoformat()
        new_ts = (now - timedelta(days=1)).isoformat()
        _write_payments(
            data_dir,
            [
                {"amount_usd": 99.00, "ts": old_ts},
                {"amount_usd": 1.00, "ts": new_ts},
            ],
        )
        monkeypatch.setattr(
            "pry.commerce.costing.get_cost_dashboard", lambda: {"total_cost": 0}, raising=False
        )
        r = client.get(f"{ADMIN_PREFIX}/v1/admin/profits?days=30")
        assert r.status_code == 200
        profits = r.json()["data"]
        assert profits["x402"]["revenue_usd"] == 1.0
        assert profits["x402"]["payment_count"] == 1

    def test_dashboard_aggregates_everything(
        self, client: TestClient, data_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write_payments(data_dir, [{"amount_usd": 2.00}])
        monkeypatch.setattr(
            "pry.commerce.costing.get_cost_dashboard", lambda: {"total_cost": 0}, raising=False
        )
        r = client.get(f"{ADMIN_PREFIX}/v1/admin/dashboard")
        assert r.status_code == 200
        body = r.json()
        assert body["success"] is True
        assert body["profits"]["x402"]["revenue_usd"] == 2.0
        assert body["system"]["active_sessions"] >= 0
        assert body["period_days"] == 30

    def test_metrics_returns_prometheus_text(self, client: TestClient) -> None:
        r = client.get(f"{ADMIN_PREFIX}/v1/admin/metrics")
        assert r.status_code == 200
        assert "pry_admin_revenue_total_usd" in r.text
        assert "pry_admin_scrapes_active" in r.text

    def test_html_dashboard_renders(self, client: TestClient) -> None:
        r = client.get(f"{ADMIN_PREFIX}/v1/admin")
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]
        assert "Pry Admin" in r.text


# ── Earnings / users / payments endpoints ────────────────────────────────────


class TestEarningsEndpoints:
    def test_earnings_shape(self, client: TestClient, data_dir: Path) -> None:
        _write_payments(data_dir, [{"amount_usd": 1.25, "verified": True}])
        r = client.get(f"{ADMIN_PREFIX}/v1/admin/earnings")
        assert r.status_code == 200
        body = r.json()
        assert body["success"] is True
        assert body["backend"] in {"earnings_tracker", "payment_analytics"}
        assert "total" in body
        assert "daily" in body
        assert "by_stream" in body
        assert "by_chain" in body
        assert "mrr" in body
        assert "growth" in body

    def test_treasury_never_500(self, client: TestClient, data_dir: Path) -> None:
        _write_payments(data_dir, [])
        r = client.get(f"{ADMIN_PREFIX}/v1/admin/earnings/treasury")
        assert r.status_code == 200
        body = r.json()
        assert body["success"] is True
        assert "treasury" in body


class TestUserAdmin:
    def test_users_list_shape(self, client: TestClient) -> None:
        r = client.get(f"{ADMIN_PREFIX}/v1/admin/users")
        assert r.status_code == 200
        body = r.json()
        assert body["success"] is True
        assert isinstance(body["users"], list)
        for u in body["users"]:
            assert {"user_id", "email", "tier", "is_active", "balance_usd"} <= set(u)

    def test_credit_then_list_shows_balance(self, client: TestClient) -> None:
        import uuid

        uid = f"u-credit-{uuid.uuid4().hex[:8]}"
        r = client.post(
            f"{ADMIN_PREFIX}/v1/admin/users/{uid}/credit",
            json={"amount_usd": 5.0, "reason": "grant"},
        )
        assert r.status_code == 200
        assert r.json()["success"] is True

        r = client.get(f"{ADMIN_PREFIX}/v1/admin/users")
        users = r.json()["users"]
        match = [u for u in users if u["user_id"] == uid]
        assert len(match) == 1
        assert match[0]["balance_usd"] == pytest.approx(5.0)

    def test_credit_rejects_bad_amount(self, client: TestClient) -> None:
        r = client.post(f"{ADMIN_PREFIX}/v1/admin/users/u-x/credit", json={"amount_usd": -1})
        assert r.status_code == 422

    def test_credit_rejects_bad_reason(self, client: TestClient) -> None:
        r = client.post(
            f"{ADMIN_PREFIX}/v1/admin/users/u-x/credit",
            json={"amount_usd": 1, "reason": "nonsense"},
        )
        assert r.status_code == 422

    def test_suspend_unknown_user_404(self, client: TestClient) -> None:
        r = client.post(f"{ADMIN_PREFIX}/v1/admin/users/nope/suspend")
        assert r.status_code == 404

    def test_suspend_disables_account(self, client: TestClient) -> None:
        import uuid

        from pry.core.db.models import User
        from pry.core.db.session import get_session

        uid = f"u-susp-{uuid.uuid4().hex[:8]}"
        with get_session() as s:
            s.add(User(user_id=uid, email=f"{uid}@test", password_hash="x"))
            s.commit()
        r = client.post(f"{ADMIN_PREFIX}/v1/admin/users/{uid}/suspend")
        assert r.status_code == 200
        with get_session() as s:
            assert s.query(User).filter_by(user_id=uid).first().is_active is False


class TestPaymentEndpoints:
    def test_recent_returns_newest_first_capped_50(
        self, client: TestClient, data_dir: Path
    ) -> None:
        from datetime import UTC, datetime, timedelta

        now = datetime.now(UTC)
        rows = [
            {"amount_usd": float(i), "ts": (now - timedelta(hours=i)).isoformat(), "verified": True}
            for i in range(60)
        ]
        _write_payments(data_dir, rows)
        r = client.get(f"{ADMIN_PREFIX}/v1/admin/payments/recent")
        assert r.status_code == 200
        body = r.json()
        assert body["count"] == 50
        assert len(body["payments"]) == 50
        # newest first: first row is the most recent (i=0)
        assert body["payments"][0]["amount_usd"] == 0.0

    def test_failed_lists_unverified(self, client: TestClient, data_dir: Path) -> None:
        _write_payments(
            data_dir,
            [
                {"amount_usd": 1.0, "verified": True},
                {"amount_usd": 2.0, "verified": False, "reason": "bad signature"},
            ],
        )
        r = client.get(f"{ADMIN_PREFIX}/v1/admin/payments/failed")
        assert r.status_code == 200
        body = r.json()
        assert body["count"] == 1
        assert body["payments"][0]["reason"] == "bad signature"


# ── Apify integration ────────────────────────────────────────────────────────


class TestApify:
    def test_unconfigured_returns_hint(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("APIFY_API_KEY", raising=False)
        r = client.get(f"{ADMIN_PREFIX}/v1/admin/apify")
        assert r.status_code == 200
        body = r.json()["data"]
        assert body["configured"] is False
        assert body["actors"] == []
        assert body["total_profit_usd"] == 0

    @respx.mock
    def test_api_error_reported_not_raised(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("APIFY_API_KEY", "fake-key")
        respx.get("https://api.apify.com/v2/actor-runs/").mock(return_value=respx.MockResponse(500))
        r = client.get(f"{ADMIN_PREFIX}/v1/admin/apify")
        assert r.status_code == 200
        body = r.json()["data"]
        assert body["configured"] is True
        assert "500" in body.get("error", "")

    @respx.mock
    def test_runs_aggregated_per_actor(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("APIFY_API_KEY", "fake-key")
        respx.get("https://api.apify.com/v2/actor-runs/").mock(
            return_value=respx.MockResponse(
                200,
                json={
                    "data": [
                        {
                            "actId": "actor-a",
                            "actName": "Scraper A",
                            "usageTotalUsd": 1.25,
                            "usageTotalCu": 4.0,
                        },
                        {
                            "actId": "actor-a",
                            "actName": "Scraper A",
                            "usageTotalUsd": 0.75,
                            "usageTotalCu": 2.0,
                        },
                    ]
                },
            )
        )
        r = client.get(f"{ADMIN_PREFIX}/v1/admin/apify")
        assert r.status_code == 200
        body = r.json()["data"]
        assert body["configured"] is True
        assert body["total_runs"] == 2
        assert body["actors"][0]["runs"] == 2
        assert body["actors"][0]["total_cost_usd"] == pytest.approx(2.0)
        assert body["total_profit_usd"] == 2.0
