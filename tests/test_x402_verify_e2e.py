# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""End-to-end verify() tests for the self-hosted x402 facilitator.

Real cryptography: each test signs a genuine EIP-3009
``TransferWithAuthorization`` with a throwaway key and drives the full
local verification path - signer recovery, amount, recipient, validity
window, chain binding, replay protection. No RPC, no network; the USD
quote is patched (it is an oracle call, not the unit under test).

Every rejection branch asserts its exact reason string so a regression
that fails closed with the WRONG reason still trips the suite.
"""

from __future__ import annotations

import time
from typing import Any

import pytest

from pry.payments.x402.scheme import AssetUsdQuote
from pry.payments.x402.self_facilitator import (
    SelfFacilitator as Facilitator,
    VerifyResult,
    _chain_id_for,
    build_transfer_with_authorization_digest,
)

# Throwaway test key - publicly known constant, never a real wallet.
TEST_KEY_HEX = "11" * 32
PAYER = "0x" + "a1" * 20  # derived below from TEST_KEY
PAY_TO = "0x" + "b2" * 20
USDC_BASE = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"  # Base USDC
NETWORK = "base"
CHAIN_ID = _chain_id_for(NETWORK)


def _signer_account() -> Any:
    from eth_account import Account

    return Account.from_key(bytes.fromhex(TEST_KEY_HEX))


PAYER = _signer_account().address


def _make_auth(
    *,
    value: int = 1_000_000,
    to: str = PAY_TO,
    valid_after: int | None = None,
    valid_before: int | None = None,
    nonce: bytes | None = None,
    chain_id: Any = CHAIN_ID,
    tamper_value: int | None = None,
) -> dict[str, Any]:
    """Build a genuinely signed EIP-3009 authorization."""
    acct = _signer_account()
    now = int(time.time())
    va = now - 60 if valid_after is None else valid_after
    vb = now + 600 if valid_before is None else valid_before
    n = nonce or bytes(range(32))
    digest = build_transfer_with_authorization_digest(
        from_address=acct.address,
        to_address=to,
        value=value,
        valid_after=va,
        valid_before=vb,
        nonce=n,
        chain_id=CHAIN_ID,
        token_address=USDC_BASE,
    )
    signed = acct.unsafe_sign_hash(digest)
    auth: dict[str, Any] = {
        "from": acct.address,
        "to": to,
        "value": value,
        "validAfter": va,
        "validBefore": vb,
        "nonce": "0x" + n.hex(),
        "signature": bytes(signed.signature).hex(),
    }
    if chain_id is not None:
        auth["chainId"] = chain_id
    if tamper_value is not None:
        # Field tampering AFTER signing must break signer recovery.
        auth["value"] = tamper_value
    return auth


def _payment(auth: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    payment: dict[str, Any] = {
        "network": NETWORK,
        "asset": "USDC",
        "amount_usd": 1.0,
        "authorization": auth,
    }
    payment.update(overrides)
    return payment


def _facilitator(tmp_path: Any, pay_to: str = PAY_TO) -> Facilitator:
    return Facilitator(pay_to=pay_to, nonce_path=tmp_path / "nonces.json")


@pytest.fixture(autouse=True)
def _stable_quote(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch the live USD oracle - deterministic $1 quotes."""

    async def fake_quote(asset: str, network: str = "") -> AssetUsdQuote:
        return AssetUsdQuote(usd=1.0, source="test")

    monkeypatch.setattr("pry.payments.x402.self_facilitator.get_asset_usd_price", fake_quote)


class TestVerifyHappyPath:
    @pytest.mark.asyncio
    async def test_valid_authorization_verifies(self, tmp_path: Any) -> None:
        fac = _facilitator(tmp_path)
        result = await fac.verify(_payment(_make_auth()))
        assert isinstance(result, VerifyResult)
        assert result.verified is True, result.reason
        assert result.signer == PAYER
        assert result.amount_atomic == 1_000_000

    @pytest.mark.asyncio
    async def test_overpayment_verifies(self, tmp_path: Any) -> None:
        fac = _facilitator(tmp_path)
        result = await fac.verify(_payment(_make_auth(value=5_000_000)))
        assert result.verified is True

    @pytest.mark.asyncio
    async def test_vrs_signature_form_accepted(self, tmp_path: Any) -> None:
        auth = _make_auth()
        raw = bytes.fromhex(auth.pop("signature"))
        auth["r"] = "0x" + raw[:32].hex()
        auth["s"] = "0x" + raw[32:64].hex()
        auth["v"] = raw[64]
        fac = _facilitator(tmp_path)
        result = await fac.verify(_payment(auth))
        assert result.verified is True, result.reason


