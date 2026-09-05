"""Pry — x402 facilitator chain dispatch (extracted from ``facilitator.py``).

Custom per-network facilitator registration, pending-authorization storage
and the chain-specific verification delegates (Solana / TRON / scaffolded
non-EVM / EIP-7702 self-verify). Mixed into
:class:`~pry.payments.x402.facilitator.FacilitatorRouter` as
``DispatchMixin``.
"""
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pry.payments.x402.facilitator_evm import (
    eip7702_matches,
    eip7702_settlement,
    eip7702_verify,
    rpc_call,
)
from pry.payments.x402.facilitator_solana_tron import (
    _scaffold_non_evm_verify,
    verify_solana,
    verify_tron,
)
from pry.payments.x402.scheme import normalize_network_id

if TYPE_CHECKING:
    import httpx


class DispatchMixin:
    """Chain dispatch + facilitator registration for the x402 router."""

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

    # ── Chain-specific verification (delegates to cohesive modules) ───────────

    async def _verify_solana(
        self,
        payment_id: str,
        tx_hash: str,
        network: str,
        asset: str,
        amount_usd: float,
    ) -> dict[str, Any]:
        """Verify a Solana payment on-chain — see ``facilitator_solana_tron``."""
        return await verify_solana(payment_id, tx_hash, network, asset, amount_usd)

    async def _verify_tron(
        self,
        payment_id: str,
        tx_hash: str,
        network: str,
        asset: str,
        amount_usd: float,
    ) -> dict[str, Any]:
        """Verify a TRON TRC-20 payment on-chain — see ``facilitator_solana_tron``."""
        return await verify_tron(payment_id, tx_hash, network, asset, amount_usd)

    def _scaffold_non_evm_verify(
        self,
        payment_id: str,
        tx_hash: str,
        network: str,
        asset: str,
        amount_usd: float,
    ) -> dict[str, Any]:
        """[REVIEW] Scaffolded non-EVM acceptance — see ``facilitator_solana_tron``."""
        return _scaffold_non_evm_verify(payment_id, tx_hash, network, asset, amount_usd)

    # ── EIP-7702 self-verify fallback (delegates to facilitator_evm) ──────────

    async def _eip7702_verify(
        self,
        tx_hash: str,
        network: str,
        asset: str,
        amount_usd: float,
    ) -> dict[str, Any]:
        """EIP-7702 self-verify: poll RPC for tx receipt AND check payTo/amount."""
        return await eip7702_verify(tx_hash, network, asset, amount_usd)

    async def _rpc_call(
        self,
        client: httpx.AsyncClient,
        rpc: str,
        method: str,
        params: list[Any],
    ) -> dict[str, Any] | None:
        """Issue a JSON-RPC call and return the ``result`` dict (or None)."""
        return await rpc_call(client, rpc, method, params)

    def _eip7702_matches(
        self,
        tx: dict[str, Any],
        network: str,
        asset: str,
        amount_usd: float,
    ) -> tuple[bool, str]:
        """Verify an EIP-7702 tx actually paid OUR wallet at least the price."""
        return eip7702_matches(tx, network, asset, amount_usd)

    def _eip7702_settlement(
        self,
        payment_id: str,
        tx_hash: str,
        network: str,
    ) -> dict[str, Any]:
        return eip7702_settlement(payment_id, tx_hash, network)
