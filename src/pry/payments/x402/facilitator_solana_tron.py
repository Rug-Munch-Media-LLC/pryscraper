"""Pry — x402 facilitator Solana/TRON verification.

Extracted from ``facilitator.py``: the non-EVM on-chain verifiers — Solana
(SPL RPC via ``x402.solana_verifier``), TRON (TRC-20 Grid via
``x402.tron_verifier``), and the honest scaffolded fallback for chains
without a real verifier yet.

These are module-level functions; :class:`FacilitatorRouter` keeps thin
method wrappers for backwards compatibility.
"""

from __future__ import annotations

import logging
import math
from typing import Any

from pry.payments.x402 import (
    X402_NETWORK_WALLETS,
    X402_UNCONFIGURED_WALLET,
    is_solana_address,
    is_tron_address,
)
from pry.payments.x402.scheme import (
    get_asset_usd_price,
    network_verification_status,
    normalize_network_id,
    resolve_asset_entry,
)

logger = logging.getLogger(__name__)

SCAFFOLDED_NETWORKS: set[str] = {"tron:mainnet"}


def _scaffold_non_evm_verify(
    payment_id: str,
    tx_hash: str,
    network: str,
    asset: str,
    amount_usd: float,
) -> dict[str, Any]:
    """[REVIEW] Scaffolded acceptance for TRON payments.

    REAL: header structure (payment_id/tx_hash present), asset membership
    in SUPPORTED_ASSETS for the CAIP-2 network, and non-negative USD
    amount are validated; the result is explicitly marked ``scaffolded``.

    NOT REAL: on-chain settlement is NOT checked — no TRON Grid
    verification and no TRC-20 facilitator is wired up yet. The payment is
    marked ``needs_facilitator`` (verified=False) so it can never be
    treated as paid. Operators must implement TRC-20 verification before
    enabling this chain. (Solana now verifies via the SPL RPC verifier —
    see :func:`verify_solana`.)
    """
    network_id = normalize_network_id(network)
    entry = resolve_asset_entry(network_id, asset)
    if not payment_id or not tx_hash:
        return {
            "verified": False,
            "reason": "needs_facilitator: missing payment_id/tx_hash in header",
            "settlement": None,
            "scaffolded": True,
            "network": network_id,
        }
    if entry is None:
        return {
            "verified": False,
            "reason": (
                f"needs_facilitator: asset {asset!r} not in SUPPORTED_ASSETS for {network_id}"
            ),
            "settlement": None,
            "scaffolded": True,
            "network": network_id,
        }
    if amount_usd is None or amount_usd < 0:
        return {
            "verified": False,
            "reason": "needs_facilitator: invalid (non-finite/negative) amount",
            "settlement": None,
            "scaffolded": True,
            "network": network_id,
        }
    return {
        "verified": False,
        "reason": "needs_facilitator: on-chain settlement verification not "
        "implemented for this chain",
        "settlement": None,
        "scaffolded": True,
        "network": network_id,
        "asset": asset,
        "supported": True,
        "verification_status": network_verification_status(network_id),
        "note": (
            "Header structure, asset membership and price validated; "
            "settlement NOT verified. See VERIFICATION_STATUS."
        ),
    }


