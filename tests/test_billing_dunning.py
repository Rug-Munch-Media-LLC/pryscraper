"""Billing dunning timeline and migration 0012 backfill."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine

from pry.commerce.billing import dunning
from pry.commerce.billing.subscription_state import (
    _INVOICES,
    _SUBSCRIPTIONS,
    reset_subscription_state,
)
from tests.billing_support import seed_subscription_invoice

BASE = datetime(2026, 10, 1, tzinfo=UTC)


def test_dunning_fires_only_on_due_days() -> None:
    reset_subscription_state()
    seed_subscription_invoice("inv_dun", "sk_dun", BASE)
    assert dunning.run_dunning(BASE)["attempts_fired"] == 0
    assert dunning.run_dunning(BASE + timedelta(days=1))["attempts_fired"] == 1
    assert dunning.run_dunning(BASE + timedelta(days=1))["attempts_fired"] == 0
    assert dunning.run_dunning(BASE + timedelta(days=4))["attempts_fired"] == 1


def _dun_through_day7():
    """Drive one invoice to the day-7 suspension and return its record."""
    reset_subscription_state()
    seed_subscription_invoice("inv_dun", "sk_dun", BASE)
    for offset in (0, 1, 1, 4):
        dunning.run_dunning(BASE + timedelta(days=offset))
    day7 = dunning.run_dunning(BASE + timedelta(days=7))
    return day7, _INVOICES["inv_dun"]


def test_dunning_suspends_after_three_attempts() -> None:
    day7, record = _dun_through_day7()
    assert day7["attempts_fired"] == 1
    assert day7["suspended"] == 1
    assert record["status"] == "suspended"
    assert record["dunning"]["attempts"] == [1, 2, 3]
    assert [e["outcome"] for e in record["dunning"]["events"]] == ["retry", "retry", "suspend"]


def test_dunning_downgrades_subscription_and_stops() -> None:
    _dun_through_day7()
    assert _SUBSCRIPTIONS["sk_dun"]["tier"] == "free"
    assert dunning.run_dunning(BASE + timedelta(days=30))["attempts_fired"] == 0


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
