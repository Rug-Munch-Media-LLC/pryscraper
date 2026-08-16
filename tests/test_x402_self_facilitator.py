# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for the self-hosted x402 facilitator (EVM EIP-3009 verify + settle)."""

from __future__ import annotations

import json
import time

import httpx
import pytest
import respx
import rlp
from eth_keys.datatypes import PrivateKey
from eth_utils import keccak, to_checksum_address

from x402 import (
    FacilitatorRouter,
    set_facilitator_router,
)
from x402.scheme import X402_ASSET_USD_PER_UNIT, get_asset_usd_price
from x402.self_facilitator import (
    CHAIN_ID_BY_NETWORK,
    NonceStore,
    SelfFacilitator,
    VerifyResult,
    build_transfer_with_authorization_digest,
    domain_separator,
)

# Test wallet: the recipient the authorization must pay to.
PAY_TO = to_checksum_address("0x000000000000000000000000000000000000dEaD")
# Base USDC (EIP-3009) — canonical address from SUPPORTED_ASSETS.
BASE_USDC = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
# Ethereum USDC (EIP-3009).
ETH_USDC = "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48"
# Base USDT (permit2 — NOT eip3009).
BASE_USDT = "0xfde4C96c8593536E31F229EA8f37b2ADa2699bb2"

CHAIN_BASE = CHAIN_ID_BY_NETWORK["eip155:8453"]


def _sign_auth(
    private_key: PrivateKey,
    *,
    to: str = PAY_TO,
    value: int = 1000,
    valid_after: int | None = None,
    valid_before: int | None = None,
    nonce: bytes | None = None,
    chain_id: int = CHAIN_BASE,
    token: str = BASE_USDC,
    as_65: bool = False,
) -> dict:
    """Build a fully signed EIP-3009 transferWithAuthorization payment field."""
    now = int(time.time())
    valid_after = now - 60 if valid_after is None else valid_after
    valid_before = now + 3600 if valid_before is None else valid_before
    nonce = nonce or bytes([len(str(value)) % 256]) * 32
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
    auth: dict = {
        "from": from_addr,
        "to": to,
        "value": value,
        "validAfter": valid_after,
        "validBefore": valid_before,
        "nonce": "0x" + nonce.hex(),
    }
    if as_65:
        raw = sig.r.to_bytes(32, "big") + sig.s.to_bytes(32, "big") + bytes([sig.v])
        auth["signature"] = "0x" + raw.hex()
    else:
        auth["v"] = sig.v
        auth["r"] = "0x" + sig.r.to_bytes(32, "big").hex()
        auth["s"] = "0x" + sig.s.to_bytes(32, "big").hex()
    return auth


def _payment(
    auth: dict,
    *,
    network: str = "base",
    asset: str = "USDC",
    amount_usd: float = 0.001,
    payment_id: str = "p-test",
) -> dict:
    return {
        "payment_id": payment_id,
        "tx_hash": "0xabc",
        "network": network,
        "asset": asset,
        "amount_usd": amount_usd,
        "authorization": auth,
    }


def _facilitator(tmp_path, **kwargs) -> SelfFacilitator:
    kwargs.setdefault("pay_to", PAY_TO)
    kwargs.setdefault("nonce_path", str(tmp_path / "nonces.json"))
    return SelfFacilitator(**kwargs)


# ── EVM verify ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_verify_valid_eip3009(tmp_path) -> None:
    priv = PrivateKey(b"\x01" * 32)
    auth = _sign_auth(priv)
    fac = _facilitator(tmp_path)
    result = await fac.verify(_payment(auth))
    assert result.verified is True
    assert result.reason == ""
    assert result.signer == to_checksum_address(priv.public_key.to_address())
    assert result.amount_atomic == 1000
    assert result.asset == "USDC"
    assert result.network == "eip155:8453"


@pytest.mark.asyncio
async def test_verify_accepts_65_byte_signature(tmp_path) -> None:
    priv = PrivateKey(b"\x02" * 32)
    auth = _sign_auth(priv, as_65=True)
    fac = _facilitator(tmp_path)
    result = await fac.verify(_payment(auth))
    assert result.verified is True
    assert result.signer == to_checksum_address(priv.public_key.to_address())


@pytest.mark.asyncio
async def test_verify_underpayment_rejected(tmp_path) -> None:
    """A validly-signed authorization below the required price is refused."""
    priv = PrivateKey(b"\x03" * 32)
    auth = _sign_auth(priv, value=500)  # 0.0005 USDC < required 0.001
    fac = _facilitator(tmp_path)
    result = await fac.verify(_payment(auth, amount_usd=0.001))
    assert result.verified is False
    assert "underpayment" in result.reason


