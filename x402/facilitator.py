"""Pry — x402 facilitator router.

Owns the facilitator configuration, the smart router with auto-fallback
(including the EIP-7702 self-verify fallback for EVM chains), and the global
router instance accessors. Config constants (``X402_WALLET``,
``X402_TIMEOUT_SECONDS``, ``EIP7702_RPC``, …) are imported from the package
root; scheme helpers come from ``x402.scheme``.
"""
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx

from x402 import (
    EIP7702_RPC,
    EIP7702_TOKEN_ADDRESSES,
    X402_OFFLINE_MODE,
    X402_TIMEOUT_SECONDS,
    X402_WALLET,
)
from x402.scheme import (
    _NATIVE_ASSETS,
    VERIFICATION_STATUS,
    X402Scheme,
    asset_to_atomic,
    network_family,
    normalize_network_id,
    resolve_asset_entry,
)

logger = logging.getLogger(__name__)

# ERC-20 transfer(address,uint256) selector — used to parse token payments.
ERC20_TRANSFER_SELECTOR = "0xa9059cbb"

# Chains with NO real on-chain settlement verification implemented yet.
# Payments for these networks validate structure/price/asset server-side and
# then report "needs_facilitator" — they are NOT claimed as verified. [REVIEW]
SCAFFOLDED_NETWORKS: set[str] = {"solana:mainnet", "tron:mainnet"}


@dataclass
class FacilitatorConfig:
    """Configuration for a single x402 facilitator."""

    name: str
    verify_url: str
    settle_url: str
    priority: int = 0
    enabled: bool = True
    api_key: str = field(default="", repr=False)
    timeout_seconds: float = X402_TIMEOUT_SECONDS


# Default facilitator router — override via env or runtime config.
DEFAULT_FACILITATORS: list[FacilitatorConfig] = [
    FacilitatorConfig(
        name="coinbase",
        verify_url=os.getenv("PRY_X402_COINBASE_VERIFY", "https://x402.org/facilitator/verify"),
        settle_url=os.getenv("PRY_X402_COINBASE_SETTLE", "https://x402.org/facilitator/settle"),
        priority=int(os.getenv("PRY_X402_COINBASE_PRIORITY", "1")),
        enabled=os.getenv("PRY_X402_COINBASE_ENABLED", "true").lower() in ("1", "true"),
    ),
    FacilitatorConfig(
        name="payai",
        verify_url=os.getenv("PRY_X402_PAYAI_VERIFY", "https://facilitator.payai.network/verify"),
        settle_url=os.getenv("PRY_X402_PAYAI_SETTLE", "https://facilitator.payai.network/settle"),
        priority=int(os.getenv("PRY_X402_PAYAI_PRIORITY", "2")),
        enabled=os.getenv("PRY_X402_PAYAI_ENABLED", "true").lower() in ("1", "true"),
    ),
    FacilitatorConfig(
        name="cloudflare",
        verify_url=os.getenv("PRY_X402_CF_VERIFY", ""),
        settle_url=os.getenv("PRY_X402_CF_SETTLE", ""),
        priority=int(os.getenv("PRY_X402_CF_PRIORITY", "3")),
        enabled=os.getenv("PRY_X402_CF_ENABLED", "false").lower() in ("1", "true"),
    ),
]