class TestVerifyRejections:
    @pytest.mark.asyncio
    async def test_unsupported_asset(self, tmp_path: Any) -> None:
        fac = _facilitator(tmp_path)
        result = await fac.verify(_payment(_make_auth(), asset="DOGE"))
        assert result.verified is False
        assert "not supported" in result.reason

    @pytest.mark.asyncio
    async def test_non_eip3009_verification(self, tmp_path: Any) -> None:
        fac = _facilitator(tmp_path)
        from pry.payments.x402 import self_facilitator as sf

        entry = {"contract": USDC_BASE, "decimals": 6, "verification": "permit"}

        def fake_resolve(network: str, asset: str) -> dict[str, Any] | None:
            return entry

        monkey = pytest.MonkeyPatch()
        monkey.setattr(sf, "resolve_asset_entry", fake_resolve)
        try:
            result = await fac.verify(_payment(_make_auth()))
        finally:
            monkey.undo()
        assert result.verified is False
        assert "not EIP-3009" in result.reason

    @pytest.mark.asyncio
    async def test_missing_authorization(self, tmp_path: Any) -> None:
        fac = _facilitator(tmp_path)
        result = await fac.verify(_payment({}))
        assert result.verified is False
        assert "missing EIP-3009" in result.reason

    @pytest.mark.asyncio
    async def test_placeholder_wallet_fails_closed(self, tmp_path: Any) -> None:
        fac = Facilitator(pay_to="", nonce_path=tmp_path / "n.json")
        # Force the placeholder branch regardless of env defaults; auth keeps
        # a VALID to-address because the wallet check fires before it.
        fac.pay_to = "pry-default-wallet"
        result = await fac.verify(_payment(_make_auth()))
        assert result.verified is False
        assert "payTo" in result.reason or "wallet" in result.reason

    @pytest.mark.asyncio
    async def test_chain_id_mismatch(self, tmp_path: Any) -> None:
        fac = _facilitator(tmp_path)
        result = await fac.verify(_payment(_make_auth(chain_id=1)))
        assert result.verified is False
        assert "chainId" in result.reason

    @pytest.mark.asyncio
    async def test_unparseable_chain_id(self, tmp_path: Any) -> None:
        fac = _facilitator(tmp_path)
        result = await fac.verify(_payment(_make_auth(chain_id="zero")))
        assert result.verified is False
        assert "unparseable authorization chainId" in result.reason

    @pytest.mark.asyncio
    async def test_malformed_signature(self, tmp_path: Any) -> None:
        auth = _make_auth()
        auth["signature"] = "deadbeef"
        fac = _facilitator(tmp_path)
        result = await fac.verify(_payment(auth))
        assert result.verified is False
        assert "malformed EIP-3009 signature" in result.reason

    @pytest.mark.asyncio
    async def test_bad_from_address(self, tmp_path: Any) -> None:
        auth = _make_auth()
        auth["from"] = "not-an-address"
        fac = _facilitator(tmp_path)
        result = await fac.verify(_payment(auth))
        assert result.verified is False
        assert "'from'" in result.reason

    @pytest.mark.asyncio
    async def test_tampered_value_breaks_signer_recovery(self, tmp_path: Any) -> None:
        """Signing value=1.00 then claiming value=99 must fail signer check."""
        auth = _make_auth(tamper_value=99_000_000)
        fac = _facilitator(tmp_path)
        result = await fac.verify(_payment(auth))
        assert result.verified is False
        assert "signer" in result.reason

    @pytest.mark.asyncio
    async def test_underpayment_rejected(self, tmp_path: Any) -> None:
        fac = _facilitator(tmp_path)
        result = await fac.verify(_payment(_make_auth(value=100), amount_usd=5.0))
        assert result.verified is False
        assert "underpayment" in result.reason

    @pytest.mark.asyncio
    async def test_recipient_must_equal_payto(self, tmp_path: Any) -> None:
        stranger = "0x" + "c3" * 20
        fac = _facilitator(tmp_path)
        result = await fac.verify(_payment(_make_auth(to=stranger)))
        assert result.verified is False
        assert "recipient" in result.reason
        assert "payTo" in result.reason

    @pytest.mark.asyncio
    async def test_not_yet_valid(self, tmp_path: Any) -> None:
        future = int(time.time()) + 3600
        fac = _facilitator(tmp_path)
        result = await fac.verify(_payment(_make_auth(valid_after=future)))
        assert result.verified is False
        assert "not valid yet" in result.reason

    @pytest.mark.asyncio
    async def test_expired(self, tmp_path: Any) -> None:
        past = int(time.time()) - 60
        fac = _facilitator(tmp_path)
        result = await fac.verify(_payment(_make_auth(valid_before=past)))
        assert result.verified is False
        assert "expired" in result.reason

    @pytest.mark.asyncio
    async def test_zero_valid_before_means_no_expiry(self, tmp_path: Any) -> None:
        fac = _facilitator(tmp_path)
        result = await fac.verify(_payment(_make_auth(valid_before=0)))
        assert result.verified is True, result.reason

    @pytest.mark.asyncio
    async def test_replay_rejected_second_time(self, tmp_path: Any) -> None:
        fac = _facilitator(tmp_path)
        auth = _make_auth()
        first = await fac.verify(_payment(auth))
        assert first.verified is True
        second = await fac.verify(_payment(auth))
        assert second.verified is False
        assert "replay" in second.reason

    @pytest.mark.asyncio
    async def test_distinct_nonce_same_payment_ok(self, tmp_path: Any) -> None:
        fac = _facilitator(tmp_path)
        r1 = await fac.verify(_payment(_make_auth(nonce=bytes(32))))
        r2 = await fac.verify(_payment(_make_auth(nonce=b"\x01" + bytes(31))))
        assert r1.verified is True, r1.reason
        assert r2.verified is True, r2.reason


