"""Candidate semantics and facade parity for Solana transfer verification."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

import threading
from typing import Any

import pytest

from pry.payments.x402 import solana_verifier as legacy
from tests.test_x402_solana_transfer import (
    OTHER,
    RECIPIENT,
    USDT,
    _body,
    _call,
    _native,
    _RpcServer,
    _spl,
    _tx,
    new,
)


@pytest.fixture
def rpc() -> Any:
    server = _RpcServer()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)


class TestTransferSemantics:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("case", "instructions", "kwargs", "needle"),
        [
            ("mint", [_spl("2000000", mint="UnsupportedMint")], {}, "wrong_mint"),
            ("asset", [_spl("2000000", mint=USDT)], {"asset": "USDC"}, "wrong_asset"),
            ("recipient", [_spl("2000000", destination=OTHER)], {}, "wrong_recipient"),
            ("underpay", [_spl("500000")], {}, "underpayment"),
            ("native_price", [_native()], {"asset": "SOL"}, "sol_price_unavailable"),
        ],
    )
    async def test_candidate_failures_are_precise(
        self,
        rpc: _RpcServer,
        case: str,
        instructions: list[dict[str, Any]],
        kwargs: dict[str, Any],
        needle: str,
    ) -> None:
        _body(rpc, {"result": _tx(instructions)})
        out = await _call(
            "sig", RECIPIENT, 1.0, rpc_url=f"http://127.0.0.1:{rpc.server_port}", **kwargs
        )
        assert out["verified"] is False
        assert needle in out["reason"]
        if case == "underpay":
            assert out["amount_raw"] == 500_000

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("result", "needle"),
        [
            (_tx([_spl()], slot=None), "transaction_not_confirmed"),
            (_tx([_spl()], err={"boom": 1}), "transaction_failed"),
        ],
    )
    async def test_confirmation_gating(
        self, rpc: _RpcServer, result: dict[str, Any], needle: str
    ) -> None:
        _body(rpc, {"result": result})
        out = await _call("sig", RECIPIENT, 1.0, rpc_url=f"http://127.0.0.1:{rpc.server_port}")
        assert out["verified"] is False
        assert needle in out["reason"]


class TestPublicParity:
    def test_legacy_facade_and_new_module_keep_the_public_contract(self) -> None:
        if new is None:
            pytest.xfail("new Solana transfer facade is not present")
        assert legacy.verify_solana_payment is new.verify_solana_payment
        for name in (
            "_parse_amount",
            "_iter_spl_instructions",
            "_iter_system_transfers",
            "_confirmed_at",
        ):
            assert getattr(legacy, name) is getattr(new, name)
        assert legacy.SUPPORTED_SOLANA_ASSETS == new.SUPPORTED_SOLANA_ASSETS
