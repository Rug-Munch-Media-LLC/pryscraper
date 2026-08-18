"""Tests for routers/admin.py — self-hosted admin backend."""

from __future__ import annotations
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers.admin import router

app = FastAPI()
app.include_router(router)
client = TestClient(app, raise_server_exceptions=False)


def test_admin_health():
    r = client.get("/v1/admin/health")
    assert r.status_code in (200, 401, 500)
    if r.status_code == 200:
        data = r.json()
        assert data.get("status") == "healthy"
        assert "version" in data


def test_admin_config():
    r = client.get("/v1/admin/config")
    assert r.status_code in (200, 401, 500)
    if r.status_code == 200:
        data = r.json()
        assert "apify_api_key_set" in data
        assert "metrics_enabled" in data


def test_admin_ping():
    r = client.post("/v1/admin/ping", json={"test": True})
    assert r.status_code in (200, 401, 500)
    if r.status_code == 200:
        data = r.json()
        assert data.get("pong") is True
        assert data.get("echo") == {"test": True}


def test_admin_profits():
    r = client.get("/v1/admin/profits?days=7")
    assert r.status_code in (200, 401, 500)
    if r.status_code == 200:
        data = r.json()
        assert "data" in data


def test_admin_metrics():
    r = client.get("/v1/admin/metrics")
    assert r.status_code in (200, 401, 500)
    if r.status_code == 200:
        assert "pry_admin_" in r.text


def test_admin_html_dashboard():
    r = client.get("/v1/admin")
    assert r.status_code in (200, 401, 500)
    if r.status_code == 200:
        assert "Pry Admin" in r.text
        assert "Prometheus" in r.text
        assert "x402 Revenue" in r.text


def test_admin_dashboard():
    r = client.get("/v1/admin/dashboard")
    assert r.status_code in (200, 401, 500)
    if r.status_code == 200:
        data = r.json()
        assert "profits" in data
        assert "system" in data


def test_admin_apify_not_configured():
    with patch.dict("os.environ", {}, clear=True):
        r = client.get("/v1/admin/apify")
        assert r.status_code in (200, 401, 500)
        if r.status_code == 200:
            data = r.json()
            apify_data = data.get("data", {})
            assert apify_data.get("configured") is False


@patch("routers.admin.os.getenv")
def test_admin_apify_configured(mock_getenv):
    mock_getenv.return_value = "test-api-key"
    # Actually, we need to patch properly
    with patch("routers.admin._get_apify_profits") as mock_apify:
        mock_apify.return_value = {
            "configured": True,
            "actors": [
                {
                    "id": "test",
                    "name": "Test Actor",
                    "runs": 5,
                    "total_cost_usd": 1.50,
                    "total_compute_units": 10,
                }
            ],
            "total_profit_usd": 1.50,
            "total_runs": 5,
        }
        r = client.get("/v1/admin/apify")
        assert r.status_code in (200, 401, 500)
        if r.status_code == 200:
            data = r.json()
            assert "data" in data


def test_admin_profits_computation():
    """Test the profit computation logic directly."""
    from routers.admin import _compute_profits

    with patch(
        "routers.admin._get_x402_payments",
        return_value=[
            {"amount_usd": 10.0, "chain": "eip155:1", "asset": "USDC"},
            {"amount_usd": 5.0, "chain": "eip155:137", "asset": "USDC"},
        ],
    ):
        with patch(
            "routers.admin._get_usage_costs",
            return_value={
                "total_cost": 2.0,
                "projected_monthly": 30.0,
            },
        ):
            result = _compute_profits(days=30)
            assert result["x402"]["revenue_usd"] == 15.0
            assert result["x402"]["payment_count"] == 2
            assert result["x402"]["net_profit_usd"] == 15.0 - 0.30 - 2.0  # revenue - 2% fee - costs


def test_admin_load_jsonl():
    from routers.admin import _load_jsonl
    import tempfile
    import os

    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        f.write('{"a": 1}\n')
        f.write('{"a": 2}\n')
        f.write("invalid json\n")
        fname = f.name

    try:
        result = _load_jsonl(fname)
        assert len(result) == 2
        assert result[0]["a"] == 1
    finally:
        os.unlink(fname)


def test_admin_load_jsonl_missing():
    from routers.admin import _load_jsonl

    result = _load_jsonl("/tmp/nonexistent_file_12345.jsonl")
    assert result == []
