"""Erasure matrix, partial status, and the scrape audit trail (GDPR wave)."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

import importlib
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

SUBJECT = "subject@example.com"


@pytest.fixture
def erasure_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Temp data root + temp SQLite with the real schema, for erasure tests."""
    monkeypatch.setenv("PRY_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PRY_DATABASE_URL", f"sqlite:///{tmp_path}/test.db")
    import pry.core.db as db
    import pry.core.paths as paths

    importlib.reload(paths)
    importlib.reload(db)
    db._engine = None
    db._SessionLocal = None
    from pry.core.db.models import Base
    from pry.core.db.session import get_engine

    Base.metadata.create_all(get_engine())
    for name in (
        "pry.compliance._deletion_scan",
        "pry.compliance.deletion_logic",
        "pry.compliance.deletion",
        "pry.compliance.gdpr",
    ):
        importlib.reload(importlib.import_module(name))
    yield tmp_path
    db._engine = None
    db._SessionLocal = None


def _session():
    from pry.core.db.session import session_scope

    return session_scope()


def _add_user(session) -> None:
    from pry.core.db.models import User

    session.add(User(user_id=SUBJECT, email=SUBJECT, password_hash="x"))
    session.flush()


def test_erasure_deletes_usage_row(erasure_env: Path) -> None:
    from pry.compliance.deletion_logic import process_deletion
    from pry.core.db.models import Usage

    with _session() as session:
        _add_user(session)
        session.add(Usage(user_id=SUBJECT, operation="scrape", endpoint="https://x.test/a"))
    result = process_deletion(SUBJECT)
    with _session() as session:
        assert session.query(Usage).filter(Usage.user_id == SUBJECT).count() == 0
    entry = next(e for e in result["stores"] if e["store"] == "usage")
    assert entry["action"] == "deleted"
    assert entry["affected"] == 1


def test_ledger_survives_with_empty_reference(erasure_env: Path) -> None:
    from pry.compliance.deletion_logic import process_deletion
    from pry.core.db.models import LedgerEntry

    with _session() as session:
        _add_user(session)
        session.add(
            LedgerEntry(
                user_id=SUBJECT,
                delta_usd=10.0,
                reason="deposit",
                reference="tx-abc123",
                balance_after=10.0,
            )
        )
    result = process_deletion(SUBJECT)
    with _session() as session:
        row = session.query(LedgerEntry).filter(LedgerEntry.user_id == SUBJECT).one()
        assert row.delta_usd == 10.0
        assert row.reference == "", "financial row kept but its reference must be cleared"
    entry = next(e for e in result["stores"] if e["store"] == "ledger_entries")
    assert entry["action"] == "pseudonymised"
    assert "17(3)(b)" in entry["basis"]


def test_status_partial_when_a_store_is_unreadable(erasure_env: Path) -> None:
    from pry.compliance.deletion_logic import process_deletion

    x402 = erasure_env / "x402"
    x402.mkdir()
    (x402 / "payments.jsonl").write_text('{"caller_key": "subject@example.com"}\n{not json\n')
    result = process_deletion(SUBJECT)
    assert result["status"] == "partial"
    assert result["unreadable_records"] == 1
    entry = next(e for e in result["stores"] if e["store"] == "x402/jsonl")
    assert entry["state"] == "ok"
    assert entry["affected"] == 1


def _post_blocked(url: str):
    from pry.api.api import app

    with patch(
        "pry.payments.x402_middleware.X402Middleware.__call__",
        lambda self, scope, receive, send: self.app(scope, receive, send),
    ):
        return TestClient(app).post("/v1/scrape", json={"url": url})


def _audit_rows():
    from pry.core.db.models import AuditEvent

    with _session() as session:
        return session.query(AuditEvent).filter(AuditEvent.event_type == "scrape_request").all()


def test_denied_scrape_writes_exactly_one_audit_row(erasure_env: Path) -> None:
    from pry.api.routers.integrations.gdpr import _DDL
    from pry.core.db.models import AuditEvent  # noqa: F401

    with _session() as session:
        session.execute(text(_DDL))
        session.execute(
            text("INSERT INTO domain_blocks (domain, reason, created_at) VALUES (:d, :r, '')"),
            {"d": "blocked.example", "r": "test"},
        )
    response = _post_blocked("https://blocked.example/secret?token=abc")
    assert response.status_code == 451
    rows = _audit_rows()
    assert len(rows) == 1
    assert rows[0].detail["host"] == "blocked.example"
    assert rows[0].path == "/v1/scrape"
    assert "secret" not in str(rows[0].path)
    assert "token" not in str(rows[0].detail)
