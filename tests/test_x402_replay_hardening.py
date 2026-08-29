# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Replay-hardening tests for the x402 payment gate (release E41).

Covers the three security-critical regressions:
1. Cross-operation payment bypass: a cheap ``scrape`` payment_id replayed
   against a more expensive gated endpoint (``crawl``/``monitor``) is REJECTED.
2. Fail-closed wallet: an unconfigured/placeholder payTo never releases funds
   and is never emitted as a real ``payToAddress``.
3. Server-authoritative atomic underpayment: a payment that under-covers the
   operation's CURRENT price (atomic units) is REJECTED; overpayment allowed.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from pry.payments.x402 import (
    X402_PLACEHOLDER_WALLETS,
    X402Handler,
    wallet_configured,
)
from pry.payments.x402_middleware import X402Middleware

# ---------------------------------------------------------------------------
# is_paid() unit tests (the gate core) — cross-operation + atomic recheck
# ---------------------------------------------------------------------------

_FUTURE = (datetime.now(UTC) + timedelta(hours=1)).isoformat()


def _payment_record(
    payment_id: str,
    *,
    operation: str,
    required_amount_atomic: int,
    caller_key: str = "",
    asset: str = "USDC",
    network: str = "base",
) -> dict[str, Any]:
    return {
        "payment_id": payment_id,
        "verified": True,
        "expires_at": _FUTURE,
        "caller_key": caller_key,
        "operation": operation,
        "required_amount_atomic": required_amount_atomic,
        "asset": asset,
        "network": network,
    }


def test_replay_cheap_payment_rejected_on_expensive_operation() -> None:
    """A $0.001 'scrape' payment must NOT unlock the $0.01 'crawl' gate."""
    h = X402Handler()
    h.payments = [
        _payment_record("cheap1", operation="scrape", required_amount_atomic=1000, caller_key="ip")
    ]
    # Cross-operation replay → rejected.
    assert h.is_paid("cheap1", "ip", operation="crawl") is False
    assert h.is_paid("cheap1", "ip", operation="monitor") is False
    # Same operation is still granted (overpayment/exact allowed).
    assert h.is_paid("cheap1", "ip", operation="scrape") is True


def test_replay_cheap_payment_rejected_at_middleware_gate(monkeypatch) -> None:
    """End-to-end at the ASGI gate: a cheap payment hitting an expensive path
    gets a 402 challenge rather than being served."""
    seeded = X402Handler()
    seeded.payments = [
        _payment_record("cheap1", operation="scrape", required_amount_atomic=1000, caller_key="")
    ]
    # refresh() reloads from the JSONL file and would wipe in-memory seeds.
    seeded._load_payments = lambda: None  # type: ignore[method-assign]
    monkeypatch.setattr(
        "pry.payments.x402_middleware.enforcement.X402Handler", lambda *a, **k: seeded
    )

    a = FastAPI()

    @a.post("/v1/scrape")
    async def scrape():
        return {"ok": True}

    @a.post("/v1/crawl")
    async def crawl():
        return {"ok": True}

    a.add_middleware(X402Middleware)
    client = TestClient(a, raise_server_exceptions=False)

    # Cheap 'scrape' payment on the expensive '/v1/crawl' gate → 402 (rejected).
    r = client.post("/v1/crawl", headers={"X-Payment-ID": "cheap1"})
    assert r.status_code == 402
    assert r.headers.get("payment-required")


def test_underpayment_in_atoms_rejected_but_overpayment_allowed() -> None:
    """Paid 500 units (< current 1000 for scrape) rejected; 1500 allowed."""
    under = X402Handler()
    under.payments = [
        _payment_record("under1", operation="scrape", required_amount_atomic=500, caller_key="ip")
    ]
    assert under.is_paid("under1", "ip", operation="scrape") is False

    over = X402Handler()
    over.payments = [
        _payment_record("over1", operation="scrape", required_amount_atomic=1500, caller_key="ip")
    ]
    assert over.is_paid("over1", "ip", operation="scrape") is True


