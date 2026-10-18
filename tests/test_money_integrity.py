"""Money integrity: Decimal columns, ledger idempotency, migration chain.

Covers the P1 fixes:
- money columns are NUMERIC(18,6) and arithmetic round-trips exactly
- a duplicate ``(user_id, reason, reference)`` ledger row is impossible
- crediting the same reference twice is a no-op (one row, one delta)
- two concurrent credits of one reference also yield one row, one delta
- ``alembic upgrade head`` runs on a fresh SQLite database
"""

from __future__ import annotations

import os
import threading
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import Numeric, create_engine, inspect
from sqlalchemy.exc import IntegrityError

from pry.commerce import billing_service
from pry.core.db import models as models_mod

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isolated SQLite file shared by the fixture engine and billing_service."""
    db_path = tmp_path / "money.db"
    monkeypatch.setenv("PRY_DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("PRY_ALEMBIC_AUTO", "0")

    import pry.core.db as db_pkg
    import pry.core.db.session as session_mod

    monkeypatch.setattr(db_pkg, "_engine", None, raising=False)
    monkeypatch.setattr(session_mod, "_engine", None, raising=False)
    monkeypatch.setattr(db_pkg, "_SessionLocal", None, raising=False)
    monkeypatch.setattr(session_mod, "_SessionLocal", None, raising=False)

    engine = create_engine(f"sqlite:///{db_path}")
    models_mod.Base.metadata.create_all(engine)
    engine.dispose()
    return db_path


def _ledger_rows(user_id: str) -> list:
    with billing_service.get_session() as session:
        return (
            session.query(models_mod.LedgerEntry)
            .filter_by(user_id=user_id)
            .order_by(models_mod.LedgerEntry.id)
            .all()
        )


def test_money_columns_are_numeric_18_6() -> None:
    table = models_mod.LedgerEntry.__table__
    for name in ("delta_usd", "balance_after"):
        col_type = table.c[name].type
        assert isinstance(col_type, Numeric)
        assert (col_type.precision, col_type.scale) == (18, 6)
    assert isinstance(models_mod.Balance.__table__.c.balance_usd.type, Numeric)
    assert isinstance(models_mod.HostingInvoice.__table__.c.amount_usd.type, Numeric)


def test_decimal_round_trip_is_exact(db: Path) -> None:
    """0.1 + 0.2 must be 0.30, not 0.30000000000000004."""
    billing_service.credit("u-dec", "0.1", reason="deposit", reference="r1")
    billing_service.credit("u-dec", "0.2", reason="deposit", reference="r2")

    balance = billing_service.get_balance("u-dec")
    assert balance["balance_usd"] == 0.3

    rows = _ledger_rows("u-dec")
    assert [Decimal(str(r.delta_usd)) for r in rows] == [Decimal("0.1"), Decimal("0.2")]
    assert Decimal(str(rows[-1].balance_after)) == Decimal("0.3")


def test_duplicate_reference_rejected_by_database(db: Path) -> None:
    billing_service.credit("u-dup", "1", reason="deposit", reference="same")
    with billing_service.get_session() as session:
        session.add(
            models_mod.LedgerEntry(
                user_id="u-dup",
                delta_usd=Decimal("1"),
                reason="deposit",
                reference="same",
                balance_after=Decimal("2"),
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()


def test_second_credit_with_same_reference_is_a_noop(db: Path) -> None:
    first = billing_service.credit("u-idem", "5", reason="deposit", reference="tx-1")
    second = billing_service.credit("u-idem", "5", reason="deposit", reference="tx-1")

    assert first["balance_usd"] == 5.0
    assert second["balance_usd"] == 5.0
    assert second.get("duplicate") is True
    assert len(_ledger_rows("u-idem")) == 1
    assert billing_service.get_balance("u-idem")["balance_usd"] == 5.0


def test_blank_reference_stays_repeatable(db: Path) -> None:
    """Usage debits have no idempotency key and must not be collapsed."""
    billing_service.credit("u-blank", "2", reason="deposit", reference="seed")
    billing_service.drawdown("u-blank", "0.5", reference="")
    billing_service.drawdown("u-blank", "0.5", reference="")
    assert len(_ledger_rows("u-blank")) == 3


def test_concurrent_credits_of_one_reference_apply_once(db: Path) -> None:
    """Two writers, one reference: one ledger row and one balance delta."""
    from pry.core.api_keys_service import ensure_user

    # ensure_user() itself races on users.email; that is a separate defect.
    # Pre-create so this test isolates the ledger idempotency gate.
    ensure_user("u-race")
    barrier = threading.Barrier(2)
    errors: list[BaseException] = []

    def worker() -> None:
        try:
            barrier.wait(timeout=10)
            billing_service.credit("u-race", "3", reason="deposit", reference="tx-race")
        except BaseException as exc:  # noqa: BLE001 — surfaced below
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
        assert not t.is_alive(), "credit thread hung (sqlite lock?)"

    assert not errors, errors
    rows = _ledger_rows("u-race")
    assert len(rows) == 1
    assert billing_service.get_balance("u-race")["balance_usd"] == 3.0


def test_alembic_upgrade_head_on_sqlite(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The whole chain, including 0011, applies to a fresh SQLite DB."""
    from alembic.config import Config

    from alembic import command

    monkeypatch.chdir(REPO_ROOT)
    monkeypatch.setenv("PRY_DATABASE_URL", f"sqlite:///{tmp_path}/mig.db")
    monkeypatch.setenv("PRY_ALEMBIC_AUTO", "0")

    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO_ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{tmp_path}/mig.db")
    command.upgrade(cfg, "head")

    engine = create_engine(f"sqlite:///{tmp_path}/mig.db")
    insp = inspect(engine)
    indexes = {idx["name"] for idx in insp.get_indexes("ledger_entries")}
    assert "ux_ledger_user_reason_reference" in indexes
    assert "ix_ledger_entries_reference" in indexes
    from sqlalchemy import text

    with engine.connect() as conn:
        version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
    assert version == "0012"
    engine.dispose()


def test_0011_downgrade_refuses_without_ack(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from alembic.config import Config

    from alembic import command

    monkeypatch.chdir(REPO_ROOT)
    monkeypatch.setenv("PRY_DATABASE_URL", f"sqlite:///{tmp_path}/down.db")
    monkeypatch.setenv("PRY_ALEMBIC_AUTO", "0")
    monkeypatch.delenv("PRY_ALLOW_LOSSY_DOWNGRADE", raising=False)

    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO_ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{tmp_path}/down.db")
    command.upgrade(cfg, "head")
    # 0012 has its own refusal guard; acknowledge it to reach 0011's guard.
    monkeypatch.setenv("PRY_ALLOW_BILLING_DOWNGRADE", "1")
    command.downgrade(cfg, "0011")
    with pytest.raises(RuntimeError, match="lossy"):
        command.downgrade(cfg, "0010")


def test_env_compare_type_is_on() -> None:
    env_text = (REPO_ROOT / "alembic" / "env.py").read_text()
    assert '"compare_type": True' in env_text
    assert os.path.exists(REPO_ROOT / "alembic" / "versions" / "0011_money_integrity.py")
