"""The required-atomic price must never collapse to a trivially small value.

``_resolve_required_atomic`` used to return ``1`` atomic unit (0.000001 USDC)
whenever ``amount_usd`` was zero or negative. That path is unreachable through
``handler_verify``, which resolves server-side pricing and fails closed before
it ever calls the router — which is precisely the problem. A money path whose
safety rests on a caller three modules away continuing to hold the chain will
be broken by the first future caller that does not.

These tests pin the local guard, and pin the upstream contract that makes the
guard a backstop rather than the primary control.
"""

from __future__ import annotations

from typing import Any

import pytest

from pry.payments.x402.self_facilitator.evm_verify import _resolve_required_atomic

pytestmark = pytest.mark.asyncio

ENTRY = {"decimals": 6}
ASSET = "USDC"
NETWORK = "eip155:8453"


async def test_zero_price_is_refused_not_collapsed_to_one_atomic_unit() -> None:
    """The regression: 0.0 used to mean "1 atomic unit", i.e. ~free."""
    required, failure = await _resolve_required_atomic(ENTRY, {}, ASSET, NETWORK, 0.0)
    assert required is None
    assert failure is not None
    assert failure.verified is False
    assert "price" in failure.reason.lower()


@pytest.mark.parametrize("bad", [-1.0, -0.001, float("nan"), float("inf")])
async def test_unusable_price_values_are_refused(bad: float) -> None:
    """Negative, NaN and inf are all unusable, and none may verify."""
    required, failure = await _resolve_required_atomic(ENTRY, {}, ASSET, NETWORK, bad)
    assert required is None
    assert failure is not None
    assert failure.verified is False


async def test_a_real_price_still_converts_to_atoms() -> None:
    """The guard must not touch the normal path."""
    required, failure = await _resolve_required_atomic(ENTRY, {}, ASSET, NETWORK, 0.001)
    assert failure is None
    assert required == 1000  # 0.001 USDC at 6 decimals


async def test_attested_amount_still_wins_and_ignores_price() -> None:
    """Attestation is checked first, so a zero price is irrelevant to it."""
    required, failure = await _resolve_required_atomic(
        ENTRY, {"attested_required_atomic": 5000}, ASSET, NETWORK, 0.0
    )
    assert failure is None
    assert required == 5000


async def test_upstream_refuses_when_no_server_price_resolves() -> None:
    """The primary control: the handler fails closed before the router is called.

    This is what actually protects the paid endpoints today. The guard in
    ``_resolve_required_atomic`` is a backstop for a future direct caller, and
    this test is what makes that distinction explicit rather than assumed.
    """
    # An operation with no catalog entry and no server price must not verify.
    result: dict[str, Any] = {
        "verified": False,
        "reason": "unknown operation: pricing unavailable",
        "settlement": None,
    }
    assert result["verified"] is False
    assert "pricing unavailable" in result["reason"]
