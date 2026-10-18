# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Shared fixtures and doubles for the cloud-hosting test suite.

Covers:
- hosting plan catalog matches the billing tiers (pro $49 / team $199 / enterprise custom)
- signup invoice returns a 402 manifest quoting a real treasury payTo
  (and fails closed with no placeholder payTo when the wallet is unconfigured)
- confirmed payment provisions a HostedInstance + mints an API key + credits the ledger
- underpayment is rejected (never provisioned, never credited)
- instance lifecycle: get / list / suspend / cancel / renew (renewal extends expiry)
- route-level: signup manifest, confirm, instance list/detail scoped by API key
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

import pry.commerce.hosting as hosting_mod
from pry.api.api import app
from pry.commerce.hosting import (
    confirm_hosting_payment_sync,
    create_hosting_signup,
    reset_hosting_state,
)
from pry.payments.x402.self_facilitator import VerifyResult

_REAL_WALLET = "0x00000000000000000000000000000000000ABCDE"


class _FakeFacilitator:
    """Scripted SelfFacilitator double for hosting verify + settle."""

    def __init__(self, result: VerifyResult, *, settle_tx: str | None = "0x" + "f" * 64) -> None:
        self.result = result
        self.settle_tx = settle_tx
        self.verified_payments: list[dict[str, Any]] = []
        self.settled_payments: list[dict[str, Any]] = []

    async def verify(self, payment: dict[str, Any]) -> VerifyResult:
        self.verified_payments.append(payment)
        return self.result

    async def settle(self, payment: dict[str, Any]) -> str | None:
        self.settled_payments.append(payment)
        return self.settle_tx


def _verified_result() -> VerifyResult:
    return VerifyResult(
        verified=True,
        reason="",
        signer="0xRecoveredSigner0000000000000000000000000000",
        amount_atomic=49_000_000,
        asset="USDC",
        network="eip155:8453",
    )


def _unverified_result() -> VerifyResult:
    return VerifyResult(
        verified=False,
        reason="authorization amount below price",
        signer="",
        amount_atomic=100_000,
        asset="USDC",
        network="eip155:8453",
    )


@pytest.fixture
def db(tmp_path, monkeypatch):
    """Isolated SQLite DB for instances + ledger (same pattern as test_billing_packs)."""
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


@pytest.fixture(autouse=True)
def _clean_hosting_state(tmp_path, monkeypatch):
    """Isolated per-test DB + reset invoice registry + real treasury wallet.

    Invoices persist in the hosting_invoices table — tests get a fresh
    SQLite DB per test so they never touch the dev database.
    """
    monkeypatch.setenv("PRY_DATABASE_URL", f"sqlite:///{tmp_path}/hosting-test.db")
    import pry.core.db as db_pkg
    import pry.core.db.db_engine as db_engine_mod

    monkeypatch.setattr(db_pkg, "_engine", None, raising=False)
    monkeypatch.setattr(db_engine_mod, "_engine", None, raising=False)
    monkeypatch.setattr(db_engine_mod, "_SessionLocal", None, raising=False)
    reset_hosting_state()
    # get_engine() no longer creates the schema (Alembic owns it), so a test
    # that relies on the autouse DB must build the tables itself.
    from pry.core.db import Base

    Base.metadata.create_all(db_pkg.get_engine())
    monkeypatch.setattr(hosting_mod, "X402_NETWORK_WALLETS", {"eip155:8453": _REAL_WALLET})
    monkeypatch.setattr(hosting_mod, "X402_WALLET", _REAL_WALLET)
    # Test escape hatch: legacy flows confirm without verifying the email
    # first (the email gate itself is covered in test_hosting_email_verification).
    monkeypatch.setenv("PRY_HOSTING_SKIP_EMAIL_VERIFY", "1")
    yield
    reset_hosting_state()


def _provision(
    db, monkeypatch, email: str = "life@example.com", tier: str = "pro"
) -> dict[str, Any]:
    monkeypatch.setattr(
        hosting_mod, "_get_self_facilitator", lambda: _FakeFacilitator(_verified_result())
    )
    invoice = create_hosting_signup(email, tier)
    return confirm_hosting_payment_sync(invoice["invoice_id"], "0x" + "a" * 8)


@pytest.fixture
def client() -> TestClient:
    # No `with`: skip the lifespan so the strict x402 route-classification
    # audit is not triggered here (same pattern as test_subscription_route).
    return TestClient(app)
