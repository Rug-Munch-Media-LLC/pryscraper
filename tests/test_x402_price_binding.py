# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Price-binding tests for the x402 attestation (audit item #7).

The challenge's SIGNED ``maxAmountRequired`` is the authoritative required
amount for volatile-asset (ETH/ARB/SOL) verification: an honest payer who
authorized the challenge-quoted amount must not be rejected because the live
oracle moved between challenge issuance and payment. Stablecoins (1:1) are
unaffected; unattested bodies keep the previous live-quote comparison.

SelfFacilitator.verify only accepts ``eip3009`` assets, so the volatile-asset
tests patch ``resolve_asset_entry`` (the acceptance-table dependency seam) to
expose an eip3009 ETH entry — the price-binding logic under test is untouched.
"""

from __future__ import annotations

import time
from typing import Any

import pytest

from pry.payments.x402.scheme import (
    X402_ATTEST_KEY_ENV,
    AssetUsdQuote,
    attest_payment_required,
    attested_max_amount_required,
    build_payment_required,
    clear_price_cache,
    verify_payment_required_attestation,
)
from pry.payments.x402.self_facilitator import SelfFacilitator

_TEST_KEY = "0x" + "11" * 32
_PAY_TO = "0x1E3AC01d0fdb976179790BDD02823196A92705C9"
_PAYER_KEY_HEX = "22" * 32
_FAKE_ETH_CONTRACT = "0x" + "ab" * 20

_ETH_ENTRY = {
    "asset": "ETH",
    "network": "eip155:1",
    "name": "Test ETH (eip3009)",
    "contract": _FAKE_ETH_CONTRACT,
    "decimals": 18,
    "verification": "eip3009",
    "kind": "erc20",
}


@pytest.fixture(autouse=True)
def _attest_env(monkeypatch):
    """Deterministic attestation key + clean oracle cache per test."""
    import pry.payments.x402.scheme as scheme_mod

    monkeypatch.setenv(X402_ATTEST_KEY_ENV, _TEST_KEY)
    monkeypatch.setattr(scheme_mod, "_attest_key_cache", None)
    clear_price_cache()
    yield
    monkeypatch.setattr(scheme_mod, "_attest_key_cache", None, raising=False)
    clear_price_cache()


def _patch_eth_as_eip3009(monkeypatch) -> None:
    """Expose an eip3009 ETH entry so SelfFacilitator.verify reaches the
    amount comparison for a volatile asset."""
    import pry.payments.x402.self_facilitator as sf_mod

    real = sf_mod.resolve_asset_entry

    def _entry(network: str, asset: str) -> dict[str, Any] | None:
        entry = real(network, asset)
        if entry is not None and str(entry.get("asset", "")).upper() == "ETH":
            return dict(_ETH_ENTRY, network=str(entry.get("network") or network))
        return entry

    monkeypatch.setattr(sf_mod, "resolve_asset_entry", _entry)


def _eth_accept(max_atomic: int) -> dict[str, Any]:
    return {
        "scheme": "exact",
        "network": "eip155:1",
        "maxAmountRequired": str(max_atomic),
        "resource": "https://pry.dev/api/scrape",
        "description": "scrape",
        "mimeType": "application/json",
        "payToAddress": _PAY_TO,
        "asset": "ETH",
        "extra": {"operation": "scrape"},
    }


def _usdc_accept(max_atomic: int) -> dict[str, Any]:
    accept = _eth_accept(max_atomic)
    accept["asset"] = "USDC"
    return accept


def _attested_body(accept: dict[str, Any]) -> dict[str, Any]:
    return attest_payment_required({"x402Version": 1, "accepts": [accept]})


def _signed_payment(
    asset: str,
    value_atomic: int,
    nonce: bytes,
    token_address: str,
    decimals: int,
) -> dict[str, Any]:
    """Build a payment dict with a REAL EIP-3009 signature over ``value``."""
    from eth_account import Account
    from eth_keys import keys as eth_keys

    from pry.payments.x402.self_facilitator import (
        build_transfer_with_authorization_digest,
    )

    acct = Account.from_key(bytes.fromhex(_PAYER_KEY_HEX))
    pk = eth_keys.PrivateKey(bytes.fromhex(_PAYER_KEY_HEX))
    valid_before = int(time.time()) + 600
    digest = build_transfer_with_authorization_digest(
        from_address=acct.address,
        to_address=_PAY_TO,
        value=value_atomic,
        valid_after=0,
        valid_before=valid_before,
        nonce=nonce,
        chain_id=1,
        token_address=token_address,
        name="USD Coin",
        version="2",
    )
    sig = pk.sign_msg_hash(digest)
    return {
        "network": "eip155:1",
        "asset": asset,
        "amount_usd": 0.001,
        "authorization": {
            "from": acct.address,
            "to": _PAY_TO,
            "value": str(value_atomic),
            "validAfter": "0",
            "validBefore": str(valid_before),
            "nonce": "0x" + nonce.hex(),
            "chainId": 1,
            "signature": "0x" + sig.to_bytes().hex(),
        },
    }


def _eth_payment(value_atomic: int, nonce: bytes) -> dict[str, Any]:
    return _signed_payment("ETH", value_atomic, nonce, _FAKE_ETH_CONTRACT, 18)


def _usdc_payment(value_atomic: int, nonce: bytes) -> dict[str, Any]:
    return _signed_payment(
        "USDC", value_atomic, nonce, "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48", 6
    )


# ── helper extraction ────────────────────────────────────────────────────────


def test_attested_max_amount_required_extracts_matching_accept() -> None:
    body = _attested_body(_eth_accept(4_000_000_000_000))
    assert verify_payment_required_attestation(body)["verified"] is True
    assert attested_max_amount_required(body, "eip155:1", "ETH") == 4_000_000_000_000
    # Legacy network name normalizes to the same accept.
    assert attested_max_amount_required(body, "ethereum", "ETH") == 4_000_000_000_000


def test_attested_max_amount_required_no_match_returns_zero() -> None:
    body = _attested_body(_eth_accept(4_000_000_000_000))
    assert attested_max_amount_required(body, "eip155:1", "ARB") == 0
    assert attested_max_amount_required({}, "eip155:1", "ETH") == 0
    assert attested_max_amount_required({"accepts": []}, "eip155:1", "ETH") == 0


def test_attested_max_amount_required_unattested_body_returns_zero() -> None:
    body = {"x402Version": 1, "accepts": [_eth_accept(4_000_000_000_000)]}
    assert attested_max_amount_required(body, "eip155:1", "ETH") == 0


# ── SelfFacilitator.verify price binding ─────────────────────────────────────


@pytest.mark.asyncio
async def test_attested_amount_beats_higher_live_oracle_quote(monkeypatch) -> None:
    """ETH accept attested at X → payment of X verifies even when the live
    oracle would quote a HIGHER required amount (the audit #7 bug)."""
    import pry.payments.x402.scheme as scheme_mod
    import pry.payments.x402.self_facilitator as sf_mod

    _patch = _patch_eth_as_eip3009  # keep linters happy about local defs
    _patch(monkeypatch)

    async def _high_quote(asset: str, network: str = "") -> AssetUsdQuote:
        # Live oracle says ETH is worth 2x the static challenge quote.
        return AssetUsdQuote(usd=5000.0, source="oracle")

    monkeypatch.setattr(scheme_mod, "get_asset_usd_price", _high_quote)
    monkeypatch.setattr(sf_mod, "get_asset_usd_price", _high_quote)

    fac = SelfFacilitator(pay_to=_PAY_TO, nonce_path=None)
    attested = _attested_body(_eth_accept(4_000_000_000_000))
    assert verify_payment_required_attestation(attested)["verified"] is True
    attested_atomic = attested_max_amount_required(attested, "eip155:1", "ETH")

    payment = _eth_payment(4_000_000_000_000, bytes(32))
    payment["attested_required_atomic"] = attested_atomic
    result = await fac.verify(payment)
    assert result.verified is True, result.reason


@pytest.mark.asyncio
async def test_underpayment_vs_attested_amount_rejected(monkeypatch) -> None:
    """Paying LESS than the ATTESTED amount is still underpayment — the gate
    stays fail-closed even with the binding active."""
    import pry.payments.x402.scheme as scheme_mod
    import pry.payments.x402.self_facilitator as sf_mod

    _patch_eth_as_eip3009(monkeypatch)

    async def _low_quote(asset: str, network: str = "") -> AssetUsdQuote:
        # Oracle would ACCEPT this payment (price dropped) — the attested
        # amount must still be enforced.
        return AssetUsdQuote(usd=1000.0, source="oracle")

    monkeypatch.setattr(scheme_mod, "get_asset_usd_price", _low_quote)
    monkeypatch.setattr(sf_mod, "get_asset_usd_price", _low_quote)

    fac = SelfFacilitator(pay_to=_PAY_TO, nonce_path=None)
    attested = _attested_body(_eth_accept(4_000_000_000_000))
    attested_atomic = attested_max_amount_required(attested, "eip155:1", "ETH")

    payment = _eth_payment(4_000_000_000_000 // 2, bytes(32))
    payment["attested_required_atomic"] = attested_atomic
    result = await fac.verify(payment)
    assert result.verified is False
    assert "underpayment" in (result.reason or "")


@pytest.mark.asyncio
async def test_stablecoin_path_unchanged_at_exact_amount() -> None:
    """USDC 1000 atomic still verifies at exactly the required amount (1:1)."""
    fac = SelfFacilitator(pay_to=_PAY_TO, nonce_path=None)
    payment = _usdc_payment(1000, bytes(31) + b"\x01")
    result = await fac.verify(payment)
    assert result.verified is True, result.reason
    assert result.amount_atomic == 1000


@pytest.mark.asyncio
async def test_unattested_payment_keeps_live_quote_behavior(monkeypatch) -> None:
    """No attested amount → previous behavior: live-oracle comparison."""
    import pry.payments.x402.scheme as scheme_mod
    import pry.payments.x402.self_facilitator as sf_mod

    _patch_eth_as_eip3009(monkeypatch)

    async def _high_quote(asset: str, network: str = "") -> AssetUsdQuote:
        return AssetUsdQuote(usd=5000.0, source="oracle")

    monkeypatch.setattr(scheme_mod, "get_asset_usd_price", _high_quote)
    monkeypatch.setattr(sf_mod, "get_asset_usd_price", _high_quote)

    fac = SelfFacilitator(pay_to=_PAY_TO, nonce_path=None)
    payment = _eth_payment(4_000_000_000_000, bytes(32) + b"\x02")
    result = await fac.verify(payment)
    # 0.001 USD at 5000/ETH = 2e11 required < 4e12 authorized → verifies.
    assert result.verified is True, result.reason

    # ...but a payment BELOW the live-quoted requirement is still rejected.
    payment2 = _eth_payment(1_000_000_000, bytes(32) + b"\x03")
    result2 = await fac.verify(payment2)
    assert result2.verified is False
    assert "underpayment" in (result2.reason or "")


@pytest.mark.asyncio
async def test_attested_binding_ignores_garbage_value(monkeypatch) -> None:
    """A non-numeric/garbage attested value falls back to the live quote."""
    import pry.payments.x402.scheme as scheme_mod
    import pry.payments.x402.self_facilitator as sf_mod

    _patch_eth_as_eip3009(monkeypatch)

    async def _high_quote(asset: str, network: str = "") -> AssetUsdQuote:
        return AssetUsdQuote(usd=5000.0, source="oracle")

    monkeypatch.setattr(scheme_mod, "get_asset_usd_price", _high_quote)
    monkeypatch.setattr(sf_mod, "get_asset_usd_price", _high_quote)

    fac = SelfFacilitator(pay_to=_PAY_TO, nonce_path=None)
    payment = _eth_payment(1_000_000_000, bytes(32) + b"\x03")
    payment["attested_required_atomic"] = "not-a-number"
    result = await fac.verify(payment)
    assert result.verified is False
    assert "underpayment" in (result.reason or "")


@pytest.mark.asyncio
async def test_attestation_signer_address_configured() -> None:
    """Sanity: the fixture key resolves to a signer (attestation is live)."""
    from pry.payments.x402.scheme import attestation_signer_address

    assert attestation_signer_address() != ""


# ── Header compaction: every configured family stays payable ────────────────


def test_compaction_keeps_every_network_stablecoin_payable():
    """The wire challenge must keep every configured network in accepts.

    Regression: the 12KB budget tail-dropped Polygon + the whole Solana
    family from the wire header even though both are fully configured and
    verifiable. Stripping the heavy discovery tables from the header copy
    (they ride in the response body + /v1/x402/pricing) frees the budget.
    """
    import base64
    import json as _json

    from pry.payments.x402_middleware.enforcement import (
        X402_PAYMENT_HEADER_MAX_BYTES,
        _compact_payment_required_header,
    )

    body = build_payment_required("scrape", multi_asset=True)
    header = _compact_payment_required_header(body, X402_PAYMENT_HEADER_MAX_BYTES)
    assert len(header.encode()) <= X402_PAYMENT_HEADER_MAX_BYTES
    decoded = _json.loads(base64.b64decode(header).decode())
    nets = {a["network"] for a in decoded["accepts"]}
    # Every network that the full body offered must stay payable-from-header.
    full_nets = {a["network"] for a in body["accepts"]}
    assert nets == full_nets, f"families dropped from the wire: {full_nets - nets}"
    # Stablecoin preferred per network.
    for a in decoded["accepts"]:
        assert a["asset"] in ("USDC", "USDT")
    # Heavy discovery metadata is header-stripped (body + pricing endpoint
    # still carry the full catalog).
    assert "supported_assets" not in decoded
    assert "networks" not in decoded
    # The trimmed body is re-attested over exactly what is advertised.
    from pry.payments.x402.scheme import verify_payment_required_attestation

    verdict = verify_payment_required_attestation(decoded)
    assert verdict["verified"] is True
