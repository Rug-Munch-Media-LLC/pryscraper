"""Pry — x402 self-hosted facilitator orchestration mixin.

Extracted from ``facilitator.py``: self-hosted verify/settle routing
(custom per-network impls + built-in SelfFacilitator), readiness and
settlement-stats probes, and payment-dict construction.
"""
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from pry.payments.x402.facilitator_evm import _eip7702_rpc_key
from pry.payments.x402.scheme import network_family, normalize_network_id
from pry.payments.x402.self_facilitator import SelfFacilitator, VerifyResult

if TYPE_CHECKING:
    from pry.payments.x402.facilitator_config import FacilitatorConfig


class SelfHostedMixin:
    """Self-hosted verify/settle orchestration for FacilitatorRouter."""

    # Host-supplied state (declared here for type-checking only; the concrete
    # ``FacilitatorRouter.__init__`` assigns them). Bare annotations create no
    # runtime attributes, so mixin behaviour is unchanged.
    self_hosted: bool
    facilitators: list[FacilitatorConfig]
    _self_facilitator: SelfFacilitator | None
    _network_facilitators: dict[str, Any]
    _pending_auths: dict[str, dict[str, Any]]

    async def _eip7702_verify(
        self, tx_hash: str, network: str, asset: str, amount_usd: float
    ) -> dict[str, Any]:
        """EIP-7702 self-verify fallback (host-supplied; see DispatchMixin)."""
        raise NotImplementedError

    async def _verify_solana(
        self, payment_id: str, tx_hash: str, network: str, asset: str, amount_usd: float
    ) -> dict[str, Any]:
        """Solana on-chain verify (host-supplied; see DispatchMixin)."""
        raise NotImplementedError

    def _scaffold_non_evm_verify(
        self, payment_id: str, tx_hash: str, network: str, asset: str, amount_usd: float
    ) -> dict[str, Any]:
        """Scaffolded non-EVM verify (host-supplied; see DispatchMixin)."""
        raise NotImplementedError

    def _eip7702_settlement(self, payment_id: str, tx_hash: str, network: str) -> dict[str, Any]:
        """EIP-7702 settlement receipt (host-supplied; see DispatchMixin)."""
        raise NotImplementedError

    @staticmethod
    def _cfg(name: str) -> Any:
        """Read x402 config via the facilitator module so tests that
        monkeypatch ``facilitator.X402_*`` keep working (lazy import —
        the facilitator module imports this mixin at module level)."""
        import pry.payments.x402.facilitator as _fac

        return getattr(_fac, name)

    """Self-hosted verify/settle orchestration for FacilitatorRouter."""

    def readiness(self) -> dict[str, Any]:
        """Facilitator readiness probe (no network I/O).

        Returns ``{"mode", "ready", "wallet_configured"}``. ``mode`` is
        ``"self_hosted"`` (EIP-3009 SelfFacilitator) or ``"external"``
        (configured facilitator URLs). ``ready`` means the wallet is
        configured AND the selected mode can actually broadcast/settle:
        self-hosted requires an RPC URL, external requires at least one
        enabled facilitator with a verify URL.
        """
        wallet = (self._cfg("X402_WALLET") or "").strip()
        wallet_configured = bool(wallet and wallet not in self._cfg("X402_PLACEHOLDER_WALLETS"))
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
                pay_to=self._cfg("X402_WALLET"),
                facilitator_key=self._cfg("X402_SELF_FACILITATOR_KEY"),
                rpc_url=self._cfg("X402_SELF_FACILITATOR_RPC"),
            )
        return self._self_facilitator

    def _build_payment(
        self,
        payment_id: str,
        tx_hash: str,
        network: str,
        asset: str,
        amount_usd: float,
        attested_required_atomic: int = 0,
    ) -> dict[str, Any]:
        """Build the payment dict handed to SelfFacilitator/custom impls."""
        payment: dict[str, Any] = {
            "payment_id": payment_id,
            "tx_hash": tx_hash,
            "network": network,
            "asset": asset,
            "amount_usd": amount_usd,
        }
        if attested_required_atomic > 0:
            # Price binding (audit #7): the attested challenge amount is the
            # authoritative required amount for volatile-asset comparison.
            payment["attested_required_atomic"] = int(attested_required_atomic)
        auth = self._pending_auths.pop(payment_id, None)
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
        attested_required_atomic: int = 0,
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
        payment = self._build_payment(
            payment_id, tx_hash, network, asset, amount_usd, attested_required_atomic
        )
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
