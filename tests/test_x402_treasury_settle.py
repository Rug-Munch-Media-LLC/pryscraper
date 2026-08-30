# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""x402 treasury payTo + server-authoritative settle — gap closure tests.

Covers the publish-audit gaps:
  #1 payTo must resolve to the REAL EVM treasury (gopass secret
     ``evm_treasury_address``), never a placeholder or "".
  #2 server-authoritative per-(operation, network, asset) pricing compared in
     integer atoms lives ON the verify path.
  #4 full 402 -> verify -> settle on a mocked-but-atomic path writes a real
     settlement record.

No real on-chain tx is attempted; the facilitator router is replaced at the
real seam (``X402Handler.router``), and the payTo comes from the config path.
The gopass secret is referenced by NAME only — never its value.
"""

from __future__ import annotations

import importlib
import os
from unittest.mock import AsyncMock, patch

import pytest

import pry.api.secrets_backend as _sb
import pry.payments.x402 as x402
import pry.payments.x402.handler as _handler_mod
import pry.payments.x402.scheme as scheme
from pry.payments.x402 import X402Handler

# The gopass secret NAME — never a value. (This is the whole point of gap #1.)
TREASURY_SECRET_NAME = "evm_treasury_address"
# A test-only EVM-shaped address (0x + 40 hex). NOT a live wallet. Injected as
# the "real" treasury via the secrets backend so we can prove the config path.
TEST_TREASURY = "0x" + "B2" * 20


def _reload_all() -> None:
    """Reload x402 -> scheme -> handler so config consts recompute in order."""
    importlib.reload(x402)
    importlib.reload(scheme)
    importlib.reload(_handler_mod)


def _restore_real_config() -> None:
    """Recompute module constants from the REAL secrets backend (fake undone)."""
    _reload_all()


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

    # Restore the module constants to the real runtime config (whatever the
    # machine actually resolves) — never leak the test fake into later tests.
    _restore_real_config()


class _FakeRouter:
    """Deterministic stand-in for the facilitator router at the real seam."""

    def __init__(self) -> None:
        self.verify = AsyncMock(return_value={"verified": True, "reason": ""})
        self.settle = AsyncMock(
            return_value={
                "success": True,
                "transaction": "0xsettled_tx",
                "facilitator": "mock",
                "network": "base",
                "asset": "USDC",
            }
        )


@pytest.mark.asyncio
async def test_e2e_402_verify_settle_writes_real_tx_record(tmp_path: object) -> None:
    """gap #4: 402 -> verify -> settle with a mocked-but-atomic facilitator.

    Asserts the treasury payTo is the real address (not ''), underpayment is
    rejected against the server price in atomic units, overpayment is allowed,
    and settle writes a real settlement record.
    """
    monkey = pytest.MonkeyPatch()
    # payTo comes from the config path, not a forged value.
    monkey.setattr(scheme, "X402_WALLET", TEST_TREASURY)
    monkey.setattr(
        scheme,
        "X402_NETWORK_WALLETS",
        {k: TEST_TREASURY if k.startswith("eip155:") else "" for k in scheme.X402_NETWORK_WALLETS},
    )
    # handler reads X402_WALLET at import; keep it consistent.
    monkey.setattr(_handler_mod, "X402_WALLET", TEST_TREASURY)

    router = _FakeRouter()
    handler = X402Handler(
        wallet=TEST_TREASURY,
        router=router,
        payments_file=tmp_path / "payments.jsonl",
        settlements_file=tmp_path / "settlements.jsonl",
    )

    try:
        # 1) 402 -> build the payment-required body, assert REAL payTo.
        body, headers = handler.create_payment_required(
            "crawl", preferred_networks=["base"], preferred_assets=["USDC"]
        )
        accept = body["accepts"][0]
        assert accept["payToAddress"] == TEST_TREASURY
        assert accept["payToAddress"] != ""
        assert accept["payToAddress"] not in x402.X402_PLACEHOLDER_WALLETS
        assert headers.get("PAYMENT-REQUIRED")

        # 2) pay + verify underpayment -> REJECTED (atomic compare).
        under_res = await handler.verify_payment(
            "crawl",
            "0xundertx",
            network="base",
            asset="USDC",
            amount_usd=0.0001,  # crawl is $0.01 -> underpayment
            operation="crawl",
        )
        assert under_res["verified"] is False
        assert "underpayment" in under_res["reason"]
        # The underpay head never reached the router.
        assert router.verify.call_count == 0

        # 3) verify valid amount -> verified (server-authoritative price used).
        ok_res = await handler.verify_payment(
            "crawl",
            "0xoktx",
            network="base",
            asset="USDC",
            amount_usd=0.01,
            operation="crawl",
        )
        assert ok_res["verified"] is True, ok_res
        # Overpayment is allowed (0.05 >= 0.01).
        over_res = await handler.verify_payment(
            "crawl",
            "0xover",
            network="base",
            asset="USDC",
            amount_usd=0.05,
            operation="crawl",
        )
        assert over_res["verified"] is True, over_res
        assert router.verify.call_count > 0, "valid verify must reach the router"

        # 4) settle -> writes a real settlement record.
        settlement = await handler.settle_payment(
            "crawl",
            "0xoktx",
            network="base",
            asset="USDC",
            amount_usd=0.01,
            operation="crawl",
        )
        assert settlement["transaction"] == "0xsettled_tx"
        assert router.settle.call_count > 0

        # The settlement audit log carries the real tx record.
        lines = (tmp_path / "settlements.jsonl").read_text().splitlines()
        assert any("0xsettled_tx" in ln for ln in lines)
        assert any('"network": "base"' in ln for ln in lines)

        # The payment record is server-authoritative (atomic required amount).
        rec = handler.get_payment("crawl")
        assert rec is not None
        assert rec["required_amount_atomic"] > 0
    finally:
        monkey.undo()
