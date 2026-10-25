"""Tests for x402/facilitator.py — FacilitatorRouter, multi-provider fallback."""
from tests.x402._x402_facilitator_support import _eip7702_ok, router  # noqa: F401
from pry.payments.x402.facilitator import _eip7702_rpc_key


def test_eip7702_rpc_key_short_name_passthrough():
    """A legacy short name that has an RPC entry resolves to itself."""
    assert _eip7702_rpc_key("base") == "base"
    assert _eip7702_rpc_key("ethereum") == "ethereum"
    assert _eip7702_rpc_key("base-sepolia") == "base-sepolia"
def test_eip7702_rpc_key_caip2_resolves_to_short_name():
    """CAIP-2 IDs (what the verify flow actually receives) map to RPC keys.
    Regression: EIP7702_RPC is keyed by short names but the API/manifest
    surface speaks CAIP-2 — without this map the EIP-7702 on-chain fallback
    never ran for any EVM chain.
    """
    assert _eip7702_rpc_key("eip155:8453") == "base"
    assert _eip7702_rpc_key("eip155:1") == "ethereum"
    assert _eip7702_rpc_key("eip155:137") == "polygon"
    assert _eip7702_rpc_key("eip155:84532") == "base-sepolia"
def test_eip7702_rpc_key_case_insensitive_short_name():
    """Uppercase short names normalize through the CAIP-2 table."""
    assert _eip7702_rpc_key("BASE") == "base"
    assert _eip7702_rpc_key("Base") == "base"
def test_eip7702_rpc_key_non_evm_returns_none():
    """Solana/TRON have no EIP-7702 RPC — must resolve to None."""
    assert _eip7702_rpc_key("solana:mainnet") is None
    assert _eip7702_rpc_key("solana") is None
    assert _eip7702_rpc_key("tron:mainnet") is None
def test_eip7702_rpc_key_unknown_chain_returns_none():
    """Unknown networks and RPC-less map entries fail closed to None."""
    assert _eip7702_rpc_key("eip155:9999") is None
    assert _eip7702_rpc_key("nonsense") is None
    assert _eip7702_rpc_key("") is None
    # ethereum-sepolia is in the reverse map but has NO EIP7702_RPC entry —
    # the resolver must not claim support for it.
    assert _eip7702_rpc_key("ethereum-sepolia") is None
    assert _eip7702_rpc_key("eip155:11155111") is None
