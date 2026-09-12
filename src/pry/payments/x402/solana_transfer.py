"""Pry — Solana multi-asset x402 payment verification (USDC / USDT / native SOL).

Verifies a Solana payment on-chain by querying the Solana RPC
``getTransaction`` with ``encoding: "jsonParsed"`` and walking:

  - parsed ``splToken`` ``transferChecked`` instructions for SPL stablecoins
    (USDC + USDT — the mints advertised in ``SUPPORTED_ASSETS`` for
    ``solana:mainnet``), and
  - parsed ``system`` program ``transfer`` instructions for native SOL
    payments (lamports, SystemProgram transfer).

No Solana SDK dependency required (httpx + stdlib only).

The verifier NEVER raises: every RPC error / not-found / malformed response
is converted into ``{"verified": False, "reason": ...}`` so callers can rely
on a stable dict shape.
"""
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

from typing import Any

import httpx

from pry.payments.x402.solana_constants import (
    DEFAULT_SOLANA_RPC_URL,
    SOLANA_NATIVE_ASSET,
    SOLANA_NATIVE_DECIMALS,
    SOLANA_RPC_TIMEOUT_SECONDS,
    SUPPORTED_SOLANA_ASSETS,
    SUPPORTED_SOLANA_MINTS,
)
from pry.payments.x402.solana_parse import (
    _amount_usd_value,
    _confirmed_at,
    _iter_spl_instructions,
    _iter_system_transfers,
    _parse_amount,
    _parse_lamports,
)
from pry.payments.x402.solana_result import _failure, _success


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
    """Verify a Solana payment for an x402 payment (USDC / USDT / native SOL).

    Queries ``getTransaction`` with ``jsonParsed`` encoding and looks for:

      - a parsed ``splToken`` ``transferChecked`` instruction where
        ``info.mint`` is an advertised Solana stablecoin mint (USDC or
        USDT), ``info.destination`` equals ``expected_recipient`` (base58),
        and ``amount / 10**decimals >= amount_usd / usdc_price_usd``; or
      - a parsed ``system`` ``transfer`` instruction (native SOL) where
        ``info.destination`` equals ``expected_recipient`` and
        ``lamports / 10**9 * sol_price_usd >= amount_usd``.

    Native SOL verification requires a SOL/USD price: pass
    ``sol_price_usd`` (there is no stable $1 assumption for SOL — without a
    price the verifier fails closed with ``sol_price_unavailable`` rather
    than guessing).

    ``asset`` optionally restricts verification to one advertised asset
    (``"USDC"``, ``"USDT"`` or ``"SOL"``). Default ``None`` accepts any
    advertised solana:mainnet asset.

    ``usdc_price_usd`` is the USD price per unit of the paid stablecoin
    (1.0 for both USDC and USDT); ``required_usd`` is denominated in those
    units, matching the historical USDC-only behaviour.

    Also confirms the transaction succeeded (``meta.err == null``) and was
    confirmed (``slot`` present).

    Never raises — every failure returns
    ``{"verified": False, "reason": ...}``.
    """
    allowed_assets, asset_upper, failure = _validate_request(
        tx_signature, expected_recipient, amount_usd, asset
    )
    if failure is not None:
        return failure

    result, slot, failure = await _fetch_transaction(tx_signature, rpc_url)
    if failure is not None:
        return failure
    if result is None:  # defensive — _fetch_transaction pairs None with a failure
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

    # Prefer the largest (highest-value) transfer to the expected recipient.
    paid_units, paid_usd, paid_atomic, decimals, paid_mint, paid_asset = max(
        valued, key=lambda v: v[0]
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


# ── Private helpers (extracted from verify_solana_payment — audit P2) ───────


def _validate_request(
    tx_signature: str,
    expected_recipient: str,
    amount_usd: float | None,
    asset: str | None,
) -> tuple[set[str] | None, str, dict[str, Any] | None]:
    """Validate request args before any RPC round-trip.

    Returns ``(allowed_assets, asset_upper, failure)`` — failure is None when
    the request is valid.
    """
    if not tx_signature:
        return None, "", _failure("missing tx signature")
    if not expected_recipient:
        return None, "", _failure("missing expected recipient")
    if amount_usd is None or amount_usd < 0:
        return None, "", _failure("invalid (negative) required amount")

    allowed_assets: set[str] | None = None
    asset_upper = ""
    if asset is not None:
        asset_upper = str(asset).strip().upper()
        if asset_upper not in SUPPORTED_SOLANA_ASSETS:
            return (
                None,
                "",
                _failure(
                    f"unsupported_asset: {asset!r} is not an advertised "
                    f"solana:mainnet asset ({', '.join(SUPPORTED_SOLANA_ASSETS)})"
                ),
            )
        allowed_assets = {asset_upper}
    return allowed_assets, asset_upper, None


async def _fetch_transaction(
    tx_signature: str, rpc_url: str
) -> tuple[dict[str, Any] | None, int, dict[str, Any] | None]:
    """Fetch and sanity-check ``getTransaction``.

    Returns ``(result, slot, failure)`` — result/slot are set only when
    failure is None.
    """
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getTransaction",
        "params": [
            tx_signature,
            {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0},
        ],
    }
    try:
        async with httpx.AsyncClient(timeout=SOLANA_RPC_TIMEOUT_SECONDS) as client:
            response = await client.post(rpc_url, json=payload)
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPStatusError as e:
        return None, 0, _failure(f"rpc_http_error: {e.response.status_code}")
    except httpx.RequestError as e:
        return None, 0, _failure(f"rpc_error: {e}")
    except ValueError as e:
        return None, 0, _failure(f"rpc_invalid_json: {e}")

    if not isinstance(data, dict):
        return None, 0, _failure("rpc_malformed_response")

    rpc_error = data.get("error")
    if rpc_error is not None:
        if isinstance(rpc_error, dict):
            code = rpc_error.get("code", "")
            message = rpc_error.get("message", "")
            return None, 0, _failure(f"rpc_error_response: {code} {message}".strip())
        return None, 0, _failure(f"rpc_error_response: {rpc_error}")

    result = data.get("result")
    if result is None:
        return None, 0, _failure("transaction_not_found")
    if not isinstance(result, dict):
        return None, 0, _failure("rpc_malformed_result")

    slot = result.get("slot")
    meta = result.get("meta") or {}
    if not isinstance(meta, dict):
        return None, 0, _failure("rpc_malformed_meta")

    tx_err = meta.get("err")
    if tx_err is not None:
        return None, 0, _failure(f"transaction_failed: {tx_err}", slot=slot)

    if not isinstance(slot, int):
        # No slot means the RPC has not confirmed the tx into a block yet.
        return None, 0, _failure("transaction_not_confirmed")

    return result, slot, None


