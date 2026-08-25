# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Production-readiness tests for the x402 surface.

Closes the gaps the readiness lane flagged:
- live price oracle (CoinGecko ``/simple/price``) with async cache + TTL and
  static fallback (no provider configured → static-default, backwards
  compatible with the pre-existing test contract);
- ``/v1/x402/health`` probing facilitator mode/readiness + oracle reachability
  + per-network verification status + settlement counters;
- per-network ``verification_status`` ("live" vs "live")
  surfaced on the health + pricing endpoints;
- settlement hardening: idempotency (never double-submits), a bounded
  pending-settlement tracker, and an error taxonomy (insufficient gas, nonce
  conflict, RPC timeout);
- EVM self-facilitator verify → settle end-to-end on a MOCKED chain
  (signature recovery, nonce check, mock-RPC broadcast).
"""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING

import httpx
import pytest
import respx
from eth_keys.datatypes import PrivateKey
from eth_utils import to_checksum_address

if TYPE_CHECKING:
    from collections.abc import Generator

from pry.api.routers.x402 import x402_health
from pry.payments.x402 import (
    FacilitatorRouter,
    SelfFacilitator,
    SettleErrorCode,
    X402Handler,
    set_facilitator_router,
)
from pry.payments.x402.scheme import (
    COINGECKO_SIMPLE_PRICE_URL,
    SUPPORTED_ASSETS,
    X402_ASSET_USD_PER_UNIT,
    clear_price_cache,
    get_asset_usd_price,
    network_verification_status,
    probe_oracle,
)
from pry.payments.x402.self_facilitator import (
    CHAIN_ID_BY_NETWORK,
    build_transfer_with_authorization_digest,
)

# Test wallet: the recipient the authorization must pay to.
PAY_TO = to_checksum_address("0x000000000000000000000000000000000000dEaD")
# Base USDC (EIP-3009) — canonical address from SUPPORTED_ASSETS.
BASE_USDC = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
CHAIN_BASE = CHAIN_ID_BY_NETWORK["eip155:8453"]

CG_URL_ETH = f"{COINGECKO_SIMPLE_PRICE_URL}?ids=ethereum&vs_currencies=usd"


@pytest.fixture(autouse=True)
def _clear_oracle_cache() -> Generator[None, None, None]:
    """Isolate the module-level oracle cache between tests in this file."""
    clear_price_cache()
    yield
    clear_price_cache()


# ── helpers ──────────────────────────────────────────────────────────────────


def _sign_auth(
    private_key: PrivateKey,
    *,
    to: str = PAY_TO,
    value: int = 1000,
    valid_before: int | None = None,
    nonce: bytes | None = None,
    chain_id: int = CHAIN_BASE,
    token: str = BASE_USDC,
) -> dict:
    """Build a fully signed EIP-3009 transferWithAuthorization payment field."""
    now = int(time.time())
    valid_after = now - 60
    valid_before = now + 3600 if valid_before is None else valid_before
    nonce = nonce or bytes([7]) * 32
    from_addr = to_checksum_address(private_key.public_key.to_address())
    digest = build_transfer_with_authorization_digest(
        from_address=from_addr,
        to_address=to,
        value=value,
        valid_after=valid_after,
        valid_before=valid_before,
        nonce=nonce,
        chain_id=chain_id,
        token_address=token,
    )
    sig = private_key.sign_msg_hash(digest)
    raw = sig.r.to_bytes(32, "big") + sig.s.to_bytes(32, "big") + bytes([sig.v])
    return {
        "from": from_addr,
        "to": to,
        "value": value,
        "validAfter": valid_after,
        "validBefore": valid_before,
        "nonce": "0x" + nonce.hex(),
        "signature": "0x" + raw.hex(),
    }


def _payment(
    auth: dict,
    *,
    network: str = "base",
    asset: str = "USDC",
    amount_usd: float = 0.001,
    payment_id: str = "p-ready",
) -> dict:
    return {
        "payment_id": payment_id,
        "tx_hash": "0xabc",
        "network": network,
        "asset": asset,
        "amount_usd": amount_usd,
        "authorization": auth,
    }


def _rpc_router(
    chain: int = CHAIN_BASE,
    tx_hash: str = "0x" + "cd" * 32,
    send_error: dict | None = None,
):
    """Mock JSON-RPC handler: eth_chainId / count / gas / sendRawTransaction."""

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        method = body["method"]
        if send_error is not None and method == "eth_sendRawTransaction":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "error": send_error})
        if method == "eth_chainId":
            result = hex(chain)
        elif method == "eth_getTransactionCount":
            result = "0x0"
        elif method == "eth_estimateGas":
            result = hex(60_000)
        elif method == "eth_gasPrice":
            result = "0x3b9aca00"  # 1 gwei
        elif method == "eth_sendRawTransaction":
            result = tx_hash
        else:
            result = None
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": result})

    return handler


def _facilitator(tmp_path, **kwargs) -> SelfFacilitator:
    kwargs.setdefault("pay_to", PAY_TO)
    kwargs.setdefault("nonce_path", str(tmp_path / "nonces.json"))
    return SelfFacilitator(**kwargs)


def _send_calls() -> list:
    return [
        c
        for c in respx.calls
        if json.loads(c.request.content)["method"] == "eth_sendRawTransaction"
    ]


# ── Live oracle (CoinGecko /simple/price) ────────────────────────────────────


@pytest.mark.asyncio
@respx.mock
async def test_oracle_coingecko_live_fetch(monkeypatch) -> None:
    monkeypatch.setenv("PRY_X402_ORACLE_SOURCE", "coingecko")
    respx.get(CG_URL_ETH).mock(return_value=httpx.Response(200, json={"ethereum": {"usd": 3100.5}}))
    quote = await get_asset_usd_price("ETH", "ethereum")
    assert quote.usd == 3100.5
    assert quote.source == "oracle"


@pytest.mark.asyncio
@respx.mock
async def test_oracle_cache_avoids_second_network_call(monkeypatch) -> None:
    monkeypatch.setenv("PRY_X402_ORACLE_SOURCE", "coingecko")
    respx.get(CG_URL_ETH).mock(return_value=httpx.Response(200, json={"ethereum": {"usd": 3100.5}}))
    first = await get_asset_usd_price("ETH", "ethereum")
    second = await get_asset_usd_price("ETH", "ethereum")
    assert first.usd == second.usd == 3100.5
    assert len(respx.calls) == 1  # async cache + TTL: no duplicate fetch


@pytest.mark.asyncio
@respx.mock
async def test_oracle_cache_ttl_expiry_refetches(monkeypatch) -> None:
    monkeypatch.setenv("PRY_X402_ORACLE_SOURCE", "coingecko")
    monkeypatch.setenv("PRY_X402_ORACLE_TTL", "0")  # TTL 0 → every call refetches
    respx.get(CG_URL_ETH).mock(return_value=httpx.Response(200, json={"ethereum": {"usd": 3100.5}}))
    await get_asset_usd_price("ETH", "ethereum")
    await get_asset_usd_price("ETH", "ethereum")
    assert len(respx.calls) == 2


@pytest.mark.asyncio
@respx.mock
async def test_oracle_falls_back_on_coingecko_failure(monkeypatch) -> None:
    monkeypatch.setenv("PRY_X402_ORACLE_SOURCE", "coingecko")
    respx.get(CG_URL_ETH).mock(side_effect=httpx.ConnectError("coingecko down"))
    quote = await get_asset_usd_price("ETH", "ethereum")
    assert quote.usd == X402_ASSET_USD_PER_UNIT["ETH"]
    assert quote.source == "static-default"


@pytest.mark.asyncio
async def test_oracle_static_default_when_no_provider(monkeypatch) -> None:
    monkeypatch.delenv("PRY_X402_ORACLE_URL", raising=False)
    monkeypatch.delenv("PRY_X402_ORACLE_SOURCE", raising=False)
    quote = await get_asset_usd_price("ETH", "ethereum")
    assert quote.usd == X402_ASSET_USD_PER_UNIT["ETH"]
    assert quote.source == "static-default"


@pytest.mark.asyncio
@respx.mock
async def test_oracle_clear_cache(monkeypatch) -> None:
    monkeypatch.setenv("PRY_X402_ORACLE_SOURCE", "coingecko")
    respx.get(CG_URL_ETH).mock(return_value=httpx.Response(200, json={"ethereum": {"usd": 3100.5}}))
    await get_asset_usd_price("ETH", "ethereum")
    clear_price_cache()
    await get_asset_usd_price("ETH", "ethereum")
    assert len(respx.calls) == 2  # cleared → refetch


@pytest.mark.asyncio
@respx.mock
async def test_probe_oracle_live_and_static(monkeypatch) -> None:
    monkeypatch.setenv("PRY_X402_ORACLE_SOURCE", "coingecko")
    respx.get(CG_URL_ETH).mock(return_value=httpx.Response(200, json={"ethereum": {"usd": 3100.5}}))
    reachable, source = await probe_oracle()
    assert reachable is True
    assert source == "coingecko"

    monkeypatch.delenv("PRY_X402_ORACLE_SOURCE", raising=False)
    monkeypatch.delenv("PRY_X402_ORACLE_URL", raising=False)
    clear_price_cache()
    reachable, source = await probe_oracle()
    assert reachable is False
    assert source == "static-default"


# ── Per-network verification status ──────────────────────────────────────────


def test_network_verification_status_labels() -> None:
    assert network_verification_status("eip155:8453") == "live"
    assert network_verification_status("eip155:1") == "live"
    assert network_verification_status("base") == "live"
    assert network_verification_status("solana:mainnet") == "live"
    assert network_verification_status("solana") == "live"
    assert network_verification_status("tron:mainnet") == "scaffolded:needs_facilitator"
    assert network_verification_status("") == "unknown"


def test_stats_expose_verification_status_by_network() -> None:
    stats = X402Handler().get_stats()
    by_network = stats["verification_status_by_network"]
    assert set(by_network) == set(SUPPORTED_ASSETS.keys())
    assert by_network["eip155:8453"] == "live"
    assert by_network["solana:mainnet"] == "live"
    assert by_network["tron:mainnet"] == "scaffolded:needs_facilitator"


# ── /v1/x402/health ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_health_self_hosted_ready(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("pry.payments.x402.facilitator.X402_WALLET", PAY_TO)
    monkeypatch.setattr(
        "pry.payments.x402.facilitator.X402_SELF_FACILITATOR_RPC", "https://rpc.invalid"
    )
    router = FacilitatorRouter(self_hosted=True)
    set_facilitator_router(router)
    try:

        async def fake_probe() -> tuple[bool, str]:
            return True, "coingecko"

        monkeypatch.setattr("pry.payments.x402.scheme.probe_oracle", fake_probe)
        body = await x402_health()
        assert body["status"] == "ok"
        assert body["facilitator"] == {
            "mode": "self_hosted",
            "ready": True,
            "wallet_configured": True,
        }
        assert body["oracle"] == {"reachable": True, "source": "coingecko"}
        assert "eip155:8453" in body["supported_networks"]
        assert "solana:mainnet" in body["supported_networks"]
        assert body["supported_assets_count"] == sum(len(a) for a in SUPPORTED_ASSETS.values())
        assert body["verification_status"]["eip155:8453"] == "live"
        assert body["verification_status"]["solana:mainnet"] == "live"
        assert body["settlement"]["nonces_seen"] >= 0
        assert body["settlement"]["pending"] >= 0
    finally:
        set_facilitator_router(FacilitatorRouter())


@pytest.mark.asyncio
async def test_health_external_mode_and_wallet_not_configured(monkeypatch) -> None:
    router = FacilitatorRouter(self_hosted=False)
    set_facilitator_router(router)
    try:

        async def fake_probe() -> tuple[bool, str]:
            return False, "static-default"

        monkeypatch.setattr("pry.payments.x402.scheme.probe_oracle", fake_probe)
        # Force the placeholder wallet — the ambient value may be a real
        # gopass secret in dev environments, so assert on explicit state.
        monkeypatch.setattr("pry.payments.x402.facilitator.X402_WALLET", "pry-default-wallet")
        body = await x402_health()
        assert body["facilitator"]["mode"] == "external"
        assert body["facilitator"]["wallet_configured"] is False
        assert body["facilitator"]["ready"] is False
        assert body["oracle"] == {"reachable": False, "source": "static-default"}

        # Configured wallet → external mode ready (default facilitators exist).
        monkeypatch.setattr("pry.payments.x402.facilitator.X402_WALLET", PAY_TO)
        body = await x402_health()
        assert body["facilitator"]["wallet_configured"] is True
        assert body["facilitator"]["ready"] is True
    finally:
        set_facilitator_router(FacilitatorRouter())


# ── Settlement hardening ─────────────────────────────────────────────────────


@pytest.mark.asyncio
@respx.mock
async def test_settle_idempotent_returns_existing_hash(tmp_path) -> None:
    """A settle for an already-settled payment never double-submits."""
    rpc = "https://rpc.invalid"
    respx.post(rpc).mock(side_effect=_rpc_router())
    fac = _facilitator(
        tmp_path,
        facilitator_key="0x" + "0f" * 32,
        rpc_url=rpc,
    )
    priv = PrivateKey(b"\x11" * 32)
    auth = _sign_auth(priv, nonce=b"\xaa" * 32)
    first = await fac.settle(_payment(auth, payment_id="p-idem"))
    assert first == "0x" + "cd" * 32
    assert len(_send_calls()) == 1

    second = await fac.settle(_payment(auth, payment_id="p-idem"))
    assert second == first  # existing tx hash returned
    assert len(_send_calls()) == 1  # never re-broadcast

    # Bounded tracker: the settled payment is no longer "pending".
    assert fac.pending_count == 0


@pytest.mark.asyncio
@respx.mock
async def test_settle_idempotent_by_nonce_without_payment_id(tmp_path) -> None:
    rpc = "https://rpc.invalid"
    respx.post(rpc).mock(side_effect=_rpc_router())
    fac = _facilitator(
        tmp_path,
        facilitator_key="0x" + "0f" * 32,
        rpc_url=rpc,
    )
    priv = PrivateKey(b"\x12" * 32)
    auth = _sign_auth(priv, nonce=b"\xbb" * 32)
    payment = _payment(auth, payment_id="")
    first = await fac.settle(payment)
    assert first == "0x" + "cd" * 32
    second = await fac.settle(_payment(auth, payment_id=""))
    assert second == first
    assert len(_send_calls()) == 1


@pytest.mark.asyncio
@respx.mock
async def test_settle_insufficient_gas_classified(tmp_path) -> None:
    rpc = "https://rpc.invalid"
    respx.post(rpc).mock(
        side_effect=_rpc_router(
            send_error={"code": -32000, "message": "insufficient funds for gas * price + value"}
        )
    )
    fac = _facilitator(
        tmp_path,
        facilitator_key="0x" + "0f" * 32,
        rpc_url=rpc,
    )
    priv = PrivateKey(b"\x13" * 32)
    outcome = await fac.settle_with_details(_payment(_sign_auth(priv)))
    assert outcome.success is False
    assert outcome.error_code == SettleErrorCode.INSUFFICIENT_GAS.value
    assert "insufficient funds" in outcome.error_detail
    assert await fac.settle(_payment(_sign_auth(priv))) is None  # legacy contract


@pytest.mark.asyncio
@respx.mock
async def test_settle_nonce_conflict_classified(tmp_path) -> None:
    rpc = "https://rpc.invalid"
    respx.post(rpc).mock(
        side_effect=_rpc_router(send_error={"code": -32000, "message": "nonce too low"})
    )
    fac = _facilitator(
        tmp_path,
        facilitator_key="0x" + "0f" * 32,
        rpc_url=rpc,
    )
    priv = PrivateKey(b"\x14" * 32)
    outcome = await fac.settle_with_details(_payment(_sign_auth(priv)))
    assert outcome.success is False
    assert outcome.error_code == SettleErrorCode.NONCE_CONFLICT.value
    assert "nonce" in outcome.error_detail


@pytest.mark.asyncio
@respx.mock
async def test_settle_rpc_timeout_classified(tmp_path) -> None:
    rpc = "https://rpc.invalid"

    def raise_timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("read timed out")

    respx.post(rpc).mock(side_effect=raise_timeout)
    fac = _facilitator(
        tmp_path,
        facilitator_key="0x" + "0f" * 32,
        rpc_url=rpc,
    )
    priv = PrivateKey(b"\x15" * 32)
    outcome = await fac.settle_with_details(_payment(_sign_auth(priv)))
    assert outcome.success is False
    assert outcome.error_code == SettleErrorCode.RPC_TIMEOUT.value
    assert "timed out" in outcome.error_detail


# ── EVM self-facilitator verify → settle (mocked chain) ──────────────────────


@pytest.mark.asyncio
@respx.mock
async def test_evm_verify_settle_end_to_end_mocked_chain(tmp_path) -> None:
    """Prove the full EVM self-facilitator flow on a MOCKED chain.

    Recover the signature locally, validate nonce/amount/recipient/window,
    then broadcast settlement to a mock RPC and return a tx hash — all
    without touching a live chain.
    """
    rpc = "https://rpc.invalid"
    respx.post(rpc).mock(side_effect=_rpc_router())
    fac = _facilitator(
        tmp_path,
        facilitator_key="0x" + "0f" * 32,
        rpc_url=rpc,
    )
    priv = PrivateKey(b"\x16" * 32)
    auth = _sign_auth(priv, nonce=b"\xcc" * 32)
    payment = _payment(auth, payment_id="p-e2e")

    # 1. verify: local ecrecover + nonce check, no network traffic.
    result = await fac.verify(payment)
    assert result.verified is True
    assert result.signer == to_checksum_address(priv.public_key.to_address())
    assert result.amount_atomic == 1000
    assert fac.nonces.count == 1  # nonce recorded for replay protection

    # 2. settle: broadcast the same authorization to the mock RPC.
    tx = await fac.settle(payment)
    assert tx == "0x" + "cd" * 32
    assert len(_send_calls()) == 1

    # 3. A repeated verify is rejected (replay) — the flow is idempotent.
    replay = await fac.verify(payment)
    assert replay.verified is False
    assert "replay" in replay.reason

    # 4. Re-settling returns the existing hash, never double-submits.
    again = await fac.settle(payment)
    assert again == tx
    assert len(_send_calls()) == 1
