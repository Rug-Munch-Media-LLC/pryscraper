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
import math
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx

from pry.payments.x402 import (
    EIP7702_RPC,
    EIP7702_TOKEN_ADDRESSES,
    X402_NETWORK_WALLETS,
    X402_OFFLINE_MODE,
    X402_PLACEHOLDER_WALLETS,
    X402_SELF_FACILITATE,
    X402_SELF_FACILITATOR_KEY,
    X402_SELF_FACILITATOR_RPC,
    X402_TIMEOUT_SECONDS,
    X402_WALLET,
    is_solana_address,
    is_tron_address,
)
from pry.payments.x402.scheme import (
    _NATIVE_ASSETS,
    X402Scheme,
    asset_to_atomic,
    get_asset_usd_price,
    network_family,
    network_verification_status,
    normalize_network_id,
    resolve_asset_entry,
    resolve_pay_to,
)
from pry.payments.x402.self_facilitator import SelfFacilitator, VerifyResult

# Reverse map: CAIP-2 ID -> short name (for EIP7702_RPC key lookup).
# EIP7702_RPC uses legacy short names ("base", "ethereum", ...) but the
# verify flow receives CAIP-2 IDs ("eip155:8453"). Without this lookup the
# EIP-7702 on-chain fallback never runs for any EVM chain.
_CAIP2_TO_SHORT: dict[str, str] = {
    v: k
    for k, v in {
        "base": "eip155:8453",
        "ethereum": "eip155:1",
        "arbitrum": "eip155:42161",
        "optimism": "eip155:10",
        "polygon": "eip155:137",
        "bnb": "eip155:56",
        "avalanche": "eip155:43114",
        "base-sepolia": "eip155:84532",
        "ethereum-sepolia": "eip155:11155111",
    }.items()
}


def _eip7702_rpc_key(network: str) -> str | None:
    """Resolve a network (CAIP-2 or short name) to its EIP7702_RPC key.

    Returns the key ONLY when a matching EIP7702_RPC entry exists, so the
    ``is not None`` guard sites never claim EIP-7702 support for a chain
    that has no RPC configured (e.g. ethereum-sepolia in the reverse map).
    """
    if network in EIP7702_RPC:
        return network
    short = _CAIP2_TO_SHORT.get(normalize_network_id(network))
    if short is not None and short in EIP7702_RPC:
        return short
    return None


logger = logging.getLogger(__name__)

# ERC-20 transfer(address,uint256) selector — used to parse token payments.
ERC20_TRANSFER_SELECTOR = "0xa9059cbb"

