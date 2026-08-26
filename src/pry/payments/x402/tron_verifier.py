# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Pry — TRON TRC-20 USDT x402 payment verifier.

Verifies a TRON TRC-20 USDT payment on-chain by querying the TRON Grid
``/walletsolidity/gettransactioninfobyid`` endpoint and decoding the
TRC-20 Transfer event from the contract result data — no TRON SDK
dependency required (httpx + stdlib only).

TRC-20 Transfer event signature (same as ERC-20 since TRON is EVM-compatible):
  ``Transfer(address,address,uint256)`` → topic0
  ``0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef``

The event data encodes:
  - topics[1]: ``from`` address (32-byte, left-padded; TRON prefix ``41``)
  - topics[2]: ``to`` address (32-byte, left-padded; TRON prefix ``41``)
  - data: ``value`` (uint256, 6 decimals for USDT)

The verifier NEVER raises: every RPC error / not-found / malformed response
is converted into ``{"verified": False, "reason": ...}`` so callers can rely
on a stable dict shape.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# TRON mainnet USDT contract address (base58, no prefix).
TRON_USDT_CONTRACT = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"

# Default public TRON Grid RPC (override per call / env in production).
DEFAULT_TRON_RPC_URL = "https://api.trongrid.io"

# RPC timeout — verify is a single round-trip, keep it short.
TRON_RPC_TIMEOUT_SECONDS = 15.0

# TRC-20 Transfer event topic0 (keccak256("Transfer(address,address,uint256)")).
TRANSFER_EVENT_TOPIC0 = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"

# TRON mainnet address prefix byte (base58check encoding starts with 'T').
TRON_ADDRESS_PREFIX = "41"


def _tron_hex_to_base58(hex_addr: str) -> str:
    """Convert a TRON hex address (41-prefixed) to base58check.

    For verification we only need to compare addresses, so we normalize
    to lowercase hex for comparison rather than full base58 encoding.
    """
    if hex_addr.lower().startswith(TRON_ADDRESS_PREFIX):
        return hex_addr[2:].lower()
    return hex_addr.lower()


def _failure(reason: str, **extra: Any) -> dict[str, Any]:
    """Build a never-raise failure dict with the stable result shape."""
    result: dict[str, Any] = {
        "verified": False,
        "recipient": "",
        "amount_raw": 0,
        "amount_decimals": 6,
        "amount_usd": 0.0,
        "contract": "",
        "confirmed_at": "",
        "reason": reason,
        "block": None,
    }
    result.update(extra)
    return result


def _success(
    *,
    recipient: str,
    amount_raw: int,
    amount_decimals: int,
    amount_usd: float,
    contract: str,
    confirmed_at: str,
    block: int | None,
    reason: str = "",
) -> dict[str, Any]:
    return {
        "verified": True,
        "recipient": recipient,
        "amount_raw": amount_raw,
        "amount_decimals": amount_decimals,
        "amount_usd": amount_usd,
        "contract": contract,
        "confirmed_at": confirmed_at,
        "reason": reason,
        "block": block,
    }


def _confirmed_at_from_timestamp(timestamp_ms: int | float | None) -> str:
    """ISO-8601 UTC timestamp from a millisecond block timestamp."""
    if not isinstance(timestamp_ms, (int, float)):
        return ""
    try:
        return datetime.fromtimestamp(int(timestamp_ms) / 1000, tz=UTC).isoformat()
    except (ValueError, OSError, OverflowError):
        return ""


def _iter_trc20_transfers(contract_result: dict[str, Any]) -> list[dict[str, Any]]:
    """Yield decoded TRC-20 Transfer events from a contract result.

    Each event is a dict with ``from``, ``to``, ``value``, ``topic0``.
    Only events with the canonical Transfer topic0 and matching USDT
    contract are returned.
    """
    events: list[dict[str, Any]] = []
    # TRON Grid returns events in ``contractResult`` or ``internal_transactions``.
    # The canonical location is the ``log`` array in the transaction receipt.
    logs = contract_result.get("log") or contract_result.get("logs") or []
    if not isinstance(logs, list):
        return events

    for entry in logs:
        if not isinstance(entry, dict):
            continue
        topics = entry.get("topics") or []
        if not isinstance(topics, list) or len(topics) < 3:
            continue
        topic0 = topics[0]
        if topic0.lower() != TRANSFER_EVENT_TOPIC0:
            continue

        # Decode the Transfer event.
        # topics[1] = from (32-byte, address is last 20 bytes, TRON prefix 41)
        # topics[2] = to (32-byte, address is last 20 bytes, TRON prefix 41)
        # data = value (uint256)
        from_hex = topics[1][-40:] if len(topics[1]) >= 40 else topics[1]
        to_hex = topics[2][-40:] if len(topics[2]) >= 40 else topics[2]
        data_hex = entry.get("data", "0x0")

        try:
            value = int(data_hex, 16) if data_hex.startswith("0x") else int(data_hex)
        except (ValueError, TypeError):
            value = 0

        events.append(
            {
                "from": TRON_ADDRESS_PREFIX + from_hex,
                "to": TRON_ADDRESS_PREFIX + to_hex,
                "value": value,
                "topic0": topic0,
            }
        )

    return events