def _collect_token_candidates(
    spl_instructions: list,
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


def _collect_native_lamports(system_transfers: list, expected_recipient: str) -> list[int]:
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


def _no_candidate_failure(
    *,
    wrong_asset_mint: str | None,
    unsupported_mint: str | None,
    native_found: bool,
    native_allowed: bool,
    native_price_ok: bool,
    native_lamports: list[int],
    recipient_mismatch_dest: str | None,
    asset_upper: str,
    expected_recipient: str,
    slot: int,
) -> dict[str, Any]:
    """Pick the most precise failure reason when no candidate valued."""
    if wrong_asset_mint is not None:
        paid_symbol = SUPPORTED_SOLANA_MINTS.get(wrong_asset_mint, "unsupported mint")
        return _failure(
            f"wrong_asset: transfer destination matches but paid "
            f"{paid_symbol} while {asset_upper} was requested",
            slot=slot,
        )
    if unsupported_mint is not None:
        return _failure(
            "wrong_mint: unsupported asset — transfer destination matches but "
            f"mint {unsupported_mint} is not an advertised solana:mainnet asset "
            f"({', '.join(SUPPORTED_SOLANA_MINTS.values())})",
            slot=slot,
        )
    if native_found and native_allowed and not native_price_ok:
        return _failure(
            "sol_price_unavailable: native SOL transfer to recipient found but no "
            "SOL/USD price provided — pass sol_price_usd to verify native SOL payments",
            recipient=expected_recipient,
            amount_raw=max(native_lamports),
            amount_decimals=SOLANA_NATIVE_DECIMALS,
            slot=slot,
        )
    if recipient_mismatch_dest is not None:
        return _failure(
            f"wrong_recipient: supported-asset transfer to {recipient_mismatch_dest}, "
            f"expected {expected_recipient}",
            slot=slot,
        )
    detail = "no supported Solana asset transfer to recipient"
    if native_found and not native_allowed:
        detail = (
            "native SOL transfer to recipient found but asset "
            f"{asset_upper} was requested (native SOL only verifies with asset='SOL')"
        )
    return _failure(f"no_usdc_transfer_found: {detail}", slot=slot)
