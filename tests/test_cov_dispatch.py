"""Branch coverage for the x402 facilitator chain dispatch delegates."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

from typing import TYPE_CHECKING

from pry.payments.x402 import facilitator_dispatch as fd

if TYPE_CHECKING:
    import pytest


class Host(fd.DispatchMixin):
    def __init__(self) -> None:
        self._network_facilitators: dict[str, object] = {}
        self._pending_auths: dict[str, dict] = {}


def test_register_caip2_facilitator_keeps_only_the_id() -> None:
    host = Host()
    impl = object()

    host.register_facilitator("solana:mainnet", impl)

    assert host._network_facilitators == {"solana:mainnet": impl}


def test_register_legacy_name_also_sets_bare_key() -> None:
    host = Host()
    impl = object()

    host.register_facilitator("solana", impl)

    assert host._network_facilitators["solana"] is impl
    assert all(value is impl for value in host._network_facilitators.values())


def test_submit_authorization_stores_by_payment_id() -> None:
    host = Host()
    auth = {"signature": "0xsig", "nonce": "1"}
    host.submit_authorization("pay_1", auth)
    assert host._pending_auths == {"pay_1": auth}


async def test_solana_and_tron_verify_delegates(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_solana(*args):
        return {"chain": "solana", "args": args}

    async def fake_tron(*args):
        return {"chain": "tron", "args": args}

    monkeypatch.setattr(fd, "verify_solana", fake_solana)
    monkeypatch.setattr(fd, "verify_tron", fake_tron)
    host = Host()

    assert await host._verify_solana("p", "0x1", "solana", "USDC", 0.1) == {
        "chain": "solana",
        "args": ("p", "0x1", "solana", "USDC", 0.1),
    }
    assert await host._verify_tron("p", "0x2", "tron", "USDT", 0.2) == {
        "chain": "tron",
        "args": ("p", "0x2", "tron", "USDT", 0.2),
    }


def test_scaffold_delegate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fd, "_scaffold_non_evm_verify", lambda *args: {"scaffold": args[2]})
    assert Host()._scaffold_non_evm_verify("p", "0x1", "ton", "TON", 0.3) == {"scaffold": "ton"}


async def test_eip7702_verify_and_rpc_delegates(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_verify(*args):
        return {"verified": False, "args": args}

    async def fake_rpc(client, rpc, method, params):
        return {"client": client, "rpc": rpc, "method": method, "params": params}

    monkeypatch.setattr(fd, "eip7702_verify", fake_verify)
    monkeypatch.setattr(fd, "rpc_call", fake_rpc)
    host = Host()

    assert await host._eip7702_verify("0x1", "base", "USDC", 0.4) == {
        "verified": False,
        "args": ("0x1", "base", "USDC", 0.4),
    }
    sentinel = object()
    assert await host._rpc_call(sentinel, "http://rpc", "eth_getTransaction", ["0x1"]) == {
        "client": sentinel,
        "rpc": "http://rpc",
        "method": "eth_getTransaction",
        "params": ["0x1"],
    }


def test_eip7702_matches_and_settlement_delegates(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fd, "eip7702_matches", lambda tx, net, asset, amt: (True, "paid"))
    monkeypatch.setattr(
        fd, "eip7702_settlement", lambda pid, tx, net: {"payment_id": pid, "tx": tx}
    )
    host = Host()

    assert host._eip7702_matches({"tx": 1}, "base", "USDC", 0.5) == (True, "paid")
    assert host._eip7702_settlement("p1", "0xabc", "base") == {
        "payment_id": "p1",
        "tx": "0xabc",
    }
