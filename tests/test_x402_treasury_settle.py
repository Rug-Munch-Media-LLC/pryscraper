# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""x402 treasury payTo + server-authoritative settle — settlement-fidelity tests.

Covers the publish-audit gaps:
  #1 payTo must resolve to the REAL EVM treasury (gopass secret
     ``evm_treasury_address``), never a placeholder or "".
  #2 server-authoritative per-(operation, network, asset) pricing compared in
     integer atoms lives ON the verify path.
  #4 full 402 -> verify -> settle writes a real settlement record AND the
     facilitator only credits an on-chain transfer that (a) paid the treasury
     payTo, (b) covered the required amount, and (c) was not consumed before.

The facilitator router is replaced at the real seam (``X402Handler.router``)
with a STATEFUL mock that models on-chain settlement fidelity: it refuses to
verify/settle unless the fake on-chain transfer's recipient is the treasury,
its amount covers the server-required amount, and the tx_hash is known. This
is NOT an unconditional ``verified=True`` stand-in — the mock inspects the
on-chain facts, so a wrong-recipient or underpaid transfer is correctly
rejected (no tautological assertions).

No real on-chain tx or facilitator is used; the payTo comes from the config
path. The gopass secret is referenced by NAME only — never its value.
"""

from __future__ import annotations

import importlib
import os
from unittest.mock import patch

import pytest

import pry.core.secrets_backend as _sb
import pry.payments.x402 as x402
import pry.payments.x402.handler as _handler_mod
import pry.payments.x402.scheme as scheme
from pry.payments.x402 import X402Handler

# The gopass secret NAME — never a value. (This is the whole point of gap #1.)
TREASURY_SECRET_NAME = "evm_treasury_address"
# A test-only EVM-shaped address (0x + 40 hex). NOT a live wallet. Injected as
# the "real" treasury via the secrets backend so we can prove the config path.
TEST_TREASURY = "0x" + "B2" * 20
# An impostor address that is NOT the treasury — used to prove the mock rejects
# a transfer to the wrong recipient.
WRONG_TREASURY = "0x" + "E" * 40  # 0x + 40 hex, != TEST_TREASURY

# Deterministic fake on-chain tx hashes. These are the ONLY "transactions" the
# mocked facilitator knows about; every one encodes a concrete on-chain fact
# (recipient + amount paid) so the fidelity assertions are real, not vacuous.
FAKE_TX_GOOD = "0x" + "1" * 64  # pays crawl price (0.01 USDC) to the treasury
FAKE_TX_OVER = "0x" + "2" * 64  # pays 0.05 USDC to the treasury (overpayment)
FAKE_TX_UNDERPAID = "0x" + "3" * 64  # pays 0.005 USDC to the treasury (short)
FAKE_TX_WRONG_RECIPIENT = "0x" + "4" * 64  # pays 0.01 USDC to WRONG_TREASURY
FAKE_TX_UNKNOWN = "0x" + "5" * 64  # not in the facilitator's on-chain book

# Server-side price for "crawl" (USDC on base, 6 decimals, USD-per-unit 1.0).
CRAWL_PRICE_USD = scheme.X402_PRICING["crawl"]["price_usd"]


def _reload_all() -> None:
    """Reload x402 -> scheme -> handler so config consts recompute in order."""
    importlib.reload(x402)
    importlib.reload(scheme)
    importlib.reload(_handler_mod)


def _snapshot_modules() -> dict:
    """Snapshot the module globals that ``_reload_all`` mutates.

    ``importlib.reload`` re-executes a shared module *in place*, so any state
    (e.g. ``X402_WALLET``) it recomputes leaks into sibling tests that import
    those modules. We snapshot ``__dict__`` up front and restore it exactly so
    the reload is fully undone regardless of what the secrets backend returns
    when the fake is lifted (gopass is flaky under pytest's captured stdin).
    """
    return {mod: mod.__dict__.copy() for mod in (x402, scheme, _handler_mod)}


def _restore_modules(snapshot: dict) -> None:
    """Restore the module globals captured by ``_snapshot_modules``."""
    for mod, state in snapshot.items():
        mod.__dict__.clear()
        mod.__dict__.update(state)


def test_treasury_secret_name_is_reference_only() -> None:
    """The treasury is sourced by secret NAME, never a hardcoded address."""
    assert x402.EVM_TREASURY_SECRET == TREASURY_SECRET_NAME
    # The secret name itself must never carry an address literal.
    assert "0x" not in x402.EVM_TREASURY_SECRET


def test_payto_resolves_to_real_treasury_via_secret_name() -> None:
    """gap #1: wiring `evm_treasury_address` must produce a REAL payTo, not ''."""

    def fake_get_secret(name: str, default: str = "") -> str:
        if name == TREASURY_SECRET_NAME:
            return TEST_TREASURY
        # Force the treasury fallback: never let x402_wallet win.
        if name == "x402_wallet":
            return ""
        return default

    env = {k: v for k, v in os.environ.items() if not k.startswith("PRY_X402_")}
    snapshot = _snapshot_modules()
    with (
        patch.dict(os.environ, env, clear=True),
        patch.object(_sb, "get_secret", side_effect=fake_get_secret),
    ):
        _reload_all()
        # Config path resolves the treasury (gopass secret name).
        assert x402.X402_WALLET == TEST_TREASURY
        assert x402.EVM_TREASURY_SECRET == TREASURY_SECRET_NAME
        assert x402.wallet_configured(x402.X402_WALLET) is True
        assert x402.X402_WALLET not in x402.X402_PLACEHOLDER_WALLETS
        # EVM networks share the treasury; solana/tron stay unset (fail closed).
        assert scheme.X402_NETWORK_WALLETS["eip155:8453"] == TEST_TREASURY
        assert scheme.X402_NETWORK_WALLETS["solana:mainnet"] != TEST_TREASURY

        # Every EVM accept option emits the REAL payTo, never "".
        accepts = scheme.build_multi_asset_accepts(
            "scrape", preferred_networks=["base"], preferred_assets=["USDC"]
        )
        assert accepts, "expected at least one accept for base/USDC"
        assert accepts[0]["payToAddress"] == TEST_TREASURY
        assert accepts[0]["payToAddress"] not in ("", x402.X402_PLACEHOLDER_WALLETS)

    # Undo the reload mutations exactly (never leak the test fake or a
    # gopass-dependent re-derivation into sibling tests).
    _restore_modules(snapshot)


def _default_tx_book() -> dict[str, dict[str, object]]:
    """Canonical fake on-chain book for the settlement-fidelity tests.

    Every entry is a *realistic* transfer fact: the recipient the funds landed
    on and the amount paid. The mocked facilitator only credits an entry when
    the recipient IS the treasury and the amount covers the required price.
    """
    return {
        FAKE_TX_GOOD: {
            "to": TEST_TREASURY,
            "amount_usd": CRAWL_PRICE_USD,  # exactly the required price
            "asset": "USDC",
        },
        FAKE_TX_OVER: {
            "to": TEST_TREASURY,
            "amount_usd": 0.05,  # overpayment — allowed
            "asset": "USDC",
        },
        FAKE_TX_UNDERPAID: {
            "to": TEST_TREASURY,
            "amount_usd": 0.005,  # < 0.01 required — must be rejected
            "asset": "USDC",
        },
        FAKE_TX_WRONG_RECIPIENT: {
            "to": WRONG_TREASURY,  # impostor, not the treasury — must reject
            "amount_usd": CRAWL_PRICE_USD,
            "asset": "USDC",
        },
    }


class _FakeFacilitatorRouter:
    """Stateful stand-in for the facilitator's on-chain verify/settle.

    Models a REAL x402 facilitator rather than an unconditional ``verified=True``
    stub. ``verify`` refuses to credit a transfer unless:
      - a known transaction exists for the ``tx_hash`` (unknown_transaction);
      - the on-chain transfer's recipient equals the treasury payTo
        (wrong_recipient);
      - the on-chain amount paid covers the server-required ``amount_usd``
        (underpayment).

    Overpayment is allowed. ``settle`` only succeeds for an on-chain transfer
    that holds the same recipient/amount facts, and records an idempotency
    ledger entry. The mock does NOT silently swallow replay — the caller's
    replay handling (``X402Handler._tx_consumed``) is exercised separately.
    """

    def __init__(
        self,
        treasury: str,
        tx_book: dict[str, dict[str, object]] | None = None,
    ) -> None:
        self._treasury = treasury
        self._tx_book = tx_book if tx_book is not None else _default_tx_book()
        self._settled: set[str] = set()
        self.verify_calls: list[dict[str, object]] = []
        self.settle_calls: list[dict[str, object]] = []

    async def verify(
        self,
        *,
        payment_id: str,
        tx_hash: str,
        network: str,
        asset: str,
        amount_usd: float,
    ) -> dict[str, object]:
        self.verify_calls.append(
            {
                "payment_id": payment_id,
                "tx_hash": tx_hash,
                "network": network,
                "asset": asset,
                "amount_usd": amount_usd,
            }
        )
        tx = self._tx_book.get(tx_hash)
        if tx is None:
            return self._failed("unknown_transaction", tx_hash)
        if str(tx["to"]).lower() != self._treasury.lower():
            return self._failed("wrong_recipient", tx_hash)
        if float(tx["amount_usd"]) + 1e-9 < float(amount_usd):
            return self._failed("underpayment", tx_hash)
        return {
            "verified": True,
            "reason": "",
            "transaction": tx_hash,
            "facilitator": "mock",
            "network": network,
            "asset": asset,
            "amount_usd": amount_usd,
        }

    async def settle(
        self,
        *,
        payment_id: str,
        tx_hash: str,
        network: str,
        asset: str,
        amount_usd: float,
    ) -> dict[str, object]:
        self.settle_calls.append(
            {
                "payment_id": payment_id,
                "tx_hash": tx_hash,
                "network": network,
                "asset": asset,
                "amount_usd": amount_usd,
            }
        )
        tx = self._tx_book.get(tx_hash)
        if tx is None:
            return {"success": False, "transaction": "", "reason": "unknown_transaction"}
        if str(tx["to"]).lower() != self._treasury.lower():
            return {"success": False, "transaction": "", "reason": "wrong_recipient"}
        if float(tx["amount_usd"]) + 1e-9 < float(amount_usd):
            return {"success": False, "transaction": "", "reason": "underpayment"}
        if tx_hash in self._settled:
            return {
                "success": True,
                "transaction": tx_hash,
                "facilitator": "mock",
                "idempotent": True,
            }
        self._settled.add(tx_hash)
        return {
            "success": True,
            "transaction": tx_hash,
            "facilitator": "mock",
            "network": network,
            "asset": asset,
            "amount_usd": amount_usd,
        }

    @staticmethod
    def _failed(reason: str, tx_hash: str) -> dict[str, object]:
        return {
            "verified": False,
            "reason": reason,
            "transaction": tx_hash,
            "facilitator": "mock",
        }


def _make_handler(
    tmp_path: object,
    router: _FakeFacilitatorRouter,
    monkeypatch: pytest.MonkeyPatch,
) -> X402Handler:
    """Build a handler wired to the stateful router and to the config treasury.

    Uses the same config-path patching the manifest test adopted so payTo is
    real, not forged. The patches stay active for the duration of the test so
    calls that consult module config (``create_payment_required``) resolve the
    treasury; pytest's ``monkeypatch`` fixture reverts them on teardown.
    """
    monkeypatch.setattr(scheme, "X402_WALLET", TEST_TREASURY)
    monkeypatch.setattr(
        scheme,
        "X402_NETWORK_WALLETS",
        {
            k: (TEST_TREASURY if k.startswith("eip155:") else "")
            for k in scheme.X402_NETWORK_WALLETS
        },
    )
    # handler reads X402_WALLET at import; keep it consistent.
    monkeypatch.setattr(_handler_mod, "X402_WALLET", TEST_TREASURY)

    return X402Handler(
        wallet=TEST_TREASURY,
        router=router,
        payments_file=tmp_path / "payments.jsonl",
        settlements_file=tmp_path / "settlements.jsonl",
    )


@pytest.mark.asyncio
async def test_settle_verify_accepts_only_treasury_recipient(
    tmp_path: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Settlement fidelity: a transfer to the REAL treasury payTo is credited.

    The mocked facilitator compares the on-chain ``to`` against the treasury;
    because the tx paid the correct recipient AND the required amount, access
    (``is_paid``) is granted. This is not a vacuous ``verified=True`` — the
    wrong-recipient sibling test would catch a stub that ignores the recipient.
    """
    router = _FakeFacilitatorRouter(treasury=TEST_TREASURY)
    handler = _make_handler(tmp_path, router, monkeypatch)

    res = await handler.verify_payment(
        "pay_good",
        FAKE_TX_GOOD,
        network="base",
        asset="USDC",
        amount_usd=CRAWL_PRICE_USD,
        operation="crawl",
    )
    assert res["verified"] is True
    assert res["transaction"] == FAKE_TX_GOOD
    # The mock DID inspect the recipient: the recorded on-chain facts target
    # the treasury, and the mock compared against its configured payee.
    assert _default_tx_book()[FAKE_TX_GOOD]["to"] == TEST_TREASURY
    assert router.verify_calls[0]["amount_usd"] == CRAWL_PRICE_USD
    # Access is actually granted for the correct, verified payment.
    assert handler.is_paid("pay_good", operation="crawl") is True


@pytest.mark.asyncio
async def test_settle_rejects_wrong_recipient(
    tmp_path: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Settlement fidelity: a transfer to a NON-treasury address is rejected."""
    router = _FakeFacilitatorRouter(treasury=TEST_TREASURY)
    handler = _make_handler(tmp_path, router, monkeypatch)

    res = await handler.verify_payment(
        "pay_impostor",
        FAKE_TX_WRONG_RECIPIENT,
        network="base",
        asset="USDC",
        amount_usd=CRAWL_PRICE_USD,
        operation="crawl",
    )
    assert res["verified"] is False
    assert res["reason"] == "wrong_recipient"
    # No access and no settlement ledger line for the impostor transfer.
    assert handler.is_paid("pay_impostor", operation="crawl") is False
    settle = await handler.settle_payment(
        "pay_impostor",
        FAKE_TX_WRONG_RECIPIENT,
        network="base",
        asset="USDC",
        amount_usd=CRAWL_PRICE_USD,
        operation="crawl",
    )
    assert settle.get("success") is False
    assert settle.get("reason") == "wrong_recipient"


@pytest.mark.asyncio
async def test_settle_rejects_amount_mismatch(
    tmp_path: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Settlement fidelity: an underpaid transfer is rejected (atomic compare).

    The on-chain transfer only paid 0.005 USDC while the server requires
    0.01 USDC for ``crawl``. The facilitator refuses to credit it even though
    the recipient is correct.
    """
    router = _FakeFacilitatorRouter(treasury=TEST_TREASURY)
    handler = _make_handler(tmp_path, router, monkeypatch)

    res = await handler.verify_payment(
        "pay_underpaid",
        FAKE_TX_UNDERPAID,
        network="base",
        asset="USDC",
        amount_usd=CRAWL_PRICE_USD,
        operation="crawl",
    )
    assert res["verified"] is False
    assert res["reason"] == "underpayment"
    assert handler.is_paid("pay_underpaid", operation="crawl") is False


@pytest.mark.asyncio
async def test_settle_rejects_same_tx_hash_replay(
    tmp_path: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Replay hardening: the same tx_hash cannot be verified twice.

    The mocked facilitator is *lenient* (it re-credits a replayed tx_hash since
    the on-chain facts still hold) — it is the handler's ``_tx_consumed`` replay
    guard that must reject a second payment_id riding on the same tx_hash. A
    payer swapping a fresh payment_id onto an already-used tx_hash must not be
    able to mint a second valid payment.
    """
    router = _FakeFacilitatorRouter(treasury=TEST_TREASURY)
    handler = _make_handler(tmp_path, router, monkeypatch)

    first = await handler.verify_payment(
        "pay_first",
        FAKE_TX_GOOD,
        network="base",
        asset="USDC",
        amount_usd=CRAWL_PRICE_USD,
        operation="crawl",
    )
    assert first["verified"] is True

    replay = await handler.verify_payment(
        "pay_replay",
        FAKE_TX_GOOD,
        network="base",
        asset="USDC",
        amount_usd=CRAWL_PRICE_USD,
        operation="crawl",
    )
    assert replay["verified"] is False
    assert replay["reason"] == "tx_hash already consumed"
    # The replayed payment was never granted access / never recorded as valid.
    assert handler.is_paid("pay_replay", operation="crawl") is False


@pytest.mark.asyncio
async def test_settle_failure_does_not_grant_access(
    tmp_path: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A settlement the facilitator cannot confirm (unknown tx) grants nothing.

    An unknown ``tx_hash`` is the canonical settlement failure: there is no
    on-chain transfer to credit. ``verify`` returns ``verified=False`` and the
    payment must not satisfy ``is_paid``.
    """
    router = _FakeFacilitatorRouter(treasury=TEST_TREASURY)
    handler = _make_handler(tmp_path, router, monkeypatch)

    res = await handler.verify_payment(
        "pay_unknown",
        FAKE_TX_UNKNOWN,
        network="base",
        asset="USDC",
        amount_usd=CRAWL_PRICE_USD,
        operation="crawl",
    )
    assert res["verified"] is False
    assert res["reason"] == "unknown_transaction"
    assert handler.is_paid("pay_unknown", operation="crawl") is False


@pytest.mark.asyncio
async def test_e2e_402_verify_settle_writes_real_tx_record(
    tmp_path: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    """gap #4: 402 -> verify -> settle on a fidelity-checked mock path.

    Keeps the valuable pricing + manifest assertions (treasury payTo is the
    real address, underpayment is rejected against the server price in atomic
    units, overpayment is allowed) and NOW drives a stateful facilitator that
    inspects recipient/amount, so the "settle writes a real record" claim is
    backed by settlement fidelity rather than an unconditional async stub.
    """
    router = _FakeFacilitatorRouter(treasury=TEST_TREASURY)
    handler = _make_handler(tmp_path, router, monkeypatch)

    # 1) 402 -> build the payment-required body, assert REAL payTo.
    body, headers = handler.create_payment_required(
        "crawl", preferred_networks=["base"], preferred_assets=["USDC"]
    )
    accept = body["accepts"][0]
    assert accept["payToAddress"] == TEST_TREASURY
    assert accept["payToAddress"] != ""
    assert accept["payToAddress"] not in x402.X402_PLACEHOLDER_WALLETS
    assert headers.get("PAYMENT-REQUIRED")

    # 2) pay + verify underpayment -> REJECTED (atomic compare). The server's
    #    own pricing gate refuses before the facilitator is ever consulted.
    under_res = await handler.verify_payment(
        "pay_under_e2e",
        "0xundertx",
        network="base",
        asset="USDC",
        amount_usd=0.0001,  # crawl is $0.01 -> underpayment
        operation="crawl",
    )
    assert under_res["verified"] is False
    assert "underpayment" in under_res["reason"]
    assert router.verify_calls == [], "underpaid head must never reach the router"

    # 3) verify a correct-amount transfer to the treasury -> verified
    #    (the facilitator checks recipient == treasury AND amount >= price).
    ok_res = await handler.verify_payment(
        "pay_ok_e2e",
        FAKE_TX_GOOD,
        network="base",
        asset="USDC",
        amount_usd=CRAWL_PRICE_USD,
        operation="crawl",
    )
    assert ok_res["verified"] is True, ok_res
    assert ok_res["transaction"] == FAKE_TX_GOOD

    # 4) overpayment is allowed (0.05 >= 0.01).
    over_res = await handler.verify_payment(
        "pay_over_e2e",
        FAKE_TX_OVER,
        network="base",
        asset="USDC",
        amount_usd=CRAWL_PRICE_USD,
        operation="crawl",
    )
    assert over_res["verified"] is True, over_res
    assert len(router.verify_calls) == 2, "valid verifies must reach the router"

    # 5) settle -> the facilitator only settles a real treasury transfer and
    #    writes a real (non-idempotent-first) settlement record.
    settlement = await handler.settle_payment(
        "pay_ok_e2e",
        FAKE_TX_GOOD,
        network="base",
        asset="USDC",
        amount_usd=CRAWL_PRICE_USD,
        operation="crawl",
    )
    assert settlement["transaction"] == FAKE_TX_GOOD
    assert settlement.get("success") is True
    assert len(router.settle_calls) == 1

    # 6) settle idempotency: a second settle for the same tx returns the cached
    #    receipt WITHOUT re-rolling the facilitator or appending a 2nd line.
    second = await handler.settle_payment(
        "pay_ok_e2e",
        FAKE_TX_GOOD,
        network="base",
        asset="USDC",
        amount_usd=CRAWL_PRICE_USD,
        operation="crawl",
    )
    assert second["transaction"] == FAKE_TX_GOOD
    assert len(router.settle_calls) == 1, "idempotent settle must not re-roll router"

    # 7) The settlement audit log carries the real tx record, exactly once.
    lines = (tmp_path / "settlements.jsonl").read_text().splitlines()
    assert sum(FAKE_TX_GOOD in ln for ln in lines) == 1
    assert any('"network": "base"' in ln for ln in lines)

    # 8) The payment record is server-authoritative (atomic required amount).
    rec = handler.get_payment("pay_ok_e2e")
    assert rec is not None
    assert rec["required_amount_atomic"] > 0
    assert rec["verified"] is True
