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

import hashlib
import logging
from datetime import UTC, datetime
from typing import Any

import httpx

logger = logging.getLogger(__name__)

TRON_USDT_CONTRACT = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"

DEFAULT_TRON_RPC_URL = "https://api.trongrid.io"

TRON_RPC_TIMEOUT_SECONDS = 15.0

TRANSFER_EVENT_TOPIC0 = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"

TRON_ADDRESS_PREFIX = "41"

_BASE58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def _base58check_to_hex(address: str) -> str:
    """Decode a TRON base58check address to its 41-prefixed lowercase hex form.

    Returns "" for malformed input (bad alphabet, wrong length, bad checksum)
    so callers can fail closed.
    """
    if not address:
        return ""
    num = 0
    for ch in address:
        idx = _BASE58_ALPHABET.find(ch)
        if idx < 0:
            return ""
        num = num * 58 + idx
    raw = num.to_bytes((num.bit_length() + 7) // 8, "big") if num else b""
    raw = b"\x00" * (len(address) - len(address.lstrip("1"))) + raw
    if len(raw) != 25:  # 1 version byte + 20-byte payload + 4-byte checksum
        return ""
    payload, checksum = raw[:-4], raw[-4:]
    if hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4] != checksum:
        return ""
    return payload.hex().lower()


TRON_USDT_CONTRACT_HEX = _base58check_to_hex(TRON_USDT_CONTRACT)


def _tron_hex_to_base58(hex_addr: str) -> str:
    """Convert a TRON hex address (41-prefixed) to base58check.

    For verification we only need to compare addresses, so we normalize
    to lowercase hex for comparison rather than full base58 encoding.
    """
    if hex_addr.lower().startswith(TRON_ADDRESS_PREFIX):
        return hex_addr[2:].lower()
    return hex_addr.lower()


def _normalize_log_address(address: Any) -> str:
    """Normalize a log's emitting-contract address to 41-prefixed lowercase hex.

    TRON Grid returns log addresses as 41-prefixed hex; base58 is accepted as
    a defensive fallback. Returns "" when the address is missing or malformed
    so callers can fail closed.
    """
    if not isinstance(address, str):
        return ""
    addr = address.strip()
    if not addr:
        return ""
    if addr.lower().startswith("0x"):
        addr = TRON_ADDRESS_PREFIX + addr[2:]
    if len(addr) == 42 and addr.lower().startswith(TRON_ADDRESS_PREFIX.lower()):
        try:
            int(addr, 16)
            return addr.lower()
        except ValueError as exc:
            logger.warning(
                "payments_exception_swallowed",
                extra={"error": str(exc), "handler": "_normalize_log_address"},
            )
            return ""
    return _base58check_to_hex(addr)


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
    except (ValueError, OSError, OverflowError) as exc:
        logger.warning(
            "payments_exception_swallowed",
            extra={"error": str(exc), "handler": "_confirmed_at_from_timestamp"},
        )
        return ""


