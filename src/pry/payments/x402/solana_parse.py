"""Pry — Solana x402 verifier: jsonParsed instruction parsing helpers.

Pure parsing of Solana RPC ``getTransaction`` ``jsonParsed`` responses:
SPL ``transferChecked`` instructions, system-program ``transfer``
instructions, atomic amount extraction, and blockTime conversion.

No RPC calls, no I/O — deterministic helpers only.
"""
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pry.payments.x402.solana_constants import (
    NATIVE_TRANSFER_TYPES,
    SPL_TOKEN_PROGRAM_ID,
    SYSTEM_PROGRAM_ID,
    VERIFIABLE_TYPES,
)


def _parse_amount(info: dict[str, Any]) -> tuple[int, int] | None:
    """Extract (amount_atomic, decimals) from a parsed transferChecked info.

    ``tokenAmount.amount`` is the authoritative atomic amount string;
    ``info.amount`` is the legacy duplicate. Returns None when malformed.

    A malformed amount returns None — never a coerced 0. Callers skip only on
    None, so a 0 here would be carried into the transfer candidates as a real
    on-chain value instead of being rejected.
    """
    token_amount = info.get("tokenAmount")
    if isinstance(token_amount, dict):
        raw = token_amount.get("amount")
        if raw is not None:
            try:
                amount = int(str(raw))
            except (ValueError, TypeError):
                return None
            try:
                decimals = int(token_amount.get("decimals", 6))
            except (ValueError, TypeError):
                decimals = 6
            return amount, decimals
    raw = info.get("amount")
    if raw is not None:
        try:
            amount = int(str(raw))
        except (ValueError, TypeError):
            return None
        try:
            decimals = int(info.get("decimals", 6))
        except (ValueError, TypeError):
            decimals = 6
        return amount, decimals
    return None


def _parse_lamports(info: dict[str, Any]) -> int | None:
    """Extract the lamports amount from a parsed system ``transfer`` info.

    jsonParsed emits ``lamports`` as an int; accept numeric strings too.
    Returns None when malformed or negative.
    """
    raw = info.get("lamports")
    if raw is None:
        return None
    try:
        lamports = int(str(raw))
    except (ValueError, TypeError):
        return None
    return lamports if lamports >= 0 else None


def _iter_spl_instructions(result: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """Yield ``(instruction_type, parsed_info)`` for every parsed splToken
    transfer instruction in the transaction (top-level + inner).

    Returns a list so the caller can pick the best (highest-amount) match
    when a transaction contains several stablecoin transfers.
    """
    found: list[tuple[str, dict[str, Any]]] = []
    message = result.get("transaction", {}).get("message", {})
    instructions = message.get("instructions", [])
    meta = result.get("meta", {}) or {}
    inner_instructions = meta.get("innerInstructions", []) or []
    for container in (
        instructions,
        *(inner.get("instructions", []) or [] for inner in inner_instructions),
    ):
        if not isinstance(container, list):
            continue
        for inst in container:
            if not isinstance(inst, dict):
                continue
            if inst.get("program") != "splToken":
                continue
            program_id = inst.get("programId")
            if program_id is not None and program_id != SPL_TOKEN_PROGRAM_ID:
                continue
            parsed = inst.get("parsed")
            if not isinstance(parsed, dict):
                continue
            inst_type = parsed.get("type")
            if inst_type not in VERIFIABLE_TYPES:
                continue
            info = parsed.get("info")
            if isinstance(info, dict):
                found.append((str(inst_type), info))
    return found


def _iter_system_transfers(result: dict[str, Any]) -> list[dict[str, Any]]:
    """Return parsed ``info`` dicts for every system-program ``transfer``
    instruction in the transaction (top-level + inner).

    A native SOL payment is a SystemProgram transfer: ``info.destination``
    is the recipient wallet directly (no mint/ATA indirection) and
    ``info.lamports`` is the atomic amount (1 SOL = 1e9 lamports).
    """
    found: list[dict[str, Any]] = []
    message = result.get("transaction", {}).get("message", {})
    instructions = message.get("instructions", [])
    meta = result.get("meta", {}) or {}
    inner_instructions = meta.get("innerInstructions", []) or []
    for container in (
        instructions,
        *(inner.get("instructions", []) or [] for inner in inner_instructions),
    ):
        if not isinstance(container, list):
            continue
        for inst in container:
            if not isinstance(inst, dict):
                continue
            if inst.get("program") != "system":
                continue
            program_id = inst.get("programId")
            if program_id is not None and program_id != SYSTEM_PROGRAM_ID:
                continue
            parsed = inst.get("parsed")
            if not isinstance(parsed, dict):
                continue
            if parsed.get("type") not in NATIVE_TRANSFER_TYPES:
                continue
            info = parsed.get("info")
            if isinstance(info, dict):
                found.append(info)
    return found


def _amount_usd_value(amount_atomic: int, decimals: int, unit_price_usd: float) -> float:
    """USD value of an atomic amount, rounded to 6 decimals."""
    if decimals < 0:
        decimals = 0
    value: float = float(amount_atomic) / (10**decimals) * float(unit_price_usd)
    return float(round(value, 6))


def _confirmed_at(result: dict[str, Any]) -> str:
    """ISO-8601 UTC timestamp from ``blockTime`` (unix seconds), or ""."""
    block_time = result.get("blockTime")
    if not isinstance(block_time, (int, float)):
        return ""
    try:
        return datetime.fromtimestamp(int(block_time), tz=UTC).isoformat()
    except (ValueError, OSError, OverflowError):
        return ""