@pytest.mark.asyncio
async def test_verify_tampered_amount_rejected(tmp_path) -> None:
    """Tampering the amount AFTER signing changes the digest → signer mismatch."""
    priv = PrivateKey(b"\x04" * 32)
    auth = _sign_auth(priv, value=1000)
    auth = dict(auth, value=1_000_000)  # attacker bumps the value post-sign
    fac = _facilitator(tmp_path)
    result = await fac.verify(_payment(auth))
    assert result.verified is False
    assert "signer" in result.reason


@pytest.mark.asyncio
async def test_verify_replay_rejected(tmp_path) -> None:
    priv = PrivateKey(b"\x05" * 32)
    auth = _sign_auth(priv)
    fac = _facilitator(tmp_path)
    assert (await fac.verify(_payment(auth))).verified is True
    second = await fac.verify(_payment(auth))
    assert second.verified is False
    assert "replay" in second.reason


@pytest.mark.asyncio
async def test_verify_wrong_recipient_rejected(tmp_path) -> None:
    priv = PrivateKey(b"\x06" * 32)
    wrong_pay_to = to_checksum_address("0x1111111111111111111111111111111111111111")
    auth = _sign_auth(priv, to=wrong_pay_to)
    fac = _facilitator(tmp_path)
    result = await fac.verify(_payment(auth))
    assert result.verified is False
    assert "payTo" in result.reason


@pytest.mark.asyncio
async def test_verify_expired_rejected(tmp_path) -> None:
    priv = PrivateKey(b"\x07" * 32)
    auth = _sign_auth(priv, valid_before=int(time.time()) - 60)
    fac = _facilitator(tmp_path)
    result = await fac.verify(_payment(auth))
    assert result.verified is False
    assert "expired" in result.reason


@pytest.mark.asyncio
async def test_verify_wrong_chain_rejected(tmp_path) -> None:
    priv = PrivateKey(b"\x08" * 32)
    # Signed for Ethereum (chain 1) but presented on Base (8453).
    auth = _sign_auth(priv, chain_id=CHAIN_ID_BY_NETWORK["eip155:1"], token=ETH_USDC)
    fac = _facilitator(tmp_path)
    result = await fac.verify(_payment(auth, network="ethereum"))
    # Signer recovers fine but the domain separator encodes chain 1; the
    # authorization is only valid on ethereum — the recovered signer still
    # matches from (domain used chain 1), so the chain check on the auth
    # field is what protects cross-chain replay only when chainId is present.
    # The digest itself binds the chain, so a Base-domain replay attempt is
    # caught by the signer mismatch below.
    result_base = await fac.verify(_payment(auth, network="base"))
    assert result_base.verified is False
    assert result.verified is True  # valid on its own chain
    # Explicit chainId mismatch is rejected outright.
    auth_flagged = dict(auth, chainId=CHAIN_BASE)
    flagged = await fac.verify(_payment(auth_flagged, network="ethereum"))
    assert flagged.verified is False
    assert "chainId" in flagged.reason


@pytest.mark.asyncio
async def test_verify_non_eip3009_asset_rejected(tmp_path) -> None:
    """USDT (permit2) is not self-verifiable via EIP-3009 — fails closed."""
    priv = PrivateKey(b"\x09" * 32)
    auth = _sign_auth(priv, token=BASE_USDT)
    fac = _facilitator(tmp_path)
    result = await fac.verify(_payment(auth, asset="USDT"))
    assert result.verified is False
    assert "EIP-3009" in result.reason


@pytest.mark.asyncio
async def test_verify_missing_authorization_rejected(tmp_path) -> None:
    fac = _facilitator(tmp_path)
    result = await fac.verify({"network": "base", "asset": "USDC", "amount_usd": 0.001})
    assert result.verified is False
    assert "missing" in result.reason.lower()


@pytest.mark.asyncio
async def test_verify_placeholder_wallet_fails_closed(tmp_path) -> None:
    priv = PrivateKey(b"\x0a" * 32)
    auth = _sign_auth(priv)
    fac = SelfFacilitator(nonce_path=str(tmp_path / "n.json"))  # default placeholder wallet
    result = await fac.verify(_payment(auth))
    assert result.verified is False
    assert "payTo" in result.reason or "wallet" in result.reason


# ── Replay nonce store ───────────────────────────────────────────────────────