# Chains with NO real on-chain settlement verification implemented yet.
# Payments for these networks validate structure/price/asset server-side and
# then report "needs_facilitator" — they are NOT claimed as verified. [REVIEW]
# Solana was moved to a REAL on-chain verifier (x402.solana_verifier — SPL RPC
# getTransaction jsonParsed); TRON stays scaffolded until a TRC-20 verifier
# exists.
SCAFFOLDED_NETWORKS: set[str] = {"tron:mainnet"}


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

    ``self_hosted`` mode (default off; opt-in via ``PRY_X402_SELF_FACILITATE=1``
    or the constructor arg) uses :class:`SelfFacilitator` INSTEAD of the
    external facilitator URLs — no Coinbase/CDP dependency. Custom per-network
    implementations can be plugged in via :meth:`register_facilitator`
    (the Solana/TRON extension point).
    """

    def __init__(
        self,
        facilitators: list[FacilitatorConfig] | None = None,
        self_hosted: bool | None = None,
    ) -> None:
        self.facilitators = sorted(
            [f for f in (facilitators or DEFAULT_FACILITATORS) if f.enabled and f.verify_url],
            key=lambda f: f.priority,
        )
        self._failures: dict[str, int] = {}
        self.self_hosted = X402_SELF_FACILITATE if self_hosted is None else bool(self_hosted)
        self._self_facilitator: SelfFacilitator | None = None
        self._network_facilitators: dict[str, Any] = {}
        self._pending_auths: dict[str, dict[str, Any]] = {}

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

    # ── Self-hosted / custom facilitator extension points ─────────────────────

    def register_facilitator(self, network: str, impl: Any) -> None:
        """Register a custom facilitator implementation for a network.

        Extension point for custom verifiers (e.g. TRON, which is still
        scaffolded): when an impl is registered for a network, verify/settle
        are routed to it instead of the external facilitators or the built-in
        SelfFacilitator. The impl must expose the SelfFacilitator contract:

        - ``async verify(payment: dict) -> VerifyResult``
        - ``async settle(payment: dict) -> str | None`` (tx hash or None)

        ``network`` may be a legacy name ("solana"), a CAIP-2 id
        ("solana:mainnet"), or a family ("solana", "tron", "evm").
        """
        network_id = normalize_network_id(network)
        self._network_facilitators[network_id] = impl
        if ":" not in network:
            self._network_facilitators[network] = impl

    def submit_authorization(self, payment_id: str, authorization: dict[str, Any]) -> None:
        """Attach an EIP-3009 transferWithAuthorization to a pending payment.

        Stored in memory keyed by ``payment_id`` so a later
        ``verify(payment_id, ...)`` / ``settle(payment_id, ...)`` can
        self-verify and self-settle it without an external facilitator.
        """
        self._pending_auths[payment_id] = authorization

    def readiness(self) -> dict[str, Any]:
        """Facilitator readiness probe (no network I/O).

        Returns ``{"mode", "ready", "wallet_configured"}``. ``mode`` is
        ``"self_hosted"`` (EIP-3009 SelfFacilitator) or ``"external"``
        (configured facilitator URLs). ``ready`` means the wallet is
        configured AND the selected mode can actually broadcast/settle:
        self-hosted requires an RPC URL, external requires at least one
        enabled facilitator with a verify URL.
        """
        wallet = (X402_WALLET or "").strip()
        wallet_configured = bool(wallet and wallet not in X402_PLACEHOLDER_WALLETS)
        mode = "self_hosted" if self.self_hosted else "external"
        if self.self_hosted:
            fac = self._get_self_facilitator()
            ready = wallet_configured and bool(fac.rpc_url)
        else:
            ready = wallet_configured and any(f.enabled and f.verify_url for f in self.facilitators)
        return {
            "mode": mode,
            "ready": ready,
            "wallet_configured": wallet_configured,
        }

    def settlement_stats(self) -> dict[str, Any]:
        """Settlement health counters for the /v1/x402/health endpoint.

        ``nonces_seen`` is the self-hosted replay-nonce store size;
        ``pending`` is the count of settlement attempts currently in-flight
        (self-hosted) or pending authorizations awaiting processing
        (external mode).
        """
        if self.self_hosted or self._self_facilitator is not None:
            fac = self._get_self_facilitator()
            nonces = fac.nonces.count
            pending = fac.pending_count
        else:
            nonces = 0
            pending = len(self._pending_auths)
        return {"nonces_seen": nonces, "pending": pending}

    def _impl_for(self, network: str) -> Any | None:
        """Return a registered custom facilitator for a network, if any."""
        network_id = normalize_network_id(network)
        impl = self._network_facilitators.get(network_id)
        if impl is not None:
            return impl
        impl = self._network_facilitators.get(network)
        if impl is not None:
            return impl
        return self._network_facilitators.get(network_family(network))

    def _get_self_facilitator(self) -> SelfFacilitator:
        """Lazily build the built-in SelfFacilitator (env-configured)."""
        if self._self_facilitator is None:
            self._self_facilitator = SelfFacilitator(
                pay_to=X402_WALLET,
                facilitator_key=X402_SELF_FACILITATOR_KEY,
                rpc_url=X402_SELF_FACILITATOR_RPC,
            )
        return self._self_facilitator

    def _build_payment(
        self,
        payment_id: str,
        tx_hash: str,
        network: str,
        asset: str,
        amount_usd: float,
    ) -> dict[str, Any]:
        """Build the payment dict handed to SelfFacilitator/custom impls."""
        payment: dict[str, Any] = {
            "payment_id": payment_id,
            "tx_hash": tx_hash,
            "network": network,
            "asset": asset,
            "amount_usd": amount_usd,
        }
        auth = self._pending_auths.get(payment_id)
        if auth:
            payment["authorization"] = auth
        return payment

    async def _verify_self_hosted(
        self,
        payment_id: str,
        tx_hash: str,
        network: str,
        asset: str,
        amount_usd: float,
    ) -> dict[str, Any]:
        """Verify via a registered custom impl or the built-in SelfFacilitator.

        EVM chains keep the EIP-7702 receipt check as a ground-truth fallback
        (native / permit2 assets and txs that already paid on-chain); the
        external facilitator URLs are never contacted in self-hosted mode.
        Solana verifies on-chain via the SPL RPC verifier
        (``x402.solana_verifier``); TRON stays scaffolded unless an impl is
        registered.
        """
        impl = self._impl_for(network)
        if impl is None:
            impl = self._get_self_facilitator()
        payment = self._build_payment(payment_id, tx_hash, network, asset, amount_usd)
        result: VerifyResult = await impl.verify(payment)
        if result.verified:
            return {
                "verified": True,
                "reason": "",
                "settlement": None,
                "facilitator": "self-hosted",
                "signer": result.signer,
                "amount_atomic": result.amount_atomic,
                "network": result.network or normalize_network_id(network),
                "asset": result.asset or asset,
            }

        if _eip7702_rpc_key(network) is not None:
            eip_result = await self._eip7702_verify(tx_hash, network, asset, amount_usd)
            if eip_result["verified"]:
                eip_result["facilitator"] = "self-hosted-eip7702"
                return eip_result
            reason = f"{result.reason}; EIP-7702: {eip_result.get('reason', '')}"
        else:
            reason = result.reason

        if network_family(network) == "solana":
            return await self._verify_solana(payment_id, tx_hash, network, asset, amount_usd)
        if network_family(network) == "tron":
            return self._scaffold_non_evm_verify(payment_id, tx_hash, network, asset, amount_usd)

        return {
            "verified": False,
            "reason": reason,
            "settlement": None,
            "facilitator": "self-hosted",
        }

    async def _settle_self_hosted(
        self,
        payment_id: str,
        tx_hash: str,
        network: str,
        asset: str,
        amount_usd: float,
    ) -> dict[str, Any]:
        """Settle via a registered custom impl or the built-in SelfFacilitator.

        When the impl cannot broadcast (a plain on-chain transfer carries no
        EIP-3009 authorization), fall through to the EIP-7702 settlement
        receipt for supported networks — mirroring ``_verify_self_hosted``.
        The settle leg only runs AFTER the verify leg cryptographically
        confirmed the tx paid the server wallet, so the receipt is honest.
        Without this fallback a verified plain transfer could never settle
        (verify ✓ → settle ✗ → fail-closed 402 forever).
        """
        impl = self._impl_for(network)
        if impl is None:
            impl = self._get_self_facilitator()
        payment = self._build_payment(payment_id, tx_hash, network, asset, amount_usd)
        settled_tx = await impl.settle(payment)
        if settled_tx:
            return {
                "success": True,
                "transaction": settled_tx,
                "network": network,
                "payment_id": payment_id,
                "facilitator": "self-hosted",
                "settled_at": datetime.now(UTC).isoformat(),
                "note": "Broadcast by self-hosted facilitator",
            }
        if _eip7702_rpc_key(network) is not None:
            return self._eip7702_settlement(payment_id, tx_hash, network)
        return {
            "success": False,
            "payment_id": payment_id,
            "reason": (
                "self-hosted settle unavailable: no authorization, no facilitator "
                "key/RPC, or chain unreachable"
            ),
            "facilitator": "self-hosted",
        }

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
        EIP-7702 self-verify fallback. Solana verifies on-chain via the SPL
        RPC verifier (``x402.solana_verifier``). TRON (SCAFFOLDED_NETWORKS)
        validates structure/price/asset and then reports "needs_facilitator"
        — it is never claimed verified without a real verifier. [REVIEW]
        """
        if X402_OFFLINE_MODE:
            return {"verified": True, "reason": "offline_mode", "settlement": None}

        # Self-hosted mode: verify locally instead of contacting the external
        # facilitator URLs (no Coinbase/CDP). Registered per-network impls
        # take precedence over the built-in SelfFacilitator.
        if self.self_hosted or self._impl_for(network) is not None:
            return await self._verify_self_hosted(payment_id, tx_hash, network, asset, amount_usd)

        payload = {
            "paymentId": payment_id,
            "transactionHash": tx_hash,
            "network": network,
            "asset": asset,
            "amount": str(asset_to_atomic(amount_usd, asset, network)),
            "payToAddress": (resolve_pay_to(network) or ""),
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
        if _eip7702_rpc_key(network) is not None:
            result = await self._eip7702_verify(tx_hash, network, asset, amount_usd)
            if result["verified"]:
                return result
            last_error = result.get("reason", last_error)

        # Non-EVM chains: Solana verifies on-chain via the SPL RPC verifier;
        # TRON verifies on-chain via the TRC-20 Grid verifier.
        if network_family(network) == "solana":
            return await self._verify_solana(payment_id, tx_hash, network, asset, amount_usd)
        if network_family(network) == "tron":
            return await self._verify_tron(payment_id, tx_hash, network, asset, amount_usd)

        return {"verified": False, "reason": last_error, "settlement": None}

    async def _verify_solana(
        self,
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
        if not recipient or recipient == "pry-default-wallet" or not is_solana_address(recipient):
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
        except ImportError:
            # Module absent (older checkout) — keep the honest scaffold path.
            return self._scaffold_non_evm_verify(payment_id, tx_hash, network, asset, amount_usd)

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

    async def _verify_tron(
        self,
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
        if not recipient or recipient == "pry-default-wallet" or not is_tron_address(recipient):
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
        except ImportError:
            return self._scaffold_non_evm_verify(payment_id, tx_hash, network, asset, amount_usd)

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

    def _scaffold_non_evm_verify(
        self,
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
        see ``_verify_solana``.)
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

        # Self-hosted mode: settle locally instead of contacting the external
        # facilitator URLs (no Coinbase/CDP).
        if self.self_hosted or self._impl_for(network) is not None:
            return await self._settle_self_hosted(payment_id, tx_hash, network, asset, amount_usd)

        payload = {
            "paymentId": payment_id,
            "transactionHash": tx_hash,
            "network": network,
            "asset": asset,
            "amount": str(asset_to_atomic(amount_usd, asset, network)),
            "payToAddress": (resolve_pay_to(network) or ""),
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
        if _eip7702_rpc_key(network) is not None:
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
        rpc = EIP7702_RPC.get(_eip7702_rpc_key(network) or network)
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
        pay_to = (resolve_pay_to(network) or "").lower()
        if not pay_to or pay_to == "pry-default-wallet":
            return False, "server wallet not configured"
        tx_to = str(tx.get("to") or "").lower()
        tokens = EIP7702_TOKEN_ADDRESSES.get(_eip7702_rpc_key(network) or network, {})
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


def register_facilitator(network: str, impl: Any) -> None:
    """Register a custom facilitator for ``network`` on the global router.

    Convenience wrapper over :meth:`FacilitatorRouter.register_facilitator`.
    Use this to plug in a custom verifier (e.g. TRON, which remains
    scaffolded until an impl is registered). ``impl`` must expose
    ``async verify(payment) -> VerifyResult`` and
    ``async settle(payment) -> str | None``.
    """
    get_facilitator_router().register_facilitator(network, impl)
