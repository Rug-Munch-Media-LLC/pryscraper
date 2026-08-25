# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for API-key lifecycle, billing drawdown, and middleware wiring.

Covers audit wins A1-A4: key issue/authenticate/revoke (hashed at rest),
per-key rate limits, usage metering flush, balance credit/drawdown/ledger,
and the admin-scope guard on the management router.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Any
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import pry.api.api_keys_service as svc
import pry.commerce.billing_service as billing
import pry.core.middleware as mw_module

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Isolated SQLite DB for the session layer.

    Uses the documented test-reset pattern (db._engine = None) to force
    engine recreation against the temp database.
    """
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


class TestKeyLifecycle:
    def test_issue_returns_plaintext_once_and_stores_hash(self, db) -> None:
        result = svc.issue_key(name="ci", tier="PRO")
        plaintext = result["plaintext"]
        assert plaintext.startswith("pry_")
        parts = plaintext.split("_")
        assert len(parts) == 3
        assert len(parts[1]) == 8
        assert len(parts[2]) == 32
        # stored hash matches sha256 of plaintext; plaintext itself absent
        assert result["key_hash"] == hashlib.sha256(plaintext.encode()).hexdigest()
        listed = svc.list_keys()
        assert len(listed) == 1
        assert "key_hash" not in listed[0]
        assert "plaintext" not in listed[0]

    def test_tier_defaults_applied(self, db) -> None:
        pro = svc.issue_key(tier="PRO")
        free = svc.issue_key(tier="FREE")
        recs = {k["key_id"]: k for k in svc.list_keys()}
        assert recs[pro["key_id"]]["rate_limit_rpm"] == 600
        assert recs[free["key_id"]]["rate_limit_rpm"] == 60

    def test_unknown_tier_rejected(self, db) -> None:
        with pytest.raises(ValueError, match="unknown tier"):
            svc.issue_key(tier="GOLD")

    def test_authenticate_roundtrip(self, db) -> None:
        issued = svc.issue_key(tier="ENTERPRISE", scopes=["scrape", "admin"])
        record = svc.authenticate(issued["plaintext"])
        assert record is not None
        assert record["key_id"] == issued["key_id"]
        assert record["rate_limit_rpm"] == 6000
        assert "admin" in record["scopes"]

    def test_revoked_key_fails_auth(self, db) -> None:
        issued = svc.issue_key()
        assert svc.authenticate(issued["plaintext"]) is not None
        assert svc.revoke_key(issued["key_id"]) is True
        assert svc.authenticate(issued["plaintext"]) is None
        assert svc.revoke_key(issued["key_id"]) is False  # already revoked

    def test_expired_key_fails_auth(self, db) -> None:
        from datetime import UTC, datetime, timedelta

        past = datetime.now(UTC) - timedelta(days=1)
        issued = svc.issue_key(expires_at=past)
        assert svc.authenticate(issued["plaintext"]) is None

    def test_non_pry_token_never_hits_db(self, db) -> None:
        assert svc.authenticate("sk-something-else") is None
        assert svc.authenticate("") is None


class TestBilling:
    def test_credit_drawdown_ledger_flow(self, db) -> None:
        billing.credit("u1", 10.0, reason="deposit", reference="tx1")
        billing.credit("u1", 2.5, reason="grant")
        after_use = billing.drawdown("u1", 3.25, reference="key_x")
        assert after_use["balance_usd"] == 9.25
        entries = billing.ledger("u1")
        assert [e["reason"] for e in entries] == ["usage", "grant", "deposit"]
        assert entries[-1]["balance_after"] == 10.0

    def test_insufficient_balance_raises(self, db) -> None:
        billing.credit("u2", 1.0, reason="deposit")
        with pytest.raises(billing.InsufficientBalance):
            billing.drawdown("u2", 5.0)

    def test_invalid_reasons_rejected(self, db) -> None:
        with pytest.raises(ValueError, match="not a credit reason"):
            billing.credit("u3", 5.0, reason="usage")  # usage is a debit reason
        with pytest.raises(ValueError, match="positive"):
            billing.credit("u3", -1, reason="deposit")
        with pytest.raises(ValueError, match="positive"):
            billing.drawdown("u3", 0)

    def test_low_balance_flag(self, db) -> None:
        billing.credit("u4", 4.0, reason="deposit")  # below default 5.0 threshold
        assert billing.get_balance("u4")["low_balance"] is True
        billing.credit("u4", 10.0, reason="deposit")
        assert billing.get_balance("u4")["low_balance"] is False


class TestMiddlewareWiring:
    @staticmethod
    def _app_with_route() -> FastAPI:
        a = FastAPI()

        @a.get("/v1/scrape")
        async def scrape() -> dict[str, bool]:
            return {"ok": True}

        a.add_middleware(mw_module.PryHttpMiddleware)
        return a

    def test_db_key_authenticates_through_middleware(
        self, db, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(mw_module.settings, "api_key", "")
        issued = svc.issue_key(tier="PRO")
        client = TestClient(self._app_with_route(), raise_server_exceptions=False)
        r = client.get("/v1/scrape", headers={"Authorization": f"Bearer {issued['plaintext']}"})
        assert r.status_code == 200

    def test_bad_key_rejected_even_keyless_loopback_off(
        self, db, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(mw_module.settings, "api_key", "")
        client = TestClient(
            self._app_with_route(), client=("203.0.113.9", 5000), raise_server_exceptions=False
        )
        r = client.get("/v1/scrape", headers={"Authorization": "Bearer pry_deadbeef_" + "0" * 32})
        assert r.status_code == 401

    def test_usage_metered_for_db_keys(self, db, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(mw_module.settings, "api_key", "")
        issued = svc.issue_key(tier="FREE")
        mw_module._usage_queue.clear()
        client = TestClient(self._app_with_route(), raise_server_exceptions=False)
        for _ in range(50):  # hit the flush batch size exactly
            client.get("/v1/scrape", headers={"Authorization": f"Bearer {issued['plaintext']}"})
        rows = self._usage_rows()
        assert len(rows) >= 50
        assert all(r["api_key_id"] == issued["key_id"] for r in rows)
        assert all(r["operation"] == "/v1/scrape" for r in rows)

    @staticmethod
    def _usage_rows() -> list[dict[str, Any]]:
        from pry.core.db import models as _models
        from pry.core.db.session import get_session

        with get_session() as session:
            return [
                {"api_key_id": r.api_key_id, "operation": r.operation}
                for r in session.query(_models.Usage).all()  # type: ignore[union-attr]
            ]


class TestKeysRouter:
    @staticmethod
    def _client() -> TestClient:
        from routers.api_keys import router

        a = FastAPI()
        a.include_router(router)
        return TestClient(a, raise_server_exceptions=False)

    def test_issue_list_revoke_via_http(self, db) -> None:
        c = self._client()  # loopback client by default -> admin allowed
        r = c.post("/v1/keys", json={"name": "ops", "tier": "PRO"})
        assert r.status_code == 200
        body = r.json()["data"]
        key_id = body["key_id"]
        assert body["plaintext"].startswith("pry_")

        listed = c.get("/v1/keys").json()["data"]
        assert any(k["key_id"] == key_id for k in listed)

        r = c.delete(f"/v1/keys/{key_id}")
        assert r.status_code == 200
        assert c.delete(f"/v1/keys/{key_id}").status_code == 404

    def test_remote_non_admin_key_gets_403(self, db) -> None:
        issued = svc.issue_key(scopes=["scrape"])  # no admin scope
        a = FastAPI()
        from routers.api_keys import router

        a.include_router(router)
        client = TestClient(a, client=("203.0.113.5", 5000), raise_server_exceptions=False)

        # simulate the middleware having authenticated this remote caller
        def fake_auth(scope):
            scope["pry_api_key"] = {
                "key_id": issued["key_id"],
                "user_id": issued["user_id"],
                "scopes": ["scrape"],
                "rate_limit_rpm": 60,
            }
            return True

        monkey = patch.object(mw_module, "request_authorized", fake_auth)
        with monkey:
            r = client.post("/v1/keys", json={"name": "x"})
        assert r.status_code == 403

    def test_balance_endpoints_roundtrip(self, db) -> None:
        issued = svc.issue_key()
        c = self._client()
        r = c.post(f"/v1/keys/{issued['key_id']}/credit", json={"amount_usd": 12.5})
        assert r.status_code == 200
        bal = c.get(f"/v1/keys/{issued['key_id']}/balance").json()["data"]
        assert bal["balance_usd"] == 12.5
        ledger = c.get(f"/v1/keys/{issued['key_id']}/ledger").json()["data"]
        assert ledger[0]["reason"] == "deposit"