def test_nonce_store_persists_and_bounds(tmp_path) -> None:
    path = tmp_path / "nonces.json"
    store = NonceStore(path=path, max_size=2)
    assert store.mark_used("c:1") is True
    assert store.mark_used("c:2") is True
    assert store.mark_used("c:3") is True  # evicts c:1 (bounded)
    assert store.contains("c:2") is True
    assert store.contains("c:1") is False

    reloaded = NonceStore(path=path, max_size=2)
    assert reloaded.contains("c:2") is True
    assert reloaded.contains("c:3") is True
    assert reloaded.mark_used("c:2") is False  # replay survives restart


def test_nonce_store_clear(tmp_path) -> None:
    store = NonceStore(path=tmp_path / "nonces.json")
    store.mark_used("x")
    assert store.count == 1
    store.clear()
    assert store.count == 0
    assert store.mark_used("x") is True


# ── EVM settle (mocked RPC) ──────────────────────────────────────────────────


def _rpc_router(chain: int = CHAIN_BASE, tx_hash: str = "0x" + "ab" * 32):
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        method = body["method"]
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


@pytest.mark.asyncio
@respx.mock
async def test_settle_broadcasts_transfer_with_authorization(tmp_path) -> None:
    rpc = "https://rpc.invalid"
    respx.post(rpc).mock(side_effect=_rpc_router())
    fac = _facilitator(
        tmp_path,
        facilitator_key="0x" + "0f" * 32,
        rpc_url=rpc,
    )
    priv = PrivateKey(b"\x0b" * 32)
    auth = _sign_auth(priv)
    tx = await fac.settle(_payment(auth))
    assert tx == "0x" + "ab" * 32

    send = next(
        c
        for c in respx.calls
        if json.loads(c.request.content)["method"] == "eth_sendRawTransaction"
    )
    raw_hex = json.loads(send.request.content)["params"][0]
    decoded = rlp.decode(bytes.fromhex(raw_hex[2:]))
    # Legacy tx fields: [nonce, gasPrice, gasLimit, to, value, data, v, r, s]
    assert bytes(decoded[3]).hex() == BASE_USDC.lower().removeprefix("0x")  # to == token
    data = bytes(decoded[5])
    selector = keccak(
        text="transferWithAuthorization("
        "address,address,uint256,uint256,uint256,bytes32,uint8,bytes32,bytes32)"
    )[:4]
    assert data[:4] == selector
    v = int.from_bytes(bytes(decoded[6]), "big")
    assert v in (CHAIN_BASE * 2 + 35, CHAIN_BASE * 2 + 36)  # EIP-155
    # data embeds the recipient (payTo) at selector(4) + from(32) + 12..32.
    to_field = data[4 + 32 + 12 : 4 + 32 + 32]
    assert to_field.hex() == PAY_TO.lower().removeprefix("0x")


@pytest.mark.asyncio
@respx.mock
async def test_settle_preapproved_transfer_from(tmp_path) -> None:
    rpc = "https://rpc.invalid"
    respx.post(rpc).mock(side_effect=_rpc_router())
    fac = _facilitator(
        tmp_path,
        facilitator_key="0x" + "0f" * 32,
        rpc_url=rpc,
    )
    payment = {
        "payment_id": "p-approve",
        "network": "base",
        "asset": "USDC",
        "amount_usd": 0.001,
        "from": to_checksum_address(PrivateKey(b"\x0c" * 32).public_key.to_address()),
        "value": 1000,
        "approved": True,
    }
    tx = await fac.settle(payment)
    assert tx == "0x" + "ab" * 32
    send = next(
        c
        for c in respx.calls
        if json.loads(c.request.content)["method"] == "eth_sendRawTransaction"
    )
    raw_hex = json.loads(send.request.content)["params"][0]
    decoded = rlp.decode(bytes.fromhex(raw_hex[2:]))
    selector = keccak(text="transferFrom(address,address,uint256)")[:4]
    assert bytes(decoded[5])[:4] == selector


@pytest.mark.asyncio
@respx.mock
async def test_settle_not_settlable_without_authorization(tmp_path) -> None:
    rpc = "https://rpc.invalid"
    respx.post(rpc).mock(side_effect=_rpc_router())
    fac = _facilitator(
        tmp_path,
        facilitator_key="0x" + "0f" * 32,
        rpc_url=rpc,
    )
    payment = {"network": "base", "asset": "USDC", "amount_usd": 0.001}
    assert await fac.settle(payment) is None
    assert len(respx.calls) == 0  # no RPC traffic for non-settlable


@pytest.mark.asyncio
@respx.mock
async def test_settle_requires_facilitator_key(tmp_path) -> None:
    rpc = "https://rpc.invalid"
    respx.post(rpc).mock(side_effect=_rpc_router())
    fac = _facilitator(tmp_path, rpc_url=rpc)  # no key
    priv = PrivateKey(b"\x0d" * 32)
    auth = _sign_auth(priv)
    assert await fac.settle(_payment(auth)) is None
    assert len(respx.calls) == 0