async def verify_tron_trc20_payment(
    tx_hash: str,
    expected_recipient: str,
    amount_usd: float,
    *,
    rpc_url: str = DEFAULT_TRON_RPC_URL,
    usdt_price_usd: float = 1.0,
) -> dict[str, Any]:
    """Verify a TRON TRC-20 USDT payment for an x402 payment.

    Queries ``/walletsolidity/gettransactioninfobyid`` and looks for a
    TRC-20 Transfer event where:
      - ``topics[0]`` is the canonical Transfer event signature
      - ``to`` (decoded from topics[2]) equals ``expected_recipient`` (hex)
      - ``value`` (decoded from data) >= amount_usd / usdt_price_usd * 10**6

    Never raises — every failure returns
    ``{"verified": False, "reason": ...}``.
    """
    if not tx_hash:
        return _failure("missing tx hash")
    if not expected_recipient:
        return _failure("missing expected recipient")
    if amount_usd is None or amount_usd < 0:
        return _failure("invalid (negative) required amount")

    # Normalize expected recipient to hex for comparison.
    expected_hex = expected_recipient.lower()
    if expected_hex.startswith("0x"):
        expected_hex = expected_hex[2:]
    if expected_hex.startswith(TRON_ADDRESS_PREFIX.lower()):
        expected_hex = expected_hex[2:]

    payload = {
        "value": tx_hash,
    }
    try:
        async with httpx.AsyncClient(timeout=TRON_RPC_TIMEOUT_SECONDS) as client:
            response = await client.post(
                f"{rpc_url}/walletsolidity/gettransactioninfobyid",
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPStatusError as e:
        return _failure(f"rpc_http_error: {e.response.status_code}")
    except httpx.RequestError as e:
        return _failure(f"rpc_error: {e}")
    except ValueError as e:
        return _failure(f"rpc_invalid_json: {e}")

    if not isinstance(data, dict):
        return _failure("rpc_malformed_response")

    # TRON Grid returns 200 with empty body for not-found transactions.
    if not data:
        return _failure("transaction_not_found")

    # Decode TRC-20 Transfer events.
    events = _iter_trc20_transfers(data)
    if not events:
        # Fallback: try decoding from receipt.logs if present.
        receipt = data.get("receipt") or {}
        events = _iter_trc20_transfers(receipt)

    if not events:
        return _failure(
            "no_trc20_transfer_found: no TRC-20 Transfer event in transaction",
            block=data.get("blockNumber"),
        )

    # Find the best matching transfer to the expected recipient.
    matching: list[dict[str, Any]] = []
    wrong_recipient: str | None = None
    for event in events:
        to_hex = event["to"][2:] if event["to"].startswith(TRON_ADDRESS_PREFIX) else event["to"]
        if to_hex.lower() == expected_hex.lower():
            matching.append(event)
        else:
            wrong_recipient = event["to"]

    if not matching:
        if wrong_recipient:
            return _failure(
                f"wrong_recipient: TRC-20 transfer to {wrong_recipient}, "
                f"expected {expected_recipient}",
                block=data.get("blockNumber"),
            )
        return _failure(
            "no_trc20_transfer_found: no TRC-20 transfer to recipient",
            block=data.get("blockNumber"),
        )

    # Prefer the largest transfer to the expected recipient.
    best = max(matching, key=lambda e: e["value"])
    paid_atomic = best["value"]
    paid_usd = paid_atomic / 1_000_000  # USDT has 6 decimals
    required_usd = amount_usd / usdt_price_usd if usdt_price_usd > 0 else float(amount_usd)

    if paid_usd + 1e-9 < required_usd:
        return _failure(
            f"underpayment: tx paid {paid_usd:.6f} USDT < required {required_usd:.6f} USDT",
            recipient=expected_recipient,
            amount_raw=paid_atomic,
            amount_decimals=6,
            amount_usd=round(paid_usd * usdt_price_usd, 6),
            contract=TRON_USDT_CONTRACT,
            confirmed_at=_confirmed_at_from_timestamp(data.get("blockTimeStamp")),
            block=data.get("blockNumber"),
        )

    return _success(
        recipient=expected_recipient,
        amount_raw=paid_atomic,
        amount_decimals=6,
        amount_usd=round(paid_usd * usdt_price_usd, 6),
        contract=TRON_USDT_CONTRACT,
        confirmed_at=_confirmed_at_from_timestamp(data.get("blockTimeStamp")),
        block=data.get("blockNumber"),
    )