class TestSettlementTrackers:
    def test_settlement_id_prefers_payment_id(self, tmp_path: Any) -> None:
        fac = _facilitator(tmp_path)
        sid = fac._settlement_id({"payment_id": "abc123"})
        assert sid == "abc123"

    def test_settlement_id_nonce_fallback(self, tmp_path: Any) -> None:
        fac = _facilitator(tmp_path)
        auth = _make_auth()
        sid = fac._settlement_id({"authorization": auth, "network": NETWORK, "asset": "USDC"})
        assert sid.startswith("nonce:"), sid

    def test_settlement_id_empty_when_no_nonce(self, tmp_path: Any) -> None:
        fac = _facilitator(tmp_path)
        assert fac._settlement_id({"authorization": {}}) == ""

    def test_pending_lifecycle(self, tmp_path: Any) -> None:
        fac = _facilitator(tmp_path)
        assert fac.pending_count == 0
        fac._mark_pending("p1")
        assert fac.pending_count == 1
        fac._mark_settled("p1", "0xtx")
        assert fac.pending_count == 0
        assert fac._settled_txs["p1"] == "0xtx"

    def test_failed_lifecycle(self, tmp_path: Any) -> None:
        fac = _facilitator(tmp_path)
        fac._mark_pending("p2")
        fac._mark_pending_failed("p2", "rpc_error", "boom")
        assert fac.pending_count == 0
        entry = fac._pending_settlements["p2"]
        assert entry["status"] == "failed"
        assert entry["error_code"] == "rpc_error"

    def test_trim_bounds(self, tmp_path: Any) -> None:
        fac = Facilitator(pay_to=PAY_TO, nonce_path=tmp_path / "n.json", max_settled=2)
        for i in range(5):
            fac._mark_settled(f"p{i}", f"0x{i}")
        assert len(fac._settled_txs) == 2
        assert "p0" not in fac._settled_txs
