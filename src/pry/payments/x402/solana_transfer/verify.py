# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Solana x402 payment verification orchestration."""

from __future__ import annotations

import logging
import math
from typing import Any

from pry.payments.x402.solana_constants import (
    DEFAULT_SOLANA_RPC_URL,
    SOLANA_NATIVE_ASSET,
)
from pry.payments.x402.solana_parse import (
    _confirmed_at,
    _iter_spl_instructions,
    _iter_system_transfers,
)
from pry.payments.x402.solana_result import _failure, _success

from .candidates import (
    _collect_native_lamports,
    _collect_token_candidates,
    _FailureContext,
    _no_candidate_failure,
    _value_candidates,
)
from .request import _validate_request
from .rpc import _fetch_transaction

logger = logging.getLogger(__name__)


async def verify_solana_payment(
    tx_signature: str,
    expected_recipient: str,
    amount_usd: float,
    *,
    rpc_url: str = DEFAULT_SOLANA_RPC_URL,
    usdc_price_usd: float = 1.0,
    sol_price_usd: float | None = None,
    asset: str | None = None,
) -> dict[str, Any]:
    """Verify a Solana payment without propagating implementation errors.

    SPL stablecoin and native SOL transfers are matched to the expected
    recipient and asset. The largest matching transfer is selected and must
    meet the requested amount. Every failure uses the stable result shape.
    """
    try:
        allowed_assets, asset_upper, failure = _validate_request(
            tx_signature, expected_recipient, amount_usd, asset
        )
        if failure is not None:
            return failure

        try:
            finite_amount = amount_usd is None or math.isfinite(amount_usd)
        except (TypeError, ValueError, OverflowError):
            return _failure("invalid (negative) required amount")
        if not finite_amount:
            return _failure("invalid (negative) required amount")

        result, slot, failure = await _fetch_transaction(tx_signature, rpc_url)
        if failure is not None:
            return failure
        if result is None:
            return _failure("rpc_malformed_result")

        native_allowed = allowed_assets is None or SOLANA_NATIVE_ASSET in allowed_assets
        spl_instructions = _iter_spl_instructions(result)
        system_transfers = _iter_system_transfers(result)
        if not spl_instructions and not system_transfers:
            return _failure(
                "no_usdc_transfer_found: no parsed splToken transferChecked "
                "or system transfer instruction",
                slot=slot,
            )

        (
            token_to_recipient,
            unsupported_mint,
            wrong_asset_mint,
            recipient_mismatch_dest,
        ) = _collect_token_candidates(spl_instructions, expected_recipient, allowed_assets)
        native_lamports = _collect_native_lamports(system_transfers, expected_recipient)
        native_found = bool(native_lamports)
        native_price_ok = sol_price_usd is not None and sol_price_usd > 0
        valued = _value_candidates(
            token_to_recipient,
            native_lamports,
            native_allowed=native_allowed,
            sol_price_usd=sol_price_usd,
            usdc_price_usd=usdc_price_usd,
        )

        if not valued:
            return _no_candidate_failure(
                _FailureContext(
                    wrong_asset_mint=wrong_asset_mint,
                    unsupported_mint=unsupported_mint,
                    native_found=native_found,
                    native_allowed=native_allowed,
                    native_price_ok=native_price_ok,
                    native_lamports=native_lamports,
                    recipient_mismatch_dest=recipient_mismatch_dest,
                    asset_upper=asset_upper,
                    expected_recipient=expected_recipient,
                    slot=slot,
                )
            )

        paid_units, paid_usd, paid_atomic, decimals, paid_mint, paid_asset = max(
            valued, key=lambda candidate: candidate[0]
        )
        required_usd = amount_usd / usdc_price_usd if usdc_price_usd > 0 else float(amount_usd)
        if paid_units + 1e-9 < required_usd:
            return _failure(
                f"underpayment: tx paid {paid_units:.6f} {paid_asset} "
                f"< required {required_usd:.6f} {paid_asset}",
                recipient=expected_recipient,
                amount_raw=paid_atomic,
                amount_decimals=decimals,
                amount_usd=paid_usd,
                mint=paid_mint,
                confirmed_at=_confirmed_at(result),
                slot=slot,
                asset=paid_asset,
            )

        return _success(
            recipient=expected_recipient,
            amount_raw=paid_atomic,
            amount_decimals=decimals,
            amount_usd=paid_usd,
            mint=paid_mint,
            asset=paid_asset,
            confirmed_at=_confirmed_at(result),
            slot=slot,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "solana_payment_verification_error",
            extra={"error_type": type(exc).__name__},
        )
        return _failure("verification_error")
