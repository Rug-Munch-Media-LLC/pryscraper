# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Deep tests for self-facilitator primitives (payment-critical).

Targets the previously-uncovered pure paths: settle-error classification,
EIP-3009 encoding helpers, signature parsing (65-byte hex / v-r-s forms,
v normalization), chain-id resolution, and NonceStore replay-protection
persistence/eviction. All offline - no RPC, no network.
"""

from __future__ import annotations

import json
import logging
from typing import Any, ClassVar

import httpx
import pytest

from pry.payments.x402.self_facilitator import (
    CHAIN_ID_BY_NETWORK,
    NonceStore,
    SettleErrorCode,
    _chain_id_for,
    _classify_settle_error,
    _encode_address,
    _encode_bytes32,
    _encode_nonce,
    _encode_uint,
    _nonce_hex,
    _parse_signature,
    _signature_from_bytes,
    _to_int,
    build_transfer_with_authorization_digest,
    domain_separator,
    transfer_with_authorization_struct_hash,
)

# ── settle-error classification ──────────────────────────────────────────────


class TestClassifySettleError:
    def test_timeout_classified(self) -> None:
        code, detail = _classify_settle_error(httpx.ReadTimeout("timed out"))
        assert code == SettleErrorCode.RPC_TIMEOUT.value
        assert "timed out" in detail

    def test_insufficient_gas_marker(self) -> None:
        err = ValueError("execution reverted: insufficient funds for gas * price")
        code, _ = _classify_settle_error(err)
        assert code == SettleErrorCode.INSUFFICIENT_GAS.value

    def test_nonce_conflict_marker(self) -> None:
        err = ValueError("nonce too low")
        code, _ = _classify_settle_error(err)
        assert code == SettleErrorCode.NONCE_CONFLICT.value

    def test_generic_rpc_error_fallback(self) -> None:
        code, detail = _classify_settle_error(RuntimeError("connection reset by peer"))
        assert code == SettleErrorCode.RPC_ERROR.value
        assert "connection reset" in detail


# ── encoding helpers ─────────────────────────────────────────────────────────


class TestEncodingHelpers:
    def test_encode_address_left_pads_to_32(self) -> None:
        out = _encode_address("0x" + "11" * 20)
        assert len(out) == 32
        assert out[:12] == b"\x00" * 12
        assert out[12:] == b"\x11" * 20

    def test_encode_uint_big_endian_32(self) -> None:
        assert _encode_uint(1) == b"\x00" * 31 + b"\x01"
        assert len(_encode_uint(2**256 - 1)) == 32

    def test_encode_bytes32_short_left_pads(self) -> None:
        assert _encode_bytes32(b"\x01") == b"\x00" * 31 + b"\x01"

    def test_encode_bytes32_long_takes_last_32(self) -> None:
        val = bytes(range(40))
        assert _encode_bytes32(val) == val[-32:]

    def test_to_int_forms(self) -> None:
        assert _to_int(42) == 42
        assert _to_int(True) == 1
        assert isinstance(_to_int(True), int)
        assert _to_int("42") == 42
        assert _to_int("0x2a") == 42
        assert _to_int(" 0X2A ") == 42

    def test_to_int_rejects_garbage(self) -> None:
        with pytest.raises(ValueError, match="invalid literal"):
            _to_int("not-a-number")
        with pytest.raises(ValueError, match="cannot parse"):
            _to_int(3.5)

    def test_encode_nonce_bytes_passthrough(self) -> None:
        raw = bytes(range(32))
        assert _encode_nonce(raw) == raw

    def test_encode_nonce_int(self) -> None:
        assert _encode_nonce(1) == b"\x00" * 31 + b"\x01"

    def test_encode_nonce_hex_string(self) -> None:
        out = _encode_nonce("0x" + "ab" * 32)
        assert out == b"\xab" * 32

    def test_encode_nonce_odd_hex_raises(self) -> None:
        """Malformed (odd-length) hex is rejected loudly - nonces are
        bytes32 by definition, silent padding would hide corruption."""
        with pytest.raises(ValueError, match="non-hexadecimal number found"):
            _encode_nonce("0x" + "abc")

    def test_encode_nonce_empty_is_zero_word(self) -> None:
        assert _encode_nonce(None) == b"\x00" * 32

    def test_nonce_hex_lowercase_canonical(self) -> None:
        h = _nonce_hex("0x" + "AB" * 32)
        assert h == "ab" * 32


# ── EIP-712 digest ───────────────────────────────────────────────────────────


class TestEip712Digest:
    ARGS: ClassVar[dict[str, Any]] = {
        "from_address": "0x" + "aa" * 20,
        "to_address": "0x" + "bb" * 20,
        "value": 1_000_000,
        "valid_after": 0,
        "valid_before": 9_999_999,
        "nonce": "0x" + "cd" * 32,
    }

    def test_digest_is_deterministic(self) -> None:
        a = build_transfer_with_authorization_digest(
            **self.ARGS, chain_id=8453, token_address="0x" + "cc" * 20
        )
        b = build_transfer_with_authorization_digest(
            **self.ARGS, chain_id=8453, token_address="0x" + "cc" * 20
        )
        assert a == b
        assert len(a) == 32

    def test_digest_binds_chain_and_token(self) -> None:
        base = build_transfer_with_authorization_digest(
            **self.ARGS, chain_id=8453, token_address="0x" + "cc" * 20
        )
        other_chain = build_transfer_with_authorization_digest(
            **self.ARGS, chain_id=1, token_address="0x" + "cc" * 20
        )
        other_token = build_transfer_with_authorization_digest(
            **self.ARGS, chain_id=8453, token_address="0x" + "dd" * 20
        )
        assert base != other_chain
        assert base != other_token

    def test_domain_separator_differs_by_name_version(self) -> None:
        token = "0x" + "cc" * 20
        d1 = domain_separator("USD Coin", "2", 8453, token)
        d2 = domain_separator("USD Coin", "1", 8453, token)
        d3 = domain_separator("Other", "2", 8453, token)
        assert len({d1, d2, d3}) == 3

    def test_struct_hash_field_order_matters(self) -> None:
        h1 = transfer_with_authorization_struct_hash(
            from_address="0x" + "aa" * 20,
            to_address="0x" + "bb" * 20,
            value=5,
            valid_after=0,
            valid_before=10,
            nonce=b"\x00" * 32,
        )
        h2 = transfer_with_authorization_struct_hash(
            from_address="0x" + "bb" * 20,  # swapped from/to
            to_address="0x" + "aa" * 20,
            value=5,
            valid_after=0,
            valid_before=10,
            nonce=b"\x00" * 32,
        )
        assert h1 != h2


# ── signature parsing ────────────────────────────────────────────────────────


class TestSignatureParsing:
    def _sig_65(self, v: int = 27) -> bytes:
        return b"\x11" * 32 + b"\x22" * 32 + bytes([v])

    def test_65byte_hex_form(self) -> None:
        sig = _parse_signature({"signature": "0x" + self._sig_65().hex()})
        assert sig is not None
        assert sig.v == 0  # 27 normalized to 0

    def test_v28_normalizes_to_one(self) -> None:
        sig = _parse_signature({"signature": self._sig_65(28).hex()})
        assert sig is not None
        assert sig.v == 1

    def test_bytes_form(self) -> None:
        sig = _parse_signature({"signature": self._sig_65()})
        assert sig is not None
        assert sig.vrs == (0, int("11" * 32, 16), int("22" * 32, 16))

    def test_wrong_length_rejected(self) -> None:
        assert _parse_signature({"signature": "0x" + "11" * 64}) is None

    def test_bad_hex_rejected(self) -> None:
        assert _parse_signature({"signature": "zz-not-hex"}) is None

    def test_invalid_v_rejected(self) -> None:
        assert _parse_signature({"signature": self._sig_65(v=7)}) is None

    def test_vrs_fields_form(self) -> None:
        sig = _parse_signature({"r": "0x" + "11" * 32, "s": "0x" + "22" * 32, "v": 28})
        assert sig is not None
        assert sig.v == 1

    def test_vrs_int_form(self) -> None:
        sig = _parse_signature({"r": int("11" * 32, 16), "s": int("22" * 32, 16), "v": 27})
        assert sig is not None
        assert sig.vrs == (0, int("11" * 32, 16), int("22" * 32, 16))

    def test_vrs_missing_s_rejected(self) -> None:
        assert _parse_signature({"r": "0x" + "11" * 32}) is None

    def test_vrs_bad_hex_rejected(self) -> None:
        assert _parse_signature({"r": "nothex!", "s": "0x" + "22" * 32}) is None

    def test_no_signature_at_all_rejected(self) -> None:
        assert _parse_signature({}) is None

    def test_signature_from_bytes_length_guard(self) -> None:
        assert _signature_from_bytes(b"\x11" * 31, b"\x22" * 32, 27) is None
        assert _signature_from_bytes(b"\x11" * 32, b"\x22" * 31, 27) is None


# ── chain id resolution ──────────────────────────────────────────────────────


class TestChainIdResolution:
    def test_known_networks_resolve(self) -> None:
        for network, expected in list(CHAIN_ID_BY_NETWORK.items())[:5]:
            assert _chain_id_for(network) == expected

    def test_eip155_caip2_parsed(self) -> None:
        assert _chain_id_for("eip155:8453") == 8453
        assert _chain_id_for("eip155:1") == 1

    def test_eip155_garbage_returns_none(self) -> None:
        assert _chain_id_for("eip155:notanumber") is None

    def test_unknown_network_returns_none(self) -> None:
        assert _chain_id_for("solana:mainnet") is None


# ── nonce store: replay protection ───────────────────────────────────────────


class TestNonceStore:
    def test_mark_used_then_contains(self, tmp_path: Any) -> None:
        store = NonceStore(path=tmp_path / "n.json")
        key = "8453:0xtoken:abc"
        assert store.contains(key) is False
        assert store.mark_used(key) is True
        assert store.contains(key) is True
        assert store.mark_used(key) is False  # replay rejected
        assert store.count == 1

    def test_persistence_survives_restart(self, tmp_path: Any) -> None:
        path = tmp_path / "nonces.json"
        store = NonceStore(path=path)
        store.mark_used("chain:token:n1")
        store.mark_used("chain:token:n2")
        reloaded = NonceStore(path=path)
        assert reloaded.contains("chain:token:n1") is True
        assert reloaded.contains("chain:token:n2") is True
        assert reloaded.count == 2

    def test_corrupt_file_tolerated(self, tmp_path: Any) -> None:
        path = tmp_path / "corrupt.json"
        path.write_text("{not json at all")
        store = NonceStore(path=path)  # must not raise
        assert store.count == 0

    def test_legacy_list_format_loaded(self, tmp_path: Any) -> None:
        path = tmp_path / "legacy.json"
        path.write_text(json.dumps(["chain:token:a", "chain:token:b"]))
        store = NonceStore(path=path)
        assert store.count == 2

    def test_eviction_respects_max_size(self, tmp_path: Any) -> None:
        store = NonceStore(path=None, max_size=3)
        for i in range(5):
            store.mark_used(f"k{i}")
        assert store.count == 3
        assert store.contains("k0") is False  # oldest evicted
        assert store.contains("k4") is True

    def test_persist_failure_logged_not_raised(
        self, tmp_path: Any, caplog: pytest.LogCaptureFixture
    ) -> None:
        # Directory as path -> write fails with OSError.
        store = NonceStore(path=tmp_path)
        with caplog.at_level(logging.WARNING):
            store.mark_used("k1")  # must not raise
        assert any("nonce_persist_failed" in r.message for r in caplog.records)

    def test_clear_resets(self, tmp_path: Any) -> None:
        store = NonceStore(path=tmp_path / "n.json")
        store.mark_used("k1")
        store.clear()
        assert store.count == 0
        assert store.contains("k1") is False
