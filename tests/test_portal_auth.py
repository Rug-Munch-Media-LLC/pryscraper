# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for signed portal-token auth on the customer portal (magic-link).

Covers:
- valid token → 200 with the customer's data
- missing / tampered / expired token → 401
- a token signed for a different email never returns another email's data
- POST /v1/hosting/portal/request emails a link (mocked transport)
- magic-link rate limiting: 6th request within the hour is blocked
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

import pry.commerce.hosting as hosting_mod
from pry.api.api import app
from pry.commerce.hosting import _ensure_user_by_email
from pry.commerce.hosting.portal_tokens import (
    issue_portal_token,
    reset_portal_rate_state,
    verify_portal_token,
)

_REAL_WALLET = "0x00000000000000000000000000000000000ABCDE"
_SIGNING_KEY = "test-portal-signing-key"


@pytest.fixture(autouse=True)
def _portal_env(tmp_path, monkeypatch):
    """Isolated DB + fixed signing key + clean rate bucket per test."""
    monkeypatch.setenv("PRY_DATABASE_URL", f"sqlite:///{tmp_path}/portal-test.db")
    import pry.core.db as db_pkg
    import pry.core.db.session as session_mod

    monkeypatch.setattr(db_pkg, "_engine", None, raising=False)
    monkeypatch.setattr(session_mod, "_engine", None, raising=False)
    # get_engine() no longer creates the schema (Alembic owns it); the test
    # must bootstrap the tables explicitly, as the app lifespan does.
    from pry.core.db.session import init_db

    init_db()
    monkeypatch.setenv("PRY_PORTAL_SIGNING_KEY", _SIGNING_KEY)
    monkeypatch.delenv("PRY_REDIS_URL", raising=False)
    reset_portal_rate_state()
    yield
    reset_portal_rate_state()


@pytest.fixture
def customer() -> str:
    """A provisioned customer (email → user_id with one live instance)."""
    email = "customer@example.com"
    user_id = _ensure_user_by_email(email)
    hosting_mod._provision_instance(user_id, "pro")
    return email


def _get_portal(token: str) -> Any:
    with TestClient(app) as client:
        return client.get("/v1/hosting/portal", params={"token": token})


# ── Token round-trip ────────────────────────────────────────────────────────


def test_valid_token_returns_customer_data(customer: str) -> None:
    token = issue_portal_token(customer)
    resp = _get_portal(token)
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["email"] == customer
    assert len(data["instances"]) == 1


def test_missing_token_returns_401() -> None:
    with TestClient(app) as client:
        resp = client.get("/v1/hosting/portal")
    assert resp.status_code in (401, 422)  # FastAPI 422 for missing required query


def test_tampered_token_returns_401(customer: str) -> None:
    token = issue_portal_token(customer)
    payload, sig = token.split(".", 1)
    # Flip a signature byte.
    bad_sig = ("0" if sig[0] != "0" else "1") + sig[1:]
    resp = _get_portal(f"{payload}.{bad_sig}")
    assert resp.status_code == 401


def test_expired_token_returns_401(customer: str) -> None:
    token = issue_portal_token(customer, ttl_seconds=-1)
    assert verify_portal_token(token) is None
    resp = _get_portal(token)
    assert resp.status_code == 401


def test_token_for_different_email_does_not_leak(customer: str) -> None:
    other = "attacker@example.com"
    token = issue_portal_token(other)
    resp = _get_portal(token)
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["email"] == other
    assert data["instances"] == []  # attacker sees nothing of the customer's


def test_garbage_token_returns_401() -> None:
    for bad in ("", "not-a-token", "a.b.c", "...."):
        resp = _get_portal(bad)
        assert resp.status_code in (401, 422)


# ── Magic-link request flow ─────────────────────────────────────────────────


def test_portal_request_sends_email(customer: str, monkeypatch: pytest.MonkeyPatch) -> None:
    from pry.commerce.hosting import checkout as checkout_mod

    sent: list[dict[str, Any]] = []

    def fake_send(*, to_email: str, **kwargs: Any) -> dict[str, Any]:
        sent.append({"to": to_email, **kwargs})
        return {"success": True}

    monkeypatch.setattr(checkout_mod, "send_portal_link_email", fake_send)
    with TestClient(app) as client:
        resp = client.post("/v1/hosting/portal/request", json={"email": customer})
    assert resp.status_code == 200
    assert resp.json()["data"]["sent"] is True
    assert len(sent) == 1
    assert sent[0]["to"] == customer


def test_portal_request_unknown_email_is_generic(
    customer: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No enumeration: unknown emails get success + no email."""
    from pry.commerce.hosting import checkout as checkout_mod

    sent: list[dict[str, Any]] = []
    monkeypatch.setattr(
        checkout_mod,
        "send_portal_link_email",
        lambda **kw: sent.append(kw) or {"success": True},
    )
    with TestClient(app) as client:
        resp = client.post("/v1/hosting/portal/request", json={"email": "stranger@example.com"})
    assert resp.status_code == 200
    assert resp.json()["data"]["sent"] is False
    assert sent == []


def test_portal_request_rate_limited(customer: str, monkeypatch: pytest.MonkeyPatch) -> None:
    from pry.commerce.hosting import checkout as checkout_mod

    monkeypatch.setattr(checkout_mod, "send_portal_link_email", lambda **kw: {"success": True})
    with TestClient(app) as client:
        for _ in range(5):
            resp = client.post("/v1/hosting/portal/request", json={"email": customer})
            assert resp.status_code == 200
        sixth = client.post("/v1/hosting/portal/request", json={"email": customer})
    assert sixth.status_code == 429


# ── Receipt email carries the signed link ───────────────────────────────────


def test_receipt_contains_signed_portal_link(
    customer: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pry.commerce.hosting import checkout as checkout_mod

    captured: dict[str, Any] = {}

    def fake_mail(**kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {"success": True}

    monkeypatch.setattr(checkout_mod, "_send_pry_mail", fake_mail)
    monkeypatch.setenv("PRY_PUBLIC_BASE_URL", "https://api.example.com")
    checkout_mod.send_hosting_receipt(
        to_email=customer,
        invoice_id="inv_1",
        plan_tier="pro",
        amount_usd=49.0,
        tx_hash="0xabc",
        api_key="pry_live_key",
        instance_id="inst_1",
    )
    body = captured["body"]
    assert "email=" not in body  # no raw-email portal URL anymore
    assert "/v1/hosting/portal?token=" in body
    token = body.split("token=")[1].split()[0]
    assert verify_portal_token(token) == customer
