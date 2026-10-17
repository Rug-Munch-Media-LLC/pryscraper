# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
"""Money-path regression tests for audit P0 classes.

Each test names the invariant it protects. Two batch invariants are NOT yet
enforced in ``src/pry/payments/x402/batch/payments.py`` (the batch is marked
``paid`` even when settlement fails, and an individual payment never consults
the batch tx-claim set). They are encoded as non-strict xfail so the gap is
tracked rather than silently accepted; removing the marker is the fix signal.
"""

from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from pry.core import api_keys_service
from pry.core.middleware_auth import request_authorized
from pry.payments.earnings import EarningsTracker
from pry.payments.x402 import X402Handler
from pry.payments.x402.batch import (
    _batch_payments,
    _consumed_txs,
    create_batch_payment,
    is_batch_paid,
    state as batch_state,
    verify_batch_payment,
)
from pry.payments.x402_middleware import X402Middleware


@pytest.fixture(autouse=True)
def _clean_batch_state():
    _batch_payments.clear()
    _consumed_txs.clear()
    batch_state._redis_client = None
    batch_state._redis_url = ""
    batch_state._redis_failed_at = 0.0
    yield
    _batch_payments.clear()
    _consumed_txs.clear()


@pytest.fixture
def db(tmp_path, monkeypatch):
    """Isolated SQLite DB for the API-key store."""
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


@pytest.mark.asyncio
@pytest.mark.xfail(
    strict=False,
    reason="audit P0: verify_batch_payment sets paid=True after a failed settle; "
    "fix belongs in src/pry/payments/x402/batch/payments.py (out of scope here)",
)
async def test_settle_failure_must_not_grant_paid_access():
    from unittest.mock import AsyncMock, patch

    created = await create_batch_payment(["scrape"])
    bid = created["batch_id"]
    router = AsyncMock()
    router.verify.return_value = {"verified": True, "reason": ""}
    router.settle.return_value = {"success": False, "reason": "rpc down"}
    with patch("pry.payments.x402.batch.payments.get_facilitator_router", return_value=router):
        result = await verify_batch_payment(bid, "0xsettlefail")

    assert result["verified"] is True
    assert result["settled"] is False
    assert is_batch_paid(bid) is False, "a failed settle must not unlock the batch"


@pytest.mark.asyncio
async def test_failed_settle_records_no_successful_ledger_row(tmp_path):
    from unittest.mock import AsyncMock, MagicMock, patch

    router = MagicMock()
    router.settle = AsyncMock(return_value={"success": False, "reason": "rpc down"})
    with patch("pry.payments.x402.handler.get_facilitator_router", return_value=router):
        handler = X402Handler(
            payments_file=tmp_path / "payments.jsonl",
            settlements_file=tmp_path / "settlements.jsonl",
        )
        receipt = await handler.settle_payment("p_fail", "0xfailed", network="base")
        await handler.settle_payment("p_fail", "0xfailed", network="base")

    assert receipt["success"] is False
    # No idempotency index entry and no usage volume: a retry must re-settle.
    assert handler._settled_txs == {}
    assert handler.usage.get_stats("p_fail") == {}
    assert router.settle.await_count == 2
    rows = [
        json.loads(line)
        for line in (tmp_path / "settlements.jsonl").read_text().splitlines()
        if line.strip()
    ]
    assert rows
    assert all(row["success"] is False for row in rows)


def test_revoked_key_cannot_authenticate_and_gate_answers_402(db):
    issued = api_keys_service.issue_key(name="p0-revoked")
    token = issued["plaintext"]
    scope = {"type": "http", "headers": [(b"authorization", f"Bearer {token}".encode())]}
    assert request_authorized(scope) is True  # key works before revocation

    assert api_keys_service.revoke_key(issued["key_id"]) is True
    assert request_authorized(scope) is False  # revoked key is dead

    app = FastAPI()

    @app.get("/v1/scrape")
    async def _paid() -> dict[str, bool]:
        return {"served": True}

    app.add_middleware(X402Middleware)
    response = TestClient(app).get("/v1/scrape", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 402
    assert "PAYMENT-REQUIRED" in response.headers


@pytest.mark.asyncio
@pytest.mark.xfail(
    strict=False,
    reason="audit P0: individual verify does not consult the batch tx-claim set; "
    "fix belongs in src/pry/payments/x402/handler_verify*.py (out of scope here)",
)
async def test_batch_tx_cannot_be_reused_individually(tmp_path):
    from unittest.mock import AsyncMock, MagicMock, patch

    created = await create_batch_payment(["scrape"])
    router = AsyncMock()
    router.verify.return_value = {"verified": True, "reason": ""}
    router.settle.return_value = {"success": True}
    with patch("pry.payments.x402.batch.payments.get_facilitator_router", return_value=router):
        assert (await verify_batch_payment(created["batch_id"], "0xshared"))["verified"] is True

    individual = MagicMock()
    individual.verify = AsyncMock(return_value={"verified": True, "reason": ""})
    with patch("pry.payments.x402.handler.get_facilitator_router", return_value=individual):
        handler = X402Handler(
            payments_file=tmp_path / "payments.jsonl",
            settlements_file=tmp_path / "settlements.jsonl",
        )
        replay = await handler.verify_payment(
            "p_single", "0xshared", network="base", operation="scrape", amount_usd=0.001
        )
    assert replay["verified"] is False
    assert replay["reason"] == "tx_hash already consumed"


class _LedgerStub:
    def _load_payments(self, days: int) -> list[dict]:
        return [
            {
                "verified": True,
                "amount_usd": 1.25,
                "network": "base",
                "verified_at": "2026-10-18T00:00:00+00:00",
            },
            {
                "verified": False,
                "amount_usd": 99.0,
                "network": "base",
                "verified_at": "2026-10-18T00:00:00+00:00",
            },
        ]


def test_unverified_row_excluded_from_revenue():
    totals = EarningsTracker(analytics=_LedgerStub()).get_total_earnings(30)
    assert totals["by_stream"]["x402"] == 1.25
    assert totals["counts"]["x402"] == 1
