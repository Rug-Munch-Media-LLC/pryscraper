"""Canonical payment-record loading and timestamp normalisation."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
import json
import logging
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

#: Canonical payment timestamp precedence.
TIMESTAMP_KEYS = ("verified_at", "ts", "created_at")


def parse_payment_ts(value: Any) -> datetime | None:
    """Parse a timestamp to an aware UTC datetime; naive values are UTC."""
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def payment_ts(record: dict[str, Any]) -> datetime | None:
    """Canonical payment time: verified_at -> ts -> created_at (aware UTC)."""
    for key in TIMESTAMP_KEYS:
        parsed = parse_payment_ts(record.get(key))
        if parsed is not None:
            return parsed
    return None


def _amount_usd(record: dict[str, Any]) -> float:
    """Coerce a row amount to float; corrupt rows count as 0, never raise."""
    try:
        return float(record.get("amount_usd", 0) or 0)
    except (TypeError, ValueError):
        return 0.0


def _payment_identity(record: dict[str, Any]) -> tuple[str, str] | None:
    tx_hash = str(record.get("tx_hash") or "")
    if tx_hash:
        return ("tx", tx_hash)
    payment_id = str(record.get("payment_id") or "")
    if payment_id:
        return ("pid", payment_id)
    return None


def dedupe_payment_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop duplicate rows, keeping the first (ledger-first) occurrence."""
    seen: set[tuple[str, str]] = set()
    unique: list[dict[str, Any]] = []
    for record in records:
        identity = _payment_identity(record)
        if identity is not None:
            if identity in seen:
                continue
            seen.add(identity)
        unique.append(record)
    return unique


def _load_jsonl_records(path: str) -> list[dict[str, Any]]:
    import os

    if not path or not os.path.exists(path):
        return []
    records: list[dict[str, Any]] = []
    try:
        with open(path) as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError as e:
                    logger.warning(
                        "payment_record_line_dropped",
                        extra={"path": path, "error": str(e)},
                    )
                    continue
                if isinstance(row, dict):
                    records.append(row)
    except OSError as exc:
        logger.warning("analytics_load_failed", extra={"error": str(exc)[:160]})
    return records


def load_payment_records(fallback_path: str = "") -> list[dict[str, Any]]:
    """Load payments with Postgres as the source of truth.

    x402_payment_records is authoritative; the JSONL log is the fallback.
    Ledger rows come first so they win on identity, but JSONL rows the ledger
    has not ingested yet are appended so history is never silently dropped.
    Deduped by tx_hash, then payment_id.
    """
    records: list[dict[str, Any]] = []
    try:
        from pry.payments.x402 import ledger_store

        if ledger_store.available():
            records.extend(ledger_store.get_payments())
    except Exception as exc:  # noqa: BLE001 - any ledger failure degrades to JSONL
        logger.warning("payment_ledger_unavailable", extra={"error": str(exc)[:160]})
    records.extend(_load_jsonl_records(fallback_path))
    return dedupe_payment_records(records)