@pytest.mark.asyncio
async def test_settle_requires_rpc(tmp_path) -> None:
    fac = _facilitator(tmp_path, facilitator_key="0x" + "0f" * 32)  # no rpc
    priv = PrivateKey(b"\x0e" * 32)
    auth = _sign_auth(priv)
    assert await fac.settle(_payment(auth)) is None


@pytest.mark.asyncio
@respx.mock
async def test_settle_refuses_wrong_chain(tmp_path) -> None:
    rpc = "https://rpc.invalid"
    respx.post(rpc).mock(side_effect=_rpc_router(chain=1))  # RPC says chain 1
    fac = _facilitator(
        tmp_path,
        facilitator_key="0x" + "0f" * 32,
        rpc_url=rpc,
    )
    priv = PrivateKey(b"\x0f" * 32)
    auth = _sign_auth(priv)
    assert await fac.settle(_payment(auth)) is None  # refuses Base payment
    methods = {json.loads(c.request.content)["method"] for c in respx.calls}
    assert methods == {"eth_chainId"}


# ── Router wiring ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
@respx.mock
async def test_router_self_hosted_uses_self_facilitator(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("x402.facilitator.X402_WALLET", PAY_TO)
    monkeypatch.setattr("x402.self_facilitator.X402_DIR", tmp_path)
    router = FacilitatorRouter(self_hosted=True)
    priv = PrivateKey(b"\x10" * 32)
    auth = _sign_auth(priv)
    router.submit_authorization("p1", auth)

    result = await router.verify("p1", "0xabc", "base", "USDC", 0.001)
    assert result["verified"] is True
    assert result["facilitator"] == "self-hosted"
    assert result["signer"] == to_checksum_address(priv.public_key.to_address())
    assert len(respx.calls) == 0  # no external facilitator was contacted


@pytest.mark.asyncio
@respx.mock
async def test_router_self_hosted_env_flag(monkeypatch) -> None:
    """The env-driven default flips the router into self-hosted mode."""
    monkeypatch.setattr("x402.facilitator.X402_SELF_FACILITATE", True)
    router = FacilitatorRouter()
    assert router.self_hosted is True
    router2 = FacilitatorRouter(self_hosted=False)
    assert router2.self_hosted is False


@pytest.mark.asyncio
@respx.mock
async def test_router_default_uses_external_facilitator() -> None:
    verify_url = "https://x402.org/facilitator/verify"
    respx.post(verify_url).mock(return_value=httpx.Response(200, json={"isValid": True}))
    router = FacilitatorRouter()  # self_hosted defaults False (off)
    result = await router.verify("p-ext", "0xabc", "base", "USDC", 0.001)
    assert result["verified"] is True
    assert result["facilitator"] == "coinbase"


@pytest.mark.asyncio
async def test_router_register_facilitator_extension() -> None:
    """Solana/TRON extension point: a registered impl routes verify+settle."""

    class FakeSolanaFacilitator:
        def __init__(self) -> None:
            self.verifies = 0
            self.settles = 0

        async def verify(self, payment: dict) -> VerifyResult:
            self.verifies += 1
            return VerifyResult(True, reason="", network="solana:mainnet", asset="USDC")

        async def settle(self, payment: dict) -> str | None:
            self.settles += 1
            return "fake-solana-tx"

    router = FacilitatorRouter()
    fake = FakeSolanaFacilitator()
    router.register_facilitator("solana", fake)

    result = await router.verify("p-sol", "tx-sol", "solana:mainnet", "USDC", 0.001)
    assert result["verified"] is True
    assert fake.verifies == 1
    settled = await router.settle("p-sol", "tx-sol", "solana:mainnet", "USDC", 0.001)
    assert settled["success"] is True
    assert settled["transaction"] == "fake-solana-tx"
    assert fake.settles == 1


@pytest.mark.asyncio
async def test_module_register_facilitator_on_global_router() -> None:
    from x402 import register_facilitator

    class FakeTronFacilitator:
        async def verify(self, payment: dict) -> VerifyResult:
            return VerifyResult(True, reason="", network="tron:mainnet")

        async def settle(self, payment: dict) -> str | None:
            return "fake-tron-tx"

    fresh = FacilitatorRouter()
    set_facilitator_router(fresh)
    try:
        register_facilitator("tron:mainnet", FakeTronFacilitator())
        result = await fresh.verify("p-tron", "tx-tron", "tron:mainnet", "USDT", 0.001)
        assert result["verified"] is True
    finally:
        set_facilitator_router(FacilitatorRouter())


# ── Oracle hook ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_oracle_hook_static_default(monkeypatch) -> None:
    monkeypatch.delenv("PRY_X402_ORACLE_URL", raising=False)
    eth = await get_asset_usd_price("ETH", "ethereum")
    assert eth.usd == X402_ASSET_USD_PER_UNIT["ETH"]
    assert eth.source == "static-default"
    usdc = await get_asset_usd_price("USDC")
    assert usdc.usd == 1.0
    assert usdc.source == "stablecoin"


@pytest.mark.asyncio
@respx.mock
async def test_oracle_hook_uses_live_price(monkeypatch) -> None:
    monkeypatch.setenv("PRY_X402_ORACLE_URL", "https://oracle.invalid")
    respx.get("https://oracle.invalid/price/ETH").mock(
        return_value=httpx.Response(200, json={"usd": 3010.5})
    )
    quote = await get_asset_usd_price("ETH", "ethereum")
    assert quote.usd == 3010.5
    assert quote.source == "oracle"


@pytest.mark.asyncio
@respx.mock
async def test_oracle_hook_falls_back_on_error(monkeypatch) -> None:
    monkeypatch.setenv("PRY_X402_ORACLE_URL", "https://oracle.invalid")
    respx.get("https://oracle.invalid/price/ETH").mock(side_effect=httpx.ConnectError("down"))
    quote = await get_asset_usd_price("ETH")
    assert quote.usd == X402_ASSET_USD_PER_UNIT["ETH"]
    assert quote.source == "static-default"


@pytest.mark.asyncio
@respx.mock
async def test_oracle_hook_falls_back_on_bad_shape(monkeypatch) -> None:
    monkeypatch.setenv("PRY_X402_ORACLE_URL", "https://oracle.invalid")
    respx.get("https://oracle.invalid/price/ETH").mock(
        return_value=httpx.Response(200, json={"weird": "shape"})
    )
    quote = await get_asset_usd_price("ETH")
    assert quote.source == "static-default"


# ── EIP-712 digest conformance ───────────────────────────────────────────────


def test_digest_matches_independent_eip712_computation() -> None:
    """Anchor the digest computation to the EIP-712/EIP-3009 spec layout."""
    from_address = to_checksum_address(PrivateKey(b"\x11" * 32).public_key.to_address())
    to_address = PAY_TO
    value = 1234
    valid_after = 100
    valid_before = 200
    nonce = b"\xde" * 32
    chain_id = CHAIN_BASE
    token = BASE_USDC
    name, version = "USD Coin", "2"

    def abi_uint(x: int) -> bytes:
        return x.to_bytes(32, "big")

    def abi_addr(a: str) -> bytes:
        return b"\x00" * 12 + bytes.fromhex(a[2:])

    domain_typehash = keccak(
        text="EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)"
    )
    transfer_typehash = keccak(
        text="TransferWithAuthorization("
        "address from,address to,uint256 value,uint256 validAfter,"
        "uint256 validBefore,bytes32 nonce)"
    )
    expected_domain = keccak(
        domain_typehash
        + keccak(text=name)
        + keccak(text=version)
        + abi_uint(chain_id)
        + abi_addr(token)
    )
    assert domain_separator(name, version, chain_id, token) == expected_domain

    expected_struct = keccak(
        transfer_typehash
        + abi_addr(from_address)
        + abi_addr(to_address)
        + abi_uint(value)
        + abi_uint(valid_after)
        + abi_uint(valid_before)
        + nonce
    )
    expected_digest = keccak(b"\x19\x01" + expected_domain + expected_struct)
    actual = build_transfer_with_authorization_digest(
        from_address=from_address,
        to_address=to_address,
        value=value,
        valid_after=valid_after,
        valid_before=valid_before,
        nonce=nonce,
        chain_id=chain_id,
        token_address=token,
        name=name,
        version=version,
    )
    assert actual == expected_digest


def test_supported_eip3009_assets() -> None:
    """Every eip3009 SUPPORTED_ASSETS entry has a resolvable chain id."""
    from x402.scheme import SUPPORTED_ASSETS

    seen = 0
    for network_id, assets in SUPPORTED_ASSETS.items():
        for _asset, entry in assets.items():
            if entry.get("verification") != "eip3009":
                continue
            seen += 1
            assert CHAIN_ID_BY_NETWORK[network_id] > 0
            assert entry.get("contract")
    assert seen >= 2  # Base USDC + Ethereum USDC (at minimum)
