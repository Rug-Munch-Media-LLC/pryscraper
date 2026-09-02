# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Handler DB-mode integration (audit item #2, PART 2).

With PRY_DATABASE_URL configured and no explicit ledger files, the
X402Handler adopts the Postgres-backed ledger store: payments and
settlements are DB records (the JSONL files are an audit-only trail) and
settle idempotency is DB-first — authoritative across processes.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

import pry.payments.x402.handler as handler_mod
from pry.payments.x402 import ledger_store
from pry.payments.x402.handler import X402Handler


@pytest.fixture
def db(tmp_path, monkeypatch):
    """Isolated DB + default ledger files (no explicit files → DB mode)."""
    monkeypatch.setenv("PRY_DATABASE_URL", f"sqlite:///{tmp_path}/handler-db.db")
    import pry.core.db as db_pkg
    import pry.core.db.session as session_mod

    monkeypatch.setattr(db_pkg, "_engine", None, raising=False)
    monkeypatch.setattr(session_mod, "_engine", None, raising=False)

    from sqlalchemy import create_engine

    from pry.core.db import models as models_mod

    engine = create_engine(f"sqlite:///{tmp_path}/handler-db.db")
    models_mod.Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture(autouse=True)
def _isolated_ledger_dir(tmp_path, monkeypatch):
    """Point X402_DIR at a scratch dir so audit-only JSONL stays isolated."""
    scratch = tmp_path / "x402-scratch"
    scratch.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(handler_mod, "X402_DIR", scratch)


class _FakeRouter:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.settle_calls: list[dict[str, Any]] = []

    async def verify(self, **kwargs: Any) -> dict[str, Any]:
        return {"verified": True, "reason": "", "facilitator": "test"}

    async def settle(self, **kwargs: Any) -> dict[str, Any]:
        self.settle_calls.append(kwargs)
        if self.fail:
            return {"success": False, "reason": "down"}
        return {
            "success": True,
            "transaction": "0x" + "f" * 64,
            "network": kwargs.get("network", ""),
            "payment_id": kwargs.get("payment_id", ""),
            "facilitator": "test",
            "settled_at": "2026-09-02T00:00:00+00:00",
        }


def test_handler_adopts_db_when_configured(db, monkeypatch) -> None:
    h = X402Handler()
    assert h._use_db is True
    assert h.payments == []


def test_payment_record_written_to_db(db, monkeypatch) -> None:
    h = X402Handler()

    h.router = _FakeRouter()
    import asyncio

    asyncio.get_event_loop_policy()

    async def _run() -> dict[str, Any]:
        return await h.verify_payment(
            "pay_db1", "0x" + "a" * 64, network="eip155:8453", asset="USDC", amount_usd=0.001
        )

    res = asyncio.run(_run())
    assert res["verified"] is True
    # DB has the record (source of truth)…

    assert len(ledger_store.payments_for("pay_db1")) == 1
    # …and the in-memory cache mirrors it.
    assert any(p["payment_id"] == "pay_db1" for p in h.payments)
    # JSONL audit trail also got the line.
    assert h.payments_file.exists()


def test_settle_idempotency_is_db_first_across_handlers(db) -> None:
    """A NEW handler (fresh process simulation) sees a settle from BEFORE it
    existed — the DB idempotency index is authoritative across processes."""
    import asyncio

    router = _FakeRouter()
    h1 = X402Handler()
    h1.router = router

    async def _run() -> dict[str, Any]:
        return await h1.settle_payment(
            "pay_x", "0x" + "b" * 64, network="eip155:8453", asset="USDC"
        )

    res1 = asyncio.run(_run())
    assert res1["success"] is True
    assert len(router.settle_calls) == 1

    # A brand-new handler (same DB) must see the settle WITHOUT calling the
    # facilitator again — cross-process idempotency.
    h2 = X402Handler()
    h2.router = router

    async def _run2() -> dict[str, Any]:
        return await h2.settle_payment(
            "pay_x", "0x" + "b" * 64, network="eip155:8453", asset="USDC"
        )

    res2 = asyncio.run(_run2())
    assert res2["success"] is True
    assert len(router.settle_calls) == 1  # no second facilitator roll
    assert res2["settled_at"] == res1["settled_at"]


def test_failed_settle_never_blocks_retry(db) -> None:
    router = _FakeRouter(fail=True)
    h = X402Handler()
    h.router = router

    async def _run() -> dict[str, Any]:
        return await h.settle_payment("pay_y", "0x" + "c" * 64, network="eip155:8453", asset="USDC")

    bad = asyncio.run(_run())
    assert bad["success"] is False
    # Failure is NOT indexed — a retry re-rolls the facilitator.
    router.fail = False
    good = asyncio.run(_run())
    assert good["success"] is True
    assert len(router.settle_calls) == 2
