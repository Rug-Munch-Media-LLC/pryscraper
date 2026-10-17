"""Branch coverage for the Postgres-backed x402 ledger store."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from pry.payments.x402 import ledger_store as ledger


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("PRY_DATABASE_URL", f"sqlite:///{tmp_path}/cov.db")
    import pry.core.db as db_pkg
    import pry.core.db.session as session_mod

    monkeypatch.setattr(db_pkg, "_engine", None, raising=False)
    monkeypatch.setattr(session_mod, "_engine", None, raising=False)
    from sqlalchemy import create_engine

    from pry.core.db import models as models_mod

    engine = create_engine(f"sqlite:///{tmp_path}/cov.db")
    models_mod.Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


def test_parse_and_iso_helpers() -> None:
    assert ledger._parse_dt(None) is None
    assert ledger._parse_dt("not-a-date") is None
    assert ledger._parse_dt("2026-09-02T00:00:00") == datetime(2026, 9, 2, tzinfo=UTC)
    assert ledger._iso(None) == ""
    assert ledger._iso(datetime(2026, 1, 1)) == "2026-01-01T00:00:00+00:00"


def test_record_payment_invalid_amount_becomes_zero(db) -> None:
    from pry.core.db.models import X402PaymentRecord
    from pry.core.db.session import get_session

    ledger.record_payment({"payment_id": "pay_bad", "tx_hash": "0x1", "amount_usd": "abc"})
    with get_session() as session:
        row = session.query(X402PaymentRecord).filter_by(payment_id="pay_bad").first()
        assert row.amount_usd == 0.0


def test_settlement_duplicate_returns_first_receipt(db) -> None:
    first = {"payment_id": "p1", "tx_hash": "0xa", "success": True}
    second = {"payment_id": "p2", "tx_hash": "0xb", "success": True}
    assert ledger.record_settlement(first, "tx:base:0xa") == first
    assert ledger.record_settlement(second, "tx:base:0xa") == first
    assert ledger.settlement_by_key("tx:base:0xa") == first


def test_settlement_race_rolls_back_and_returns_existing(monkeypatch: pytest.MonkeyPatch) -> None:
    from sqlalchemy.exc import IntegrityError

    import pry.core.db.session as session_mod

    existing = {"success": True, "kept": "db"}
    state = SimpleNamespace(queries=0, rollbacks=0)

    class _Query:
        def __init__(self, row):
            self.row = row

        def filter_by(self, **_kw):
            return self

        def first(self):
            return self.row

    class _Session:
        def query(self, _model):
            state.queries += 1
            return _Query(None if state.queries == 1 else SimpleNamespace(receipt=existing))

        def add(self, _obj):
            raise IntegrityError("INSERT", {}, Exception("unique"))

        def rollback(self):
            state.rollbacks += 1

    @contextmanager
    def fake_scope():
        yield _Session()

    monkeypatch.setattr(session_mod, "session_scope", fake_scope)
    assert ledger.record_settlement({"payment_id": "p1"}, "dup") == existing
    assert state.rollbacks == 1


def test_available_false_when_probe_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    import pry.core.db.session as session_mod

    @contextmanager
    def broken_scope():
        raise RuntimeError("db down")
        yield

    monkeypatch.setattr(session_mod, "session_scope", broken_scope)
    assert ledger.available() is False


def test_iso_aware_and_non_datetime() -> None:
    assert ledger._iso(datetime(2026, 1, 1, tzinfo=UTC)) == "2026-01-01T00:00:00+00:00"
    assert ledger._iso("2026-01-01") == "2026-01-01"


def test_settlement_race_reraises_when_row_vanishes(monkeypatch: pytest.MonkeyPatch) -> None:
    from sqlalchemy.exc import IntegrityError

    import pry.core.db.session as session_mod

    class _Query:
        def filter_by(self, **_kw):
            return self

        def first(self):
            return None

    class _Session:
        def query(self, _model):
            return _Query()

        def add(self, _obj):
            raise IntegrityError("INSERT", {}, Exception("unique"))

        def rollback(self):
            return None

    @contextmanager
    def fake_scope():
        yield _Session()

    monkeypatch.setattr(session_mod, "session_scope", fake_scope)
    with pytest.raises(IntegrityError):
        ledger.record_settlement({"payment_id": "p1"}, "lost")