async def verify_solana(
    payment_id: str,
    tx_hash: str,
    network: str,
    asset: str,
    amount_usd: float,
) -> dict[str, Any]:
    """Verify a Solana payment (USDC / USDT / native SOL) on-chain via the
    SPL RPC verifier.

    Uses ``x402.solana_verifier.verify_solana_payment`` (guarded import —
    if the module is absent, e.g. an older checkout, fall back to the
    scaffolded path). Native SOL payments are valued with the canonical
    SOL/USD quote (``get_asset_usd_price("SOL")`` — live oracle or
    env-overridable static default), so a native SOL transfer verifies
    like any other asset. The server Solana receiving wallet comes from
    ``X402_NETWORK_WALLETS`` (``PRY_X402_WALLET_SOLANA``) — a Solana
    address is NOT the EVM wallet, so verification fails closed when it is
    unconfigured. The result reflects real on-chain verification.
    """
    network_id = normalize_network_id(network)
    if not payment_id or not tx_hash:
        return {
            "verified": False,
            "reason": "needs_facilitator: missing payment_id/tx_hash in header",
            "settlement": None,
            "scaffolded": True,
            "network": network_id,
        }
    if amount_usd is None or not math.isfinite(amount_usd) or amount_usd < 0:
        return {
            "verified": False,
            "reason": "invalid (non-finite/negative) amount",
            "settlement": None,
            "network": network_id,
        }
    entry = resolve_asset_entry(network_id, asset)
    if entry is None:
        return {
            "verified": False,
            "reason": f"asset {asset!r} not in SUPPORTED_ASSETS for {network_id}",
            "settlement": None,
            "network": network_id,
        }
    recipient = (X402_NETWORK_WALLETS.get(network_id) or "").strip()
    if not recipient or recipient == X402_UNCONFIGURED_WALLET or not is_solana_address(recipient):
        return {
            "verified": False,
            "reason": (
                "solana receiving wallet not configured or malformed — set "
                "PRY_X402_WALLET_SOLANA (a Solana base58 address, not the EVM wallet)"
            ),
            "settlement": None,
            "network": network_id,
        }
    try:
        from pry.payments.x402.solana_verifier import verify_solana_payment
    except ImportError as exc:
        # Module absent (older checkout) — keep the honest scaffold path.
        logger.warning(
            "payments_exception_swallowed",
            extra={"error": str(exc), "handler": "verify_solana"},
        )
        return _scaffold_non_evm_verify(payment_id, tx_hash, network, asset, amount_usd)

    # Native SOL verification needs a SOL/USD price — there is no stable
    # $1 assumption, and the verifier fails closed without one. Use the
    # canonical price path (live oracle when PRY_X402_ORACLE_SOURCE is
    # configured, else the env-overridable static default
    # PRY_X402_USD_PER_UNIT_SOL, default 140) — the SAME quote used to
    # build the accept list, so verification can never price a SOL
    # payment at 0 or drift from the quoted amount.
    sol_quote = await get_asset_usd_price("SOL", network_id)
    if sol_quote.usd is None or sol_quote.usd <= 0:
        return {
            "verified": False,
            "reason": (
                "sol_price_unavailable: no SOL/USD price for native SOL "
                "verification — set PRY_X402_USD_PER_UNIT_SOL or configure an oracle"
            ),
            "settlement": None,
            "network": network_id,
        }
    result = await verify_solana_payment(
        tx_hash, recipient, amount_usd, sol_price_usd=sol_quote.usd
    )
    return {
        "verified": bool(result.get("verified")),
        "reason": result.get("reason", ""),
        "settlement": None,
        "network": network_id,
        "facilitator": "solana-rpc",
        "signer": result.get("recipient") or recipient,
        "amount_atomic": result.get("amount_raw"),
        "asset": asset,
        "mint": result.get("mint"),
        "confirmed_at": result.get("confirmed_at"),
        "amount_usd": result.get("amount_usd"),
    }


async def verify_tron(
    payment_id: str,
    tx_hash: str,
    network: str,
    asset: str,
    amount_usd: float,
) -> dict[str, Any]:
    """Verify a TRON TRC-20 USDT payment on-chain via the TRON Grid verifier.

    Uses ``x402.tron_verifier.verify_tron_trc20_payment`` (guarded import).
    The server TRON receiving wallet comes from ``X402_NETWORK_WALLETS``
    (``PRY_X402_WALLET_TRON``) — a TRON address is NOT the EVM wallet, so
    verification fails closed when it is unconfigured. The result reflects
    real on-chain verification.
    """
    network_id = normalize_network_id(network)
    if not payment_id or not tx_hash:
        return {
            "verified": False,
            "reason": "needs_facilitator: missing payment_id/tx_hash in header",
            "settlement": None,
            "scaffolded": True,
            "network": network_id,
        }
    if amount_usd is None or not math.isfinite(amount_usd) or amount_usd < 0:
        return {
            "verified": False,
            "reason": "invalid (non-finite/negative) amount",
            "settlement": None,
            "network": network_id,
        }
    entry = resolve_asset_entry(network_id, asset)
    if entry is None:
        return {
            "verified": False,
            "reason": f"asset {asset!r} not in SUPPORTED_ASSETS for {network_id}",
            "settlement": None,
            "network": network_id,
        }
    recipient = (X402_NETWORK_WALLETS.get(network_id) or "").strip()
    if not recipient or recipient == X402_UNCONFIGURED_WALLET or not is_tron_address(recipient):
        return {
            "verified": False,
            "reason": (
                "TRON receiving wallet not configured or malformed — set "
                "PRY_X402_WALLET_TRON (a TRON base58 address, not the EVM wallet)"
            ),
            "settlement": None,
            "network": network_id,
        }
    try:
        from pry.payments.x402.tron_verifier import verify_tron_trc20_payment
    except ImportError as exc:
        logger.warning(
            "payments_exception_swallowed",
            extra={"error": str(exc), "handler": "verify_tron"},
        )
        return _scaffold_non_evm_verify(payment_id, tx_hash, network, asset, amount_usd)

    result = await verify_tron_trc20_payment(tx_hash, recipient, amount_usd)
    return {
        "verified": bool(result.get("verified")),
        "reason": result.get("reason", ""),
        "settlement": None,
        "network": network_id,
        "facilitator": "tron-grid",
        "signer": result.get("recipient") or recipient,
        "amount_atomic": result.get("amount_raw"),
        "asset": asset,
        "contract": result.get("contract"),
        "confirmed_at": result.get("confirmed_at"),
        "amount_usd": result.get("amount_usd"),
    }