def test_gated_operation_without_stored_atomics_fails_closed() -> None:
    """Pre-hardening records (no operation/amount) can't satisfy a gated op."""
    h = X402Handler()
    h.payments = [
        {"payment_id": "old1", "verified": True, "expires_at": _FUTURE, "caller_key": "ip"}
    ]
    assert h.is_paid("old1", "ip", operation="scrape") is False
    # Legacy caller (no gate operation) keeps the old verified/unexpired contract.
    assert h.is_paid("old1", "ip") is True


# ---------------------------------------------------------------------------
# FIX 2 — fail-closed wallet: never emit / use a placeholder payTo
# ---------------------------------------------------------------------------


def test_placeholder_wallets_are_never_configured() -> None:
    assert "pry-default-wallet" in X402_PLACEHOLDER_WALLETS
    assert "0xRMI_PLATFORM_WALLET" in X402_PLACEHOLDER_WALLETS
    assert "" in X402_PLACEHOLDER_WALLETS
    assert wallet_configured("pry-default-wallet") is False
    assert wallet_configured("0xRMI_PLATFORM_WALLET") is False
    assert wallet_configured("") is False
    assert wallet_configured("0x000000000000000000000000000000000000dEaD") is True


def test_accepts_never_emit_placeholder_payto(monkeypatch) -> None:
    """The multi-asset 402 accepts must not carry a fake payToAddress."""
    from pry.payments.x402.scheme import build_multi_asset_accepts

    monkeypatch.setattr("pry.payments.x402.scheme.X402_WALLET", "pry-default-wallet")
    monkeypatch.setattr("pry.payments.x402.scheme.X402_NETWORK_WALLETS", {})
    accepts = build_multi_asset_accepts("scrape")
    assert accepts
    for acc in accepts:
        pay_to = acc.get("payToAddress", "")
        assert pay_to not in X402_PLACEHOLDER_WALLETS or pay_to == ""


def test_self_facilitator_unconfigured_wallet_is_placeholder(monkeypatch) -> None:
    """Constructing a SelfFacilitator with no real payTo yields a placeholder
    that the module treats as not-configured (fail closed)."""
    from pry.payments.x402.self_facilitator import SelfFacilitator

    monkeypatch.setattr("pry.payments.x402.self_facilitator.X402_WALLET", "")
    fac = SelfFacilitator()
    assert fac.pay_to in X402_PLACEHOLDER_WALLETS

    fac2 = SelfFacilitator(pay_to="pry-default-wallet")
    assert fac2.pay_to in X402_PLACEHOLDER_WALLETS


@pytest.mark.asyncio
async def test_self_facilitator_verify_fails_closed_with_unconfigured_wallet(
    monkeypatch,
) -> None:
    """With a REAL signed authorization and NO configured wallet, verify fails
    closed (the pay-to guard must reject it, not 'verify' it)."""
    from eth_keys.datatypes import PrivateKey

    from pry.payments.x402.self_facilitator import SelfFacilitator
    from tests.test_x402_readiness import _payment, _sign_auth

    monkeypatch.setattr("pry.payments.x402.self_facilitator.X402_WALLET", "")
    priv = PrivateKey(b"\x3a" * 32)
    auth = _sign_auth(priv)
    fac = SelfFacilitator(nonce_path=None)
    result = await fac.verify(_payment(auth))
    assert result.verified is False
    assert "not configured" in result.reason.lower() or "payto" in result.reason.lower()


def test_verify_payment_records_atomic_required_amount() -> None:
    """The verified payment record persists operation + atomic required amount
    so is_paid() can re-check the cross-operation and underpayment guards."""
    from unittest.mock import AsyncMock, MagicMock

    h = X402Handler()
    h.router = MagicMock()
    h.router.verify = AsyncMock(return_value={"verified": True, "reason": "", "facilitator": "t"})

    async def _run() -> None:
        await h.verify_payment("pid1", "0xtx", network="base", asset="USDC", operation="scrape")

    asyncio.run(_run())
    p = next(r for r in h.payments if r["payment_id"] == "pid1")
    assert p["operation"] == "scrape"
    assert p["required_amount_atomic"] == 1000  # $0.001 USDC, 6 decimals
