"""Pry — self-facilitator ABI encoding, EIP-712 digests, signature parsing."""

from __future__ import annotations

import logging
from typing import Any

from eth_keys.datatypes import Signature
from eth_utils import keccak, to_canonical_address

logger = logging.getLogger(__name__)

_EIP712_DOMAIN_TYPEHASH = keccak(
    text="EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)"
)
_TRANSFER_WITH_AUTH_TYPEHASH = keccak(
    text="TransferWithAuthorization("
    "address from,address to,uint256 value,uint256 validAfter,"
    "uint256 validBefore,bytes32 nonce)"
)

_TRANSFER_WITH_AUTH_SELECTOR = keccak(
    text="transferWithAuthorization("
    "address,address,uint256,uint256,uint256,bytes32,uint8,bytes32,bytes32)"
)[:4]
_TRANSFER_FROM_SELECTOR = keccak(text="transferFrom(address,address,uint256)")[:4]


def _encode_address(addr: str) -> bytes:
    return b"\x00" * 12 + to_canonical_address(addr)


def _encode_uint(value: int) -> bytes:
    return value.to_bytes(32, "big")


def _encode_bytes32(value: bytes) -> bytes:
    if len(value) < 32:
        return value.rjust(32, b"\x00")
    return value[-32:]


def _to_int(value: Any) -> int:
    """Parse an int from int / decimal str / 0x-hex str (EVM fields)."""
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        s = value.strip()
        if s.startswith(("0x", "0X")):
            return int(s, 16)
        return int(s, 10)
    raise ValueError(f"cannot parse {value!r} as integer")


def _encode_nonce(nonce: Any) -> bytes:
    """Normalize an EIP-3009 nonce (bytes32) to 32 bytes."""
    if isinstance(nonce, bytes):
        return _encode_bytes32(nonce)
    if isinstance(nonce, int):
        return nonce.to_bytes(32, "big")
    value = str(nonce or "")
    if value.startswith(("0x", "0X")):
        raw = bytes.fromhex(value[2:])
    else:
        raw = bytes.fromhex(value) if value else b"\x00"
    return _encode_bytes32(raw)


def _nonce_hex(nonce: Any) -> str:
    """Canonical lowercase hex string for a nonce (replay key component)."""
    return _encode_nonce(nonce).hex()


def _hex_to_bytes(value: str) -> bytes:
    """Parse a hex string to bytes, left-padding odd-length input."""
    s = value.removeprefix("0x")
    if len(s) % 2:
        s = "0" + s
    return bytes.fromhex(s)


def domain_separator(
    name: str,
    version: str,
    chain_id: int,
    verifying_contract: str,
) -> bytes:
    """Compute the EIP-712 domain separator for an EIP-3009 token."""
    return keccak(
        _EIP712_DOMAIN_TYPEHASH
        + keccak(text=name)
        + keccak(text=version)
        + _encode_uint(chain_id)
        + _encode_address(verifying_contract)
    )


def transfer_with_authorization_struct_hash(
    *,
    from_address: str,
    to_address: str,
    value: int,
    valid_after: int,
    valid_before: int,
    nonce: Any,
) -> bytes:
    """Compute the EIP-712 struct hash for ``TransferWithAuthorization``."""
    return keccak(
        _TRANSFER_WITH_AUTH_TYPEHASH
        + _encode_address(from_address)
        + _encode_address(to_address)
        + _encode_uint(value)
        + _encode_uint(valid_after)
        + _encode_uint(valid_before)
        + _encode_nonce(nonce)
    )


def build_transfer_with_authorization_digest(
    *,
    from_address: str,
    to_address: str,
    value: int,
    valid_after: int,
    valid_before: int,
    nonce: Any,
    chain_id: int,
    token_address: str,
    name: str = "USD Coin",
    version: str = "2",
) -> bytes:
    """Compute the EIP-712 signed digest for an EIP-3009 authorization.

    The digest is what the payer signs: ``keccak("\x19\x01" || domain || struct)``
    per EIP-712 / EIP-3009.
    """
    domain = domain_separator(name, version, chain_id, token_address)
    struct = transfer_with_authorization_struct_hash(
        from_address=from_address,
        to_address=to_address,
        value=value,
        valid_after=valid_after,
        valid_before=valid_before,
        nonce=nonce,
    )
    return keccak(b"\x19\x01" + domain + struct)


def _signature_from_bytes(r: bytes, s: bytes, v: int) -> Signature | None:
    """Build an eth_keys Signature, normalizing v (27/28 -> 0/1).

    eth-keys 0.7 stores r/s as ints and requires v in {0, 1}.
    """
    if len(r) != 32 or len(s) != 32:
        return None
    v_norm = int(v)
    if v_norm in (27, 28):
        v_norm -= 27
    if v_norm not in (0, 1):
        return None
    return Signature(vrs=(v_norm, int.from_bytes(r, "big"), int.from_bytes(s, "big")))


def _parse_signature(auth: dict[str, Any]) -> Signature | None:
    """Parse an EIP-3009 signature from ``signature`` (65-byte hex/bytes) or v/r/s.

    r/s may be hex strings, ints, or bytes; v may be 0/1 or 27/28.
    Odd-length hex (top nibble 0, e.g. ``hex()`` output) is left-padded.
    """
    signature = auth.get("signature")
    if signature:
        if isinstance(signature, (bytes, bytearray)):
            raw = bytes(signature)
        else:
            try:
                raw = bytes.fromhex(str(signature).removeprefix("0x"))
            except ValueError as exc:
                logger.warning(
                    "payments_exception_swallowed",
                    extra={"error": str(exc), "handler": "_parse_signature"},
                )
                return None
        if len(raw) != 65:
            return None
        r, s, v = raw[:32], raw[32:64], int(raw[64])
        return _signature_from_bytes(r, s, v)
    r_value = auth.get("r")
    s_value = auth.get("s")
    if r_value is None or s_value is None:
        return None
    try:
        r = r_value.to_bytes(32, "big") if isinstance(r_value, int) else _hex_to_bytes(str(r_value))
        s = s_value.to_bytes(32, "big") if isinstance(s_value, int) else _hex_to_bytes(str(s_value))
        v = int(auth.get("v", 27))
    except (ValueError, OverflowError) as exc:
        logger.warning(
            "payments_exception_swallowed",
            extra={"error": str(exc), "handler": "_parse_signature"},
        )
        return None
    return _signature_from_bytes(r, s, v)
