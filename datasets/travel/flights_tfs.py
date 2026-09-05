"""tfs protobuf encoder for Google Flights deep links (wire format, hand-rolled).

The ``tfs`` query parameter is a Base64-encoded protobuf payload. The wire
format is reverse-engineered from the current ``fast-flights`` encoder and
verified byte-for-byte against a known-good round-trip example
(``CBwQAh...AZgBAQ`` for TPE→MYJ 2024-05-28).

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import base64
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable


# ── tfs protobuf encoder (wire format, hand-rolled — no protobuf dep) ──
def _varint(value: int) -> bytes:
    """Encode an unsigned LEB128 varint (protobuf wire format)."""
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def _field(num: int, payload: bytes) -> bytes:
    """Encode a length-delimited protobuf field (tag + length + payload)."""
    return _varint((num << 3) | 2) + _varint(len(payload)) + payload


def _encode_airport(code: str) -> bytes:
    """Encode an ``Airport { f1: 1, f2: <IATA> }`` message."""
    return b"\x08\x01" + _field(2, code.encode())


def _encode_leg(date: str, origin: str, dest: str) -> bytes:
    """Encode one ``FlightInfo`` leg (f3 of the top-level message)."""
    payload = _field(2, date.encode())
    payload += _field(13, _encode_airport(origin))
    payload += _field(14, _encode_airport(dest))
    return _field(3, payload)


def _build_tfs(legs: Iterable[tuple[str, str, str]]) -> str:
    """Build the Base64url ``tfs`` search parameter for the given legs.

    Each leg is a ``(date, origin, dest)`` tuple with ``date`` as
    ``YYYY-MM-DD`` and 3-letter IATA codes. The fixed header/tail bytes are
    the values emitted by the current ``fast-flights`` encoder for a
    one-way economy search with 1 adult (verified byte-for-byte).
    """
    full = b"\x08\x1c\x10\x02"
    for date, origin, dest in legs:
        full += _encode_leg(date, origin, dest)
    full += b"\x40\x01\x48\x01\x70\x01"
    full += b"\x82\x01\x0b\x08\xff\xff\xff\xff\xf0\x19\x80\x10\x10"
    return base64.urlsafe_b64encode(full).decode("ascii").rstrip("=")
