# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Broken upstream data must say "unavailable", never render as a healthy zero.

One test per surface, each asserting the response/log carries an explicit
unavailable marker instead of a plausible-looking empty/zero state:

- admin_html:   analytics failure  -> `analytics_error` + "Unavailable" payer row
- admin_shared: costing failure    -> `unavailable: True` (not "$0.00 spend")
- vision:       unparseable price  -> `model_pricing_unparseable` + model id
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from pry.api.routers.core.admin import ADMIN_PREFIX, router as admin_router  # isort:skip

# admin <-> admin_html is a pre-existing import cycle; importing `admin` first
# breaks it. Then reach the helpers under test through the settled module.
from pry.api.routers.ai.vision import router as vision_router
from pry.api.routers.core import admin_html, admin_shared

LOOPBACK = ("127.0.0.1", 51234)


@pytest.fixture
def client() -> TestClient:
    """Minimal app carrying only the admin router (no global auth stack)."""
    a = FastAPI()
    a.include_router(admin_router)
    return TestClient(a, client=LOOPBACK, raise_server_exceptions=False)


def _models_client() -> TestClient:
    a = FastAPI()
    a.include_router(vision_router)
    return TestClient(a, raise_server_exceptions=False)


def test_admin_html_analytics_failure_marks_unavailable(client, monkeypatch, caplog):
    """A broken analytics backend must not render as a healthy empty payer table."""

    def _boom() -> None:
        raise RuntimeError("payments.jsonl unreadable")

    monkeypatch.setattr("pry.payments.analytics.get_analytics", _boom, raising=True)

    with caplog.at_level("WARNING"):
        r = client.get(f"{ADMIN_PREFIX}/v1/admin")

    assert r.status_code == 200
    assert "Unavailable" in r.text
    assert "No payers yet" not in r.text
    assert "dashboard_analytics_failed" in caplog.text

    data: dict[str, Any] = admin_html._gather_dashboard_data(30)
    assert data["analytics_error"] == "payments.jsonl unreadable"


def test_admin_costing_failure_marks_unavailable(monkeypatch, caplog):
    """A broken costing ledger must not render as "$0.00 spend"."""

    def _boom() -> dict[str, Any]:
        raise OSError("ledger missing")

    monkeypatch.setattr("pry.commerce.costing.get_cost_dashboard", _boom)

    with caplog.at_level("WARNING"):
        costs = admin_shared._get_usage_costs(30)

    assert costs["unavailable"] is True
    assert costs["total_cost"] == 0
    assert "costing_ledger_unavailable" in caplog.text

    profits = admin_shared._compute_profits(30)
    assert profits["costs"]["unavailable"] is True


def test_vision_models_unparseable_pricing_is_logged(caplog):
    """An unparseable price must be logged with its model id, never silently dropped."""
    fake: dict[str, Any] = {
        "data": [
            {
                "id": "vendor/broken-price-vl",
                "name": "Broken Price VL",
                "architecture": {"input_modalities": ["image"]},
                "pricing": {"prompt": "free", "completion": "free"},
            }
        ]
    }
    resp = AsyncMock()
    resp.raise_for_status = MagicMock(return_value=None)
    resp.json = MagicMock(return_value=fake)

    with (
        patch("pry.api.routers.ai.vision.get_client", new_callable=AsyncMock) as mock_client,
        caplog.at_level("WARNING"),
    ):
        mock_client.return_value.get.return_value = resp
        r = _models_client().get("/v1/vision/models")

    assert r.status_code == 200
    assert r.json()["data"]["free_models"] == []
    assert "model_pricing_unparseable" in caplog.text
    assert any(
        getattr(rec, "model_id", None) == "vendor/broken-price-vl" for rec in caplog.records
    ), "model id missing from the model_pricing_unparseable warning"