def _iter_trc20_transfers(contract_result: dict[str, Any]) -> list[dict[str, Any]]:
    """Yield decoded TRC-20 Transfer events from a contract result.

    Each event is a dict with ``from``, ``to``, ``value``, ``topic0``.
    Only events with the canonical Transfer topic0 **emitted by the configured
    USDT contract** are returned. The emitting contract address is mandatory:
    a log without an ``address`` (or with a non-USDT contract) is skipped —
    fail closed, since topic0 alone is shared by every TRC-20 token and any
    scam token's Transfer event would otherwise pass verification.
    """
    events: list[dict[str, Any]] = []
    logs = contract_result.get("log") or contract_result.get("logs") or []
    if not isinstance(logs, list):
        return events

    for entry in logs:
        if not isinstance(entry, dict):
            continue
        log_contract = _normalize_log_address(
            entry.get("address") or entry.get("contract_address") or ""
        )
        if not log_contract or log_contract != TRON_USDT_CONTRACT_HEX:
            continue

        topics = entry.get("topics") or []
        if not isinstance(topics, list) or len(topics) < 3:
            continue
        topic0 = topics[0]
        if topic0.lower() != TRANSFER_EVENT_TOPIC0:
            continue

        # data = value (uint256)
        from_hex = topics[1][-40:] if len(topics[1]) >= 40 else topics[1]
        to_hex = topics[2][-40:] if len(topics[2]) >= 40 else topics[2]
        data_hex = entry.get("data", "0x0")

        try:
            value = int(data_hex, 16) if str(data_hex).startswith("0x") else int(data_hex)
        except (ValueError, TypeError) as exc:
            logger.warning(
                "payments_exception_swallowed",
                extra={"error": str(exc), "handler": "_iter_trc20_transfers"},
            )
            continue

        events.append(
            {
                "from": TRON_ADDRESS_PREFIX + from_hex,
                "to": TRON_ADDRESS_PREFIX + to_hex,
                "value": value,
                "topic0": topic0,
            }
        )

    return events


def _has_non_usdt_transfer(contract_result: dict[str, Any]) -> bool:
    """True if any log carries the Transfer topic0 but was NOT emitted by the
    configured USDT contract (or lacks an emitting address).

    Used only to produce a precise ``wrong_contract`` failure reason — the
    security decision itself is the filter inside ``_iter_trc20_transfers``.
    """
    logs = contract_result.get("log") or contract_result.get("logs") or []
    if not isinstance(logs, list):
        return False
    for entry in logs:
        if not isinstance(entry, dict):
            continue
        topics = entry.get("topics") or []
        if not isinstance(topics, list) or not topics:
            continue
        topic0 = topics[0]
        if not isinstance(topic0, str) or topic0.lower() != TRANSFER_EVENT_TOPIC0:
            continue
        log_contract = _normalize_log_address(
            entry.get("address") or entry.get("contract_address") or ""
        )
        if log_contract != TRON_USDT_CONTRACT_HEX:
            return True
    return False


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
      - the log's emitting contract address equals ``TRON_USDT_CONTRACT``
        (case-insensitive; fail closed on missing/mismatched address so
        non-USDT scam tokens can never pass verification)
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
        logger.warning(
            "payments_exception_swallowed",
            extra={"error": str(e), "handler": "verify_tron_trc20_payment"},
        )
        return _failure(f"rpc_http_error: {e.response.status_code}")
    except httpx.RequestError as e:
        logger.warning(
            "payments_exception_swallowed",
            extra={"error": str(e), "handler": "verify_tron_trc20_payment"},
        )
        return _failure(f"rpc_error: {e}")
    except ValueError as e:
        logger.warning(
            "payments_exception_swallowed",
            extra={"error": str(e), "handler": "verify_tron_trc20_payment"},
        )
        return _failure(f"rpc_invalid_json: {e}")

    if not isinstance(data, dict):
        return _failure("rpc_malformed_response")

    # TRON Grid returns 200 with empty body for not-found transactions.
    if not data:
        return _failure("transaction_not_found")

    # Decode TRC-20 Transfer events. Only events emitted by the configured
    # USDT contract are accepted (fail closed on any other TRC-20 token).
    events = _iter_trc20_transfers(data)
    receipt: dict[str, Any] = {}
    if not events:
        # Fallback: try decoding from receipt.logs if present.
        candidate_receipt = data.get("receipt")
        if isinstance(candidate_receipt, dict):
            receipt = candidate_receipt
            events = _iter_trc20_transfers(receipt)

    if not events:
        if _has_non_usdt_transfer(data) or _has_non_usdt_transfer(receipt):
            return _failure(
                f"wrong_contract: TRC-20 Transfer event not emitted by USDT "
                f"contract {TRON_USDT_CONTRACT} — refusing to credit "
                f"non-USDT token transfers",
                block=data.get("blockNumber"),
            )
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
