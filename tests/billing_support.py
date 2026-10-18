"""Shared DB fixture and row builders for the billing lifecycle tests."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine

from pry.commerce.billing.subscription_state import _INVOICES, _SUBSCRIPTIONS
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


def create_invoice(
    invoice_id: str, user_id: str, amount: str = "100", status: str = "paid"
) -> None:
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


def seed_subscription_invoice(invoice_id: str, api_key: str, due: datetime) -> None:
    _INVOICES[invoice_id] = {
        "invoice_id": invoice_id,
        "api_key": api_key,
        "status": "pending",
        "expires_at": due.isoformat(),
    }
    _SUBSCRIPTIONS[api_key] = {"tier": "pro", "expires_at": (due + timedelta(days=30)).isoformat()}
