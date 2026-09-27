"""Swallowed failures that must not read as success.

Each case here was an ``except`` that neither logged nor re-raised and
returned a value indistinguishable from a real one:

- a wallet validator that threw and reported the wallet **valid**
- a ledger read that failed and reported the starter grant **unconsumed**,
  which re-issued real money to the same account
- an unparseable SPL amount coerced to ``0`` and kept as a **real transfer**
- an undecodable TRC-20 ``data`` word counted as a **0-value on-chain event**
- an Etherscan outage reported as "the treasury holds **no USDC**"

The pattern is the same in all five: a failure was rendered as a plausible
value. These tests pin the fail-closed behaviour so it cannot be reverted to
a default that reads as success.
"""

from __future__ import annotations

import pytest

# ── wallet_setup: a throwing validator must not report a valid wallet ────────


def test_evm_address_rejects_when_checksum_validation_raises(monkeypatch) -> None:
    from pry.payments import wallet_setup

    addr = "0xaB" * 20  # mixed case, so the checksum path is reached

    def boom(_addr: str) -> bool:
        raise ValueError("corrupt checksum table")

    import eth_utils

    monkeypatch.setattr(eth_utils, "is_checksum_address", boom)
    assert wallet_setup._is_evm_address(addr) is False


def test_evm_address_still_accepts_valid_and_lowercase(monkeypatch) -> None:
    """The fail-closed change must not break the paths that legitimately pass."""
    from pry.payments import wallet_setup

    low = "0x" + "ab" * 20
    assert wallet_setup._is_evm_address(low) is True


def test_evm_address_falls_back_to_format_only_without_eth_utils(monkeypatch) -> None:
    """ImportError is a missing OPTION, not a validation failure: format-only is right."""
    from pry.payments import wallet_setup

    real_import = (
        __builtins__["__import__"] if isinstance(__builtins__, dict) else __builtins__.__import__
    )

    def no_eth_utils(name: str, *args, **kwargs):  # type: ignore[no-untyped-def]
        if name == "eth_utils":
            raise ImportError("blocked for test")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", no_eth_utils)
    assert wallet_setup._is_evm_address("0x" + "ab" * 20) is True


# ── accounts: a ledger failure must not re-issue real money ────────────────


def test_starter_credit_denied_when_ledger_unreadable(monkeypatch) -> None:
    """Fails CLOSED: a read error is not evidence the grant is unconsumed."""
    from pry.commerce.billing import accounts

    def boom(_user_id: str, limit: int = 100) -> list[dict]:
        raise RuntimeError("ledger unavailable")

    monkeypatch.setattr(accounts.billing_service, "ledger", boom)
    assert accounts._has_starter_credit("u1") is True  # True == already granted == deny


def test_starter_credit_granted_only_when_ledger_says_so(monkeypatch) -> None:
    from pry.commerce.billing import accounts

    monkeypatch.setattr(accounts.billing_service, "ledger", lambda *a, **k: [])
    assert accounts._has_starter_credit("u-new") is False

    monkeypatch.setattr(
        accounts.billing_service, "ledger", lambda *a, **k: [{"reference": "signup"}]
    )
    assert accounts._has_starter_credit("u-old") is True


# ── solana_parse: a malformed amount is not a zero-value transfer ───────────


def test_malformed_spl_amount_is_rejected_not_zeroed() -> None:
    from pry.payments.x402.solana_parse import _parse_amount

    info = {"tokenAmount": {"amount": "not-a-number", "decimals": 6}}
    assert _parse_amount(info) is None


def test_valid_spl_amount_still_parses() -> None:
    from pry.payments.x402.solana_parse import _parse_amount

    info = {"tokenAmount": {"amount": "1000", "decimals": 6}}
    assert _parse_amount(info) == (1000, 6)


# ── tron_verifier: an undecodable data word is skipped, not a 0 event ───────


def _usdt_log(data: str) -> dict:
    """A canonical USDT Transfer log entry, with a caller-chosen data word."""
    from pry.payments.x402.tron_verifier import (
        TRANSFER_EVENT_TOPIC0,
        TRON_USDT_CONTRACT_HEX,
    )

    def topic32(addr_hex: str) -> str:
        return "0x" + addr_hex.rjust(64, "0")

    return {
        "address": TRON_USDT_CONTRACT_HEX,
        "topics": [TRANSFER_EVENT_TOPIC0, topic32("11" * 20), topic32("22" * 20)],
        "data": data,
    }


def test_undecodable_trc20_data_is_skipped() -> None:
    """The regression: undecodable data became a 0-value event in a filter."""
    from pry.payments.x402.tron_verifier import _iter_trc20_transfers

    assert _iter_trc20_transfers({"log": [_usdt_log("0xZZnothex")]}) == []


def test_trc20_decodable_data_still_passes_through() -> None:
    """The fix must not skip a well-formed value."""
    from pry.payments.x402.tron_verifier import _iter_trc20_transfers

    events = _iter_trc20_transfers({"log": [_usdt_log("0x64")]})
    assert len(events) == 1
    assert events[0]["value"] == 100


# ── earnings: an outage must not render as "no USDC" ───────────────────────


def test_etherscan_outage_propagates_instead_of_reporting_no_usdc(monkeypatch) -> None:
    """The caller must see an explicit error, not an omitted balance."""
    import httpx

    from pry.payments import earnings_treasury

    def boom(*_a, **_k):
        raise httpx.ConnectError("etherscan down")

    monkeypatch.setattr(httpx, "get", boom)
    with pytest.raises(httpx.HTTPError):
        earnings_treasury.TreasuryMixin._evm_usdc(object(), "key")  # type: ignore[arg-type]


def test_etherscan_status_not_one_still_means_no_data() -> None:
    """A legitimate 'no data' answer must still return None, not raise."""

    class Resp:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"status": "0", "message": "No data found"}

    import httpx

    from pry.payments import earnings_treasury

    orig = httpx.get
    try:
        httpx.get = lambda *a, **k: Resp()  # type: ignore[assignment]
        assert earnings_treasury.TreasuryMixin._evm_usdc(object(), "key") is None  # type: ignore[arg-type]
    finally:
        httpx.get = orig  # type: ignore[assignment]
