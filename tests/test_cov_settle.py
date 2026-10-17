"""Branch coverage for the x402 SettleMixin replay / failure paths.

Each test removes one branch mentally: a deleted abort/cache/retry guard
changes the asserted observable value (router call count, receipt identity,
raised error), so a surviving mutant fails here.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

import pytest

from pry.payments.x402 import handler_settle as hs
from tests.test_cov_x402_support import Router, SettleHost, ok_receipt


async def test_pre_settle_abort_returns_receipt_and_skips_facilitator() -> None:
    router = Router([ok_receipt()])
    host = SettleHost(router)
    host._pre_settle_hooks.append(lambda **_: {"abort": True, "reason": "daily cap"})

    out = await host.settle_payment("pay_1", "0xabc", network="base")

    assert out == {"success": False, "error": "daily cap"}
    assert router.calls == []
    assert host.records == []


async def test_passthrough_hook_then_abort() -> None:
    router = Router([ok_receipt()])
    host = SettleHost(router)
    seen: list[str] = []
    host._pre_settle_hooks.extend([lambda **_: seen.append("pass"), lambda **_: {"abort": True}])

    out = await host.settle_payment("pay_1", "0x1", network="base")

    assert seen == ["pass"]
    assert out == {"success": False, "error": "aborted by pre-settle hook"}
    assert router.calls == []


async def test_replayed_settle_hits_cache_once() -> None:
    router = Router([ok_receipt()])
    host = SettleHost(router)

    first = await host.settle_payment("pay_1", "0xfeed", network="base")
    second = await host.settle_payment("pay_1", "0xfeed", network="base")

    assert first["success"] is True
    assert second["tx_hash"] == "0xfeed"
    assert len(router.calls) == 1
    assert len(host.records) == 1


async def test_failed_settle_is_not_cached_and_can_retry() -> None:
    router = Router([{"success": False, "reason": "declined"}, ok_receipt()])
    host = SettleHost(router)

    first = await host.settle_payment("pay_1", "0xdead", network="base")
    second = await host.settle_payment("pay_1", "0xdead", network="base")

    assert first["success"] is False
    assert first["reason"] == "declined"
    assert second["success"] is True
    assert len(router.calls) == 2
    assert len(host.records) == 2


async def test_strict_settle_raises_with_reason_and_identity() -> None:
    host = SettleHost(Router([{"success": False, "reason": "insufficient funds"}]))

    with pytest.raises(hs.SettleError) as caught:
        await host.settle_payment_strict("pay_9", "0xabc", network="base", asset="USDC")

    assert caught.value.reason == "insufficient funds"
    assert caught.value.extra == {
        "payment_id": "pay_9",
        "tx_hash": "0xabc",
        "network": "base",
        "asset": "USDC",
    }


async def test_strict_settle_returns_success_receipt_unchanged() -> None:
    host = SettleHost(Router([ok_receipt()]))
    out = await host.settle_payment_strict("pay_1", "0xfeed", network="base")
    assert out["transaction"] == "0xfeed"


async def test_facilitator_error_is_retried_once(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(hs, "_retry_after_seconds", lambda *_: 0.0)
    router = Router([RuntimeError("facilitator 502"), ok_receipt()])
    host = SettleHost(router)

    out = await host.settle_payment("pay_1", "0xfeed", network="base")

    assert out["success"] is True
    assert len(router.calls) == 2


async def test_facilitator_error_raises_after_four_attempts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(hs, "_retry_after_seconds", lambda *_: 0.0)
    router = Router([RuntimeError("down")] * 4)
    host = SettleHost(router)

    with pytest.raises(RuntimeError, match="down"):
        await host.settle_payment("pay_1", "0xfeed", network="base")

    assert len(router.calls) == 4
    assert host.records == []
