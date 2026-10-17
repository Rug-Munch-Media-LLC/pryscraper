# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Fuzz tests for x402.scheme network/asset resolution helpers.

Invariants checked here:

* ``normalize_network_id`` is total: for ANY string it returns a string and
  never raises (no KeyError, no AttributeError, no UnicodeError).
* ``resolve_asset_entry`` is total: for ANY (network, asset) strings it
  returns ``None`` or a dict and never raises — malformed CAIP-2 ids
  (``"eip155:"``, ``"eip155:8453:extra"``, ``"EIP155:8453"``, whitespace,
  unicode, …) must not blow up the acceptance-table lookup.
* Known legacy network names and every canonical CAIP-2 id in
  ``SUPPORTED_ASSETS`` resolve to the documented entries.
"""

import string

import pytest
from hypothesis import HealthCheck, given, settings, strategies as st

from pry.payments.x402.scheme import (
    CAIP2_NETWORK_IDS,
    SUPPORTED_ASSETS,
    network_family,
    normalize_network_id,
    resolve_asset_entry,
)

# Alphabet covering every weird character a hostile client could put in a
# CAIP-2 id: separators, brackets, unicode, whitespace, control-ish chars.
_NETWORK_ALPHABET = string.ascii_letters + string.digits + ":-._/\\[]@% \t" + "éü中"


@settings(max_examples=500, deadline=2000, suppress_health_check=[HealthCheck.too_slow])
@given(network=st.text(max_size=200))
def test_normalize_network_id_never_raises(network: str) -> None:
    """normalize_network_id is total — returns a str for ANY input."""
    result = normalize_network_id(network)
    assert isinstance(result, str)


@settings(max_examples=500, deadline=2000, suppress_health_check=[HealthCheck.too_slow])
@given(network=st.text(alphabet=_NETWORK_ALPHABET, max_size=120))
def test_normalize_network_id_weird_caip2_never_raises(network: str) -> None:
    """Malformed CAIP-2 spellings (extra colons, unicode, whitespace, …) are total."""
    result = normalize_network_id(network)
    assert isinstance(result, str)


@settings(max_examples=500, deadline=2000, suppress_health_check=[HealthCheck.too_slow])
@given(
    network=st.text(alphabet=_NETWORK_ALPHABET, max_size=120),
    asset=st.text(alphabet=string.ascii_letters + string.digits + "_.- ", max_size=40),
)
def test_resolve_asset_entry_never_raises(network: str, asset: str) -> None:
    """resolve_asset_entry is total — None or dict, never an exception."""
    entry = resolve_asset_entry(network, asset)
    assert entry is None or isinstance(entry, dict)


@settings(max_examples=500, deadline=2000, suppress_health_check=[HealthCheck.too_slow])
@given(network=st.text(max_size=300))
def test_resolve_asset_entry_any_string_never_raises(network: str) -> None:
    """Even arbitrary binary-ish strings (all code points) must not crash."""
    entry = resolve_asset_entry(network, "USDC")
    assert entry is None or isinstance(entry, dict)


@pytest.mark.parametrize(
    "network",
    [
        "eip155:",  # missing chain id
        "eip155:8453:extra",  # too many segments
        ":8453",  # missing namespace
        ":",  # bare colon
        "EIP155:8453",  # uppercase namespace
        "Eip155:8453",  # mixed case
        "eip155:8453 ",  # trailing whitespace
        " eip155:8453",  # leading whitespace
        "eip155:0x2105",  # hex chain id spelling
        "solana:",  # missing network segment
        "solana:mainnet:extra",  # too many segments
        "tron:",  # missing network segment
        "bip122:000000000019d6689c085ae165831e93",  # valid-format, unsupported
        "cosmos:cosmoshub-4",  # valid-format, unsupported
    ],
)
def test_malformed_caip2_ids_never_raise(network: str) -> None:
    """Malformed/unsupported CAIP-2 ids resolve to None (or passthrough str)."""
    assert isinstance(normalize_network_id(network), str)
    entry = resolve_asset_entry(network, "USDC")
    assert entry is None or isinstance(entry, dict)
    # Unsupported families report unknown without raising.
    assert isinstance(network_family(network), str)


def test_legacy_network_names_map_to_caip2() -> None:
    """Every documented legacy name maps to its canonical CAIP-2 id."""
    for legacy, caip2 in CAIP2_NETWORK_IDS.items():
        assert normalize_network_id(legacy) == caip2
        assert normalize_network_id(legacy.upper()) == caip2


def test_every_supported_asset_entry_resolves_case_insensitively() -> None:
    """Every canonical (network, asset) pair resolves, with any asset case."""
    for network_id, assets in SUPPORTED_ASSETS.items():
        for asset in assets:
            entry = resolve_asset_entry(network_id, asset)
            assert entry is not None
            # Case must not change the resolved entry (same mint/address).
            assert entry == resolve_asset_entry(network_id, asset.lower())
            assert entry == resolve_asset_entry(network_id, asset.upper())


def test_unknown_pair_returns_none() -> None:
    assert resolve_asset_entry("eip155:8453", "BOGUS") is None
    assert resolve_asset_entry("bogus:chain", "USDC") is None
    assert resolve_asset_entry("", "USDC") is None
    assert resolve_asset_entry("eip155:8453", "") is None