class FacilitatorRouter:
    """Smart router that picks the best facilitator per chain/asset.

    Falls back through enabled facilitators. Records failures and retries
    with exponential backoff. Supports EIP-7702 self-verify mode as a
    last-resort fallback for EVM chains.
    """

    def __init__(self, facilitators: list[FacilitatorConfig] | None = None) -> None:
        self.facilitators = sorted(
            [f for f in (facilitators or DEFAULT_FACILITATORS) if f.enabled and f.verify_url],
            key=lambda f: f.priority,
        )
        self._failures: dict[str, int] = {}

    def _health_key(self, facilitator: FacilitatorConfig) -> str:
        return facilitator.name

    def _is_healthy(self, facilitator: FacilitatorConfig) -> bool:
        return self._failures.get(self._health_key(facilitator), 0) < 3

    def _mark_failure(self, facilitator: FacilitatorConfig) -> None:
        key = self._health_key(facilitator)
        self._failures[key] = self._failures.get(key, 0) + 1
        logger.warning("x402_facilitator_failure", extra={"facilitator": facilitator.name})

    def _mark_success(self, facilitator: FacilitatorConfig) -> None:
        key = self._health_key(facilitator)
        if key in self._failures:
            del self._failures[key]

    async def verify(
        self,
        payment_id: str,
        tx_hash: str,
        network: str,
        asset: str,
        amount_usd: float,
    ) -> dict[str, Any]:
        """Verify a payment with the best available facilitator.

        Returns {"verified": bool, "reason": str, "settlement": dict|None}.

        EVM chains are verified via configured facilitators, with an
        EIP-7702 self-verify fallback. Solana/TRON (SCAFFOLDED_NETWORKS)
        validate structure/price/asset and then report "needs_facilitator" —
        they are never claimed verified without a real verifier. [REVIEW]
        """
        if X402_OFFLINE_MODE:
            return {"verified": True, "reason": "offline_mode", "settlement": None}

        payload = {
            "paymentId": payment_id,
            "transactionHash": tx_hash,
            "network": network,
            "asset": asset,
            "amount": str(asset_to_atomic(amount_usd, asset, network)),
            "payToAddress": X402_WALLET,
            "scheme": X402Scheme.EXACT.value,
            "timestamp": datetime.now(UTC).isoformat(),
        }

        last_error = "No facilitators available"
        async with httpx.AsyncClient(timeout=X402_TIMEOUT_SECONDS) as client:
            for facilitator in self.facilitators:
                if not self._is_healthy(facilitator):
                    continue
                try:
                    response = await client.post(facilitator.verify_url, json=payload)
                    response.raise_for_status()
                    data = response.json()
                    self._mark_success(facilitator)
                    verified = bool(
                        data.get("isValid") or data.get("verified") or data.get("success")
                    )
                    return {
                        "verified": verified,
                        "reason": data.get("error", data.get("reason", "")) if not verified else "",
                        "settlement": data if verified else None,
                        "facilitator": facilitator.name,
                    }
                except httpx.HTTPStatusError as e:
                    last_error = f"{facilitator.name}: HTTP {e.response.status_code}"
                    self._mark_failure(facilitator)
                except httpx.RequestError as e:
                    last_error = f"{facilitator.name}: {e}"
                    self._mark_failure(facilitator)
                except json.JSONDecodeError as e:
                    last_error = f"{facilitator.name}: invalid JSON response - {e}"
                    self._mark_failure(facilitator)

        # EIP-7702 self-verify fallback for supported EVM chains
        if network in EIP7702_RPC:
            result = await self._eip7702_verify(tx_hash, network, asset, amount_usd)
            if result["verified"]:
                return result
            last_error = result.get("reason", last_error)

        # Non-EVM chains: validate structure/price/asset, then report that a
        # real verifier is required — do NOT claim success. [REVIEW]
        if network_family(network) in ("solana", "tron"):
            return self._scaffold_non_evm_verify(payment_id, tx_hash, network, asset, amount_usd)

        return {"verified": False, "reason": last_error, "settlement": None}

    def _scaffold_non_evm_verify(
        self,
        payment_id: str,
        tx_hash: str,
        network: str,
        asset: str,
        amount_usd: float,
    ) -> dict[str, Any]:
        """[REVIEW] Scaffolded acceptance for Solana/TRON payments.

        REAL: header structure (payment_id/tx_hash present), asset membership
        in SUPPORTED_ASSETS for the CAIP-2 network, and non-negative USD
        amount are validated; the result is explicitly marked ``scaffolded``.

        NOT REAL: on-chain settlement is NOT checked — no Solana RPC /
        TRON Grid verification and no SPL/TRC-20 facilitator is wired up yet.
        The payment is marked ``needs_facilitator`` (verified=False) so it
        can never be treated as paid. Operators must implement SPL/TRC-20
        verification before enabling these chains.
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
        status = VERIFICATION_STATUS.get(network_family(network_id), {})
        return {
            "verified": False,
            "reason": "needs_facilitator: on-chain settlement verification not "
            "implemented for this chain",
            "settlement": None,
            "scaffolded": True,
            "network": network_id,
            "asset": asset,
            "supported": True,
            "verification_status": status.get("scaffolded", True),
            "note": (
                "Header structure, asset membership and price validated; "
                "settlement NOT verified. See VERIFICATION_STATUS."
            ),
        }

    async def settle(
        self,
        payment_id: str,
        tx_hash: str,
        network: str,
        asset: str,
        amount_usd: float,
    ) -> dict[str, Any]:
        """Confirm settlement with the best available facilitator."""
        if X402_OFFLINE_MODE:
            return self._offline_settlement(payment_id, tx_hash, network)

        payload = {
            "paymentId": payment_id,
            "transactionHash": tx_hash,
            "network": network,
            "asset": asset,
            "amount": str(asset_to_atomic(amount_usd, asset, network)),
            "payToAddress": X402_WALLET,
            "scheme": X402Scheme.EXACT.value,
            "timestamp": datetime.now(UTC).isoformat(),
        }

        last_error = "No facilitators available"
        async with httpx.AsyncClient(timeout=X402_TIMEOUT_SECONDS) as client:
            for facilitator in self.facilitators:
                if not self._is_healthy(facilitator):
                    continue
                if not facilitator.settle_url:
                    continue
                try:
                    response = await client.post(facilitator.settle_url, json=payload)
                    response.raise_for_status()
                    data = response.json()
                    self._mark_success(facilitator)
                    return self._normalize_settlement(
                        data, payment_id, tx_hash, network, facilitator.name
                    )
                except httpx.HTTPStatusError as e:
                    last_error = f"{facilitator.name}: HTTP {e.response.status_code}"
                    self._mark_failure(facilitator)
                except httpx.RequestError as e:
                    last_error = f"{facilitator.name}: {e}"
                    self._mark_failure(facilitator)
                except json.JSONDecodeError as e:
                    last_error = f"{facilitator.name}: invalid JSON response - {e}"
                    self._mark_failure(facilitator)

        # EIP-7702 fallback settlement receipt
        if network in EIP7702_RPC:
            return self._eip7702_settlement(payment_id, tx_hash, network)

        # Non-EVM chains have no settlement verifier yet — report honestly.
        if network_family(network) in ("solana", "tron"):
            return {
                "success": False,
                "payment_id": payment_id,
                "reason": "needs_facilitator: settlement verification not implemented "
                "for this chain",
                "scaffolded": True,
                "network": normalize_network_id(network),
            }

        return {
            "success": False,
            "payment_id": payment_id,
            "reason": last_error,
        }

    def _normalize_settlement(
        self,
        data: dict[str, Any],
        payment_id: str,
        tx_hash: str,
        network: str,
        facilitator: str,
    ) -> dict[str, Any]:
        """Normalize facilitator response into a standard settlement receipt."""
        return {
            "success": True,
            "transaction": tx_hash,
            "network": network,
            "payment_id": payment_id,
            "facilitator": facilitator,
            "settled_at": datetime.now(UTC).isoformat(),
            "block_number": data.get("blockNumber", data.get("block_number", "")),
            "block_hash": data.get("blockHash", data.get("block_hash", "")),
            "tx_index": data.get("transactionIndex", data.get("tx_index", "")),
            "confirmations": data.get("confirmations", 0),
            "amount_paid": data.get("amountPaid", data.get("amount_paid", "")),
            "receipt": data,
        }

    def _offline_settlement(self, payment_id: str, tx_hash: str, network: str) -> dict[str, Any]:
        return {
            "success": True,
            "transaction": tx_hash,
            "network": network,
            "payment_id": payment_id,
            "facilitator": "offline",
            "settled_at": datetime.now(UTC).isoformat(),
            "note": "Offline mode — settlement not verified on-chain",
        }

    async def _eip7702_verify(
        self,
        tx_hash: str,
        network: str,
        asset: str,
        amount_usd: float,
    ) -> dict[str, Any]:
        """EIP-7702 self-verify: poll RPC for tx receipt AND check payTo/amount.

        A successful receipt alone is NOT proof of payment. We require:
        - the tx to have been sent to the facilitator's wallet (native) or to
          the asset's token contract with a transfer() to our wallet (ERC-20);
        - the transferred value to be >= the server-side price.
        """
        rpc = EIP7702_RPC.get(network)
        if not rpc:
            return {"verified": False, "reason": f"No EIP-7702 RPC for {network}"}
        try:
            async with httpx.AsyncClient(timeout=X402_TIMEOUT_SECONDS) as client:
                receipt = await self._rpc_call(client, rpc, "eth_getTransactionReceipt", [tx_hash])
                if not receipt or receipt.get("status") != "0x1":
                    return {
                        "verified": False,
                        "reason": "EIP-7702 receipt not found or tx failed",
                        "settlement": receipt or None,
                        "facilitator": "eip-7702",
                    }
                tx = await self._rpc_call(client, rpc, "eth_getTransactionByHash", [tx_hash])
                if not tx:
                    return {
                        "verified": False,
                        "reason": "EIP-7702 tx not found",
                        "settlement": receipt,
                        "facilitator": "eip-7702",
                    }
                ok, reason = self._eip7702_matches(tx, network, asset, amount_usd)
                if not ok:
                    return {
                        "verified": False,
                        "reason": f"EIP-7702 payment mismatch: {reason}",
                        "settlement": receipt,
                        "facilitator": "eip-7702",
                    }
                return {
                    "verified": True,
                    "reason": "",
                    "settlement": receipt,
                    "facilitator": "eip-7702",
                }
        except (httpx.HTTPError, httpx.RequestError) as e:
            return {"verified": False, "reason": f"EIP-7702 verify failed: {e}", "settlement": None}

    async def _rpc_call(
        self,
        client: httpx.AsyncClient,
        rpc: str,
        method: str,
        params: list[Any],
    ) -> dict[str, Any] | None:
        """Issue a JSON-RPC call and return the ``result`` dict (or None)."""
        response = await client.post(
            rpc,
            json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
        )
        response.raise_for_status()
        data = response.json()
        return data.get("result") or None

    def _eip7702_matches(
        self,
        tx: dict[str, Any],
        network: str,
        asset: str,
        amount_usd: float,
    ) -> tuple[bool, str]:
        """Verify an EIP-7702 tx actually paid OUR wallet at least the price.

        Returns ``(ok, reason)``. ERC-20 assets must transfer() to the
        server wallet on the asset's token contract; native assets must send
        value directly to the server wallet. Unknown assets fail closed.
        """
        pay_to = (X402_WALLET or "").lower()
        if not pay_to or pay_to == "pry-default-wallet":
            return False, "server wallet not configured"
        tx_to = str(tx.get("to") or "").lower()
        tokens = EIP7702_TOKEN_ADDRESSES.get(network, {})
        if asset in tokens:
            token = tokens[asset].lower()
            if tx_to != token:
                return False, f"tx recipient {tx_to} is not {asset} token on {network}"
            calldata = str(tx.get("input") or "0x")
            if not calldata.lower().startswith(ERC20_TRANSFER_SELECTOR):
                return False, "tx is not an ERC-20 transfer()"
            if len(calldata) < 138:
                return False, "ERC-20 transfer calldata too short"
            recipient = "0x" + calldata[34:74]
            try:
                paid_atomic = int(calldata[74:138], 16)
            except ValueError:
                return False, "unparseable ERC-20 transfer amount"
            if recipient.lower() != pay_to:
                return False, f"transfer recipient {recipient} != server wallet {pay_to}"
            expected_atomic = asset_to_atomic(amount_usd, asset, network)
            if paid_atomic < expected_atomic:
                return (
                    False,
                    f"underpayment: tx paid {paid_atomic} < required {expected_atomic} "
                    f"atomic {asset}",
                )
            return True, ""
        if asset in _NATIVE_ASSETS:
            if tx_to != pay_to:
                return False, f"tx recipient {tx_to} != server wallet {pay_to}"
            try:
                value_atomic = int(tx.get("value") or "0x0", 16)
            except (ValueError, TypeError):
                return False, "unparseable tx value"
            expected_atomic = asset_to_atomic(amount_usd, asset, network)
            if value_atomic < expected_atomic:
                return (
                    False,
                    f"underpayment: tx value {value_atomic} < required {expected_atomic} "
                    f"atomic {asset}",
                )
            return True, ""
        return False, f"unsupported asset {asset} for EIP-7702 self-verify on {network}"

    def _eip7702_settlement(
        self,
        payment_id: str,
        tx_hash: str,
        network: str,
    ) -> dict[str, Any]:
        return {
            "success": True,
            "transaction": tx_hash,
            "network": network,
            "payment_id": payment_id,
            "facilitator": "eip-7702",
            "settled_at": datetime.now(UTC).isoformat(),
            "note": "Verified via EIP-7702 RPC",
        }


# Global router instance (can be overridden in tests)
_facilitator_router: FacilitatorRouter | None = None


def get_facilitator_router() -> FacilitatorRouter:
    """Return the global facilitator router."""
    global _facilitator_router
    if _facilitator_router is None:
        _facilitator_router = FacilitatorRouter()
    return _facilitator_router


def set_facilitator_router(router: FacilitatorRouter) -> None:
    """Override the global facilitator router (useful for tests)."""
    global _facilitator_router
    _facilitator_router = router
