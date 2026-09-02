# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Email verification gates the hosting confirm step (audit item #4).

The portal is keyed by user_email — signup with an unverified email was an
account-takeover-adjacent vector. The confirm step now refuses while the
signup email is unverified (fail closed); these tests prove the gate.
"""

from __future__ import annotations

from typing import Any

import pytest

import pry.commerce.hosting as hosting_mod
from pry.commerce.hosting import (
    confirm_hosting_payment_sync,
    create_hosting_signup,
    get_hosting_invoice,
    verify_hosting_email,
)
from pry.payments.x402.self_facilitator import VerifyResult

_REAL_WALLET = "0x00000000000000000000000000000000000ABCDE"


class _FakeFacilitator:
    def __init__(self, result: VerifyResult) -> None:
        self.result = result

    async def verify(self, payment: dict[str, Any]) -> VerifyResult:
        return self.result

    async def settle(self, payment: dict[str, Any]) -> str | None:
        return "0x" + "f" * 64


def _verified_result() -> VerifyResult:
    return VerifyResult(
        verified=True,
        reason="",
        signer="0xRecoveredSigner0000000000000000000000000000",
        amount_atomic=49_000_000,
        asset="USDC",
        network="eip155:8453",
    )


@pytest.fixture
def db(tmp_path, monkeypatch):
    """Isolated SQLite DB per test (same pattern as test_hosting.py)."""
    monkeypatch.setenv("PRY_DATABASE_URL", f"sqlite:///{tmp_path}/email-verify.db")
    import pry.core.db as db_pkg
    import pry.core.db.session as session_mod

    monkeypatch.setattr(db_pkg, "_engine", None, raising=False)
    monkeypatch.setattr(session_mod, "_engine", None, raising=False)

    from sqlalchemy import create_engine

    from pry.core.db import models as models_mod

    engine = create_engine(f"sqlite:///{tmp_path}/email-verify.db")
    models_mod.Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture(autouse=True)
def _wallet_and_gate(monkeypatch):
    """Real treasury wallet + email gate ENABLED (no escape hatch here)."""
    monkeypatch.delenv("PRY_HOSTING_SKIP_EMAIL_VERIFY", raising=False)
    monkeypatch.setattr(hosting_mod, "X402_NETWORK_WALLETS", {"eip155:8453": _REAL_WALLET})
    monkeypatch.setattr(hosting_mod, "X402_WALLET", _REAL_WALLET)


def _signup(db) -> dict[str, Any]:
    """Create a signup invoice and return the CREATE response.

    The 6-char code is exposed on the create response ONLY when the mail
    backend is unconfigured (dev fallback — the verification email would
    otherwise carry it). Tests run with mail unconfigured, so it's present.
    """
    return create_hosting_signup("verify-me@example.com", "pro")


def test_signup_starts_unverified_with_code(db) -> None:
    invoice = _signup(db)
    stored = get_hosting_invoice(invoice["invoice_id"])
    assert stored["email_verified"] is False
    # The code is exposed on the CREATE response (dev fallback) — the public
    # invoice dict deliberately omits it (never leak via portal/checkout reads).
    assert len(invoice["verification_code"]) == 6
    assert "verification_code" not in stored


def test_verify_wrong_code_stays_unverified(db) -> None:
    invoice = _signup(db)
    result = verify_hosting_email(invoice["invoice_id"], "000000")
    assert result["verified"] is False
    assert get_hosting_invoice(invoice["invoice_id"])["email_verified"] is False


def test_verify_right_code_marks_verified(db) -> None:
    invoice = _signup(db)
    code = invoice["verification_code"]
    assert code, "dev fallback must expose the code when mail is unconfigured"
    result = verify_hosting_email(invoice["invoice_id"], code)
    assert result["verified"] is True
    assert get_hosting_invoice(invoice["invoice_id"])["email_verified"] is True


def test_confirm_refused_while_unverified(db, monkeypatch) -> None:
    monkeypatch.setattr(
        hosting_mod, "_get_self_facilitator", lambda: _FakeFacilitator(_verified_result())
    )
    invoice = _signup(db)
    result = confirm_hosting_payment_sync(invoice["invoice_id"], "0x" + "a" * 8)
    assert result["paid"] is False
    assert "email not verified" in str(result.get("reason", ""))
    stored = get_hosting_invoice(invoice["invoice_id"])
    assert stored["status"] != "paid"
    assert stored["instance_id"] == ""


def test_confirm_proceeds_after_verification(db, monkeypatch) -> None:
    monkeypatch.setattr(
        hosting_mod, "_get_self_facilitator", lambda: _FakeFacilitator(_verified_result())
    )
    invoice = _signup(db)
    code = invoice["verification_code"]
    verify_hosting_email(invoice["invoice_id"], code)
    result = confirm_hosting_payment_sync(invoice["invoice_id"], "0x" + "a" * 8)
    assert result["paid"] is True
    assert get_hosting_invoice(invoice["invoice_id"])["status"] == "paid"


def test_unknown_invoice_404(db) -> None:
    with pytest.raises(ValueError, match="unknown hosting invoice"):
        verify_hosting_email("host_nope", "123456")
