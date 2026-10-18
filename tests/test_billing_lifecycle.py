"""Billing lifecycle: invoice numbering, refunds, dunning, tax, migration 0012."""

import threading
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine

from pry.commerce.billing import dunning, invoices, refunds
from pry.commerce.billing.subscription_state import (
    _INVOICES,
    _SUBSCRIPTIONS,
    reset_subscription_state,
)
from pry.core.db import models as models_mod


@pytest.fixture
def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db_path = tmp_path / "lifecycle.db"
    monkeypatch.setenv("PRY_DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("PRY_ALEMBIC_AUTO", "0")
    import pry.core.db as db_pkg
    import pry.core.db.session as session_mod

    for mod in (db_pkg, session_mod):
        monkeypatch.setattr(mod, "_engine", None, raising=False)
        monkeypatch.setattr(mod, "_SessionLocal", None, raising=False)
    engine = create_engine(f"sqlite:///{db_path}")
    models_mod.Base.metadata.create_all(engine)
    engine.dispose()
    return db_path


def _invoice(invoice_id: str, user_id: str, amount: str = "100", status: str = "paid") -> None:
    from pry.core.api_keys_service import ensure_user
    from pry.core.db.session import session_scope

    ensure_user(user_id)
    with session_scope() as session:
        session.add(
            models_mod.HostingInvoice(
                invoice_id=invoice_id,
                kind="signup",
                plan_tier="pro",
                user_email=f"{user_id}@example.test",
                user_id=user_id,
                payment_method="x402",
                amount_usd=Decimal(amount),
                status=status,
            )
        )


def test_allocate_number_is_sequential_and_formatted(db: Path) -> None:
    first = invoices.allocate_invoice_number("202610")
    second = invoices.allocate_invoice_number("202610")
    assert (first, second) == ("INV-202610-000001", "INV-202610-000002")
    assert invoices.allocate_invoice_number("202611") == "INV-202611-000001"


def test_concurrent_allocation_yields_distinct_numbers(db: Path) -> None:
    results: list[str] = []
    errors: list[BaseException] = []
    barrier = threading.Barrier(4)

    def worker() -> None:
        try:
            barrier.wait(timeout=10)
            results.append(invoices.allocate_invoice_number("202612"))
        except BaseException as exc:  # noqa: BLE001 — surfaced below
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert not errors, errors
    assert len(set(results)) == 4, results


def test_assign_number_to_stored_invoice_is_idempotent(db: Path) -> None:
    _invoice("inv_a", "u_num")
    first = invoices.assign_invoice_number("inv_a")
    assert (first.startswith("INV-"), first.endswith("000001")) == (True, True)
    assert invoices.assign_invoice_number("inv_a") == first


def test_refund_rules_and_idempotency(db: Path) -> None:
    from pry.core.db.session import get_session

    _invoice("inv_over", "u_ref", amount="50")
    with pytest.raises(refunds.RefundError, match="exceeds paid"):
        refunds.refund_invoice("inv_over", "50.01", "over")

    _invoice("inv_part", "u_ref2", amount="100")
    first = refunds.refund_invoice("inv_part", "40", "goodwill")
    assert first["status"] == "partially_refunded"
    assert first["duplicate"] is False
    assert Decimal(str(first["refunded_amount"])) == Decimal("40")

    second = refunds.refund_invoice("inv_part", "40", "goodwill")
    assert second["duplicate"] is True
    assert second["refunded_amount"] == first["refunded_amount"]

    with get_session() as session:
        rows = session.query(models_mod.LedgerEntry).filter_by(reference="refund:inv_part").all()
        assert len(rows) == 1
        assert Decimal(str(rows[0].delta_usd)) == Decimal("-40")

    _invoice("inv_full", "u_ref3", amount="100")
    assert refunds.refund_invoice("inv_full", "100", "duplicate")["status"] == "refunded"


def _sub_invoice(invoice_id: str, api_key: str, due: datetime) -> None:
    _INVOICES[invoice_id] = {
        "invoice_id": invoice_id,
        "api_key": api_key,
        "status": "pending",
        "expires_at": due.isoformat(),
    }
    _SUBSCRIPTIONS[api_key] = {"tier": "pro", "expires_at": (due + timedelta(days=30)).isoformat()}


def test_dunning_timeline_and_idempotency() -> None:
    reset_subscription_state()
    base = datetime(2026, 10, 1, tzinfo=UTC)
    _sub_invoice("inv_dun", "sk_dun", base)

    assert dunning.run_dunning(base)["attempts_fired"] == 0
    assert dunning.run_dunning(base + timedelta(days=1))["attempts_fired"] == 1
    assert dunning.run_dunning(base + timedelta(days=1))["attempts_fired"] == 0
    assert dunning.run_dunning(base + timedelta(days=4))["attempts_fired"] == 1
    day7 = dunning.run_dunning(base + timedelta(days=7))
    assert day7["attempts_fired"] == 1
    assert day7["suspended"] == 1

    record = _INVOICES["inv_dun"]
    assert record["status"] == "suspended"
    assert record["dunning"]["attempts"] == [1, 2, 3]
    assert [e["outcome"] for e in record["dunning"]["events"]] == ["retry", "retry", "suspend"]
    assert _SUBSCRIPTIONS["sk_dun"]["tier"] == "free"
    assert dunning.run_dunning(base + timedelta(days=30))["attempts_fired"] == 0


def test_tax_decimal_math() -> None:
    tax = invoices.compute_tax("100.10", "0.20", "de")
    assert tax["tax_amount"] == Decimal("20.020000")
    assert tax["total_usd"] == Decimal("120.120000")
    assert tax["tax_country"] == "DE"
    assert isinstance(tax["tax_amount"], Decimal)
    zero = invoices.compute_tax("99.99", "0.20", "IE", reverse_charge=True)
    assert (zero["tax_amount"], zero["total_usd"]) == (0, Decimal("99.990000"))
    with pytest.raises(ValueError, match="immutable"):
        invoices.apply_tax({"amount_usd": 10, "status": "paid"}, "0.2")


def test_0012_backfills_numbers_and_is_refusal_safe(tmp_path: Path, monkeypatch) -> None:
    from alembic.config import Config

    from alembic import command

    repo = Path(__file__).resolve().parents[1]
    monkeypatch.chdir(repo)
    url = f"sqlite:///{tmp_path}/mig.db"
    cfg = Config(str(repo / "alembic.ini"))
    cfg.set_main_option("script_location", str(repo / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    monkeypatch.setenv("PRY_DATABASE_URL", url)
    monkeypatch.setenv("PRY_ALEMBIC_AUTO", "0")

    command.upgrade(cfg, "0011")
    engine = create_engine(url)
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "INSERT INTO hosting_invoices (invoice_id, kind, plan_tier, user_email, user_id,"
            " payment_method, amount_usd, amount_atomic, chain, pay_to, asset, status,"
            " created_at, updated_at) VALUES ('inv_old', 'signup', 'pro', 'o@x.test', 'u_old',"
            " 'x402', 10, '0', '', '', 'USDC', 'paid', '2026-09-15 10:00:00',"
            " '2026-09-15 10:00:00')"
        )
    engine.dispose()

    command.upgrade(cfg, "head")
    engine = create_engine(url)
    with engine.connect() as conn:
        row = conn.exec_driver_sql(
            "SELECT invoice_number, tax_amount FROM hosting_invoices WHERE invoice_id='inv_old'"
        ).one()
        version = conn.exec_driver_sql("SELECT version_num FROM alembic_version").scalar()
    assert (version, row[0], Decimal(str(row[1]))) == ("0012", "INV-202609-000001", 0)
    engine.dispose()

    monkeypatch.delenv("PRY_ALLOW_BILLING_DOWNGRADE", raising=False)
    with pytest.raises(RuntimeError, match="human-readable"):
        command.downgrade(cfg, "0011")
