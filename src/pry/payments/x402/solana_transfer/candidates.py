"""Pry — Solana x402 verifier: candidate collection and valuation helpers."""
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pry.payments.x402.solana_constants import (
    SOLANA_NATIVE_ASSET,
    SOLANA_NATIVE_DECIMALS,
    SUPPORTED_SOLANA_MINTS,
)
from pry.payments.x402.solana_parse import (
    _amount_usd_value,
    _parse_amount,
    _parse_lamports,
)
from pry.payments.x402.solana_result import _failure


def _collect_token_candidates(
    spl_instructions: list[tuple[str, dict[str, Any]]],
    expected_recipient: str,
    allowed_assets: set[str] | None,
) -> tuple[list[tuple[int, int, str, str]], str | None, str | None, str | None]:
    """Collect SPL transfer candidates to the recipient.

    Returns ``(token_to_recipient, unsupported_mint, wrong_asset_mint,
    recipient_mismatch_dest)`` — the three hints drive precise failure
    reasons when no candidate values.
    """
    # Token candidates: (amount_atomic, decimals, mint, asset_symbol).
    token_to_recipient: list[tuple[int, int, str, str]] = []
    unsupported_mint: str | None = None
    wrong_asset_mint: str | None = None
    recipient_mismatch_dest: str | None = None
    for _inst_type, info in spl_instructions:
        mint = str(info.get("mint") or "")
        destination = info.get("destination")
        parsed = _parse_amount(info)
        if parsed is None:
            continue
        amount_atomic, decimals = parsed
        asset_symbol = SUPPORTED_SOLANA_MINTS.get(mint)
        if destination == expected_recipient:
            if asset_symbol is not None and (
                allowed_assets is None or asset_symbol in allowed_assets
            ):
                token_to_recipient.append((amount_atomic, decimals, mint, asset_symbol))
            elif asset_symbol is not None:
                # Supported mint, but a different asset than strictly requested.
                wrong_asset_mint = mint
            else:
                unsupported_mint = mint
        elif asset_symbol is not None and recipient_mismatch_dest is None:
            recipient_mismatch_dest = str(destination)
    return token_to_recipient, unsupported_mint, wrong_asset_mint, recipient_mismatch_dest


def _collect_native_lamports(
    system_transfers: list[dict[str, Any]], expected_recipient: str
) -> list[int]:
    """Native SOL transfers to the recipient (lamports)."""
    native_lamports: list[int] = []
    for info in system_transfers:
        if info.get("destination") != expected_recipient:
            continue
        lamports = _parse_lamports(info)
        if lamports is not None and lamports > 0:
            native_lamports.append(lamports)
    return native_lamports


def _value_candidates(
    token_to_recipient: list[tuple[int, int, str, str]],
    native_lamports: list[int],
    *,
    native_allowed: bool,
    sol_price_usd: float | None,
    usdc_price_usd: float,
) -> list[tuple[float, float, int, int, str, str]]:
    """Value every candidate and return them for the largest-first pick.

    ``units`` is the comparison quantity: token units for SPL transfers
    (matching the historical USDC arithmetic — required_usd is denominated
    in token units via usdc_price_usd) and USD for native SOL (lamports
    valued at the supplied SOL price).
    """
    # (units, usd_value, amount_atomic, decimals, mint, asset_symbol).
    valued: list[tuple[float, float, int, int, str, str]] = []
    for amount_atomic, decimals, mint, asset_symbol in token_to_recipient:
        units = amount_atomic / (10**decimals) if decimals >= 0 else float(amount_atomic)
        valued.append(
            (
                units,
                _amount_usd_value(amount_atomic, decimals, usdc_price_usd),
                amount_atomic,
                decimals,
                mint,
                asset_symbol,
            )
        )
    if native_allowed and sol_price_usd is not None and sol_price_usd > 0:
        for lamports in native_lamports:
            native_usd = _amount_usd_value(lamports, SOLANA_NATIVE_DECIMALS, sol_price_usd)
            valued.append(
                (
                    native_usd,
                    native_usd,
                    lamports,
                    SOLANA_NATIVE_DECIMALS,
                    "",  # native SOL has no mint (SUPPORTED_ASSETS contract == "")
                    SOLANA_NATIVE_ASSET,
                )
            )
    return valued


@dataclass(frozen=True)
class _FailureContext:
    wrong_asset_mint: str | None
    unsupported_mint: str | None
    native_found: bool
    native_allowed: bool
    native_price_ok: bool
    native_lamports: list[int]
    recipient_mismatch_dest: str | None
    asset_upper: str
    expected_recipient: str
    slot: int


def _no_candidate_failure(context: _FailureContext) -> dict[str, Any]:
    """Pick the most precise failure reason when no candidate valued."""
    if context.wrong_asset_mint is not None:
        paid_symbol = SUPPORTED_SOLANA_MINTS.get(context.wrong_asset_mint, "unsupported mint")
        return _failure(
            f"wrong_asset: transfer destination matches but paid "
            f"{paid_symbol} while {context.asset_upper} was requested",
            slot=context.slot,
        )
    if context.unsupported_mint is not None:
        return _failure(
            "wrong_mint: unsupported asset — transfer destination matches but "
            f"mint {context.unsupported_mint} is not an advertised solana:mainnet asset "
            f"({', '.join(SUPPORTED_SOLANA_MINTS.values())})",
            slot=context.slot,
        )
    if context.native_found and context.native_allowed and not context.native_price_ok:
        return _failure(
            "sol_price_unavailable: native SOL transfer to recipient found but no "
            "SOL/USD price provided — pass sol_price_usd to verify native SOL payments",
            recipient=context.expected_recipient,
            amount_raw=max(context.native_lamports),
            amount_decimals=SOLANA_NATIVE_DECIMALS,
            slot=context.slot,
        )
    if context.recipient_mismatch_dest is not None:
        return _failure(
            f"wrong_recipient: supported-asset transfer to {context.recipient_mismatch_dest}, "
            f"expected {context.expected_recipient}",
            slot=context.slot,
        )
    detail = "no supported Solana asset transfer to recipient"
    if context.native_found and not context.native_allowed:
        detail = (
            "native SOL transfer to recipient found but asset "
            f"{context.asset_upper} was requested (native SOL only verifies with asset='SOL')"
        )
    return _failure(f"no_usdc_transfer_found: {detail}", slot=context.slot)
