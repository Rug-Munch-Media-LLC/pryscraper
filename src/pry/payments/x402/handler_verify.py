"""Pry — X402Handler verify mixin.

Extracted from handler.py: ``verify_payment`` / ``verify_payment_strict``
plus the verify-failure hook fan-out and the out-of-band extension header
encoder. Mixed into :class:`~pry.payments.x402.handler.X402Handler`, which
owns the shared state (router, hooks, ledger, ``_verify_lock``).
"""
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import base64
import json
import logging
from typing import Any

from pry.payments.x402 import X402_DEFAULT_ASSET, X402_DEFAULT_NETWORK
from pry.payments.x402.handler_verify_gate import (
    _resolve_fallback_amount,
    _resolve_server_amount,
    _run_pre_verify_hooks,
)
from pry.payments.x402.handler_verify_record import (
    _apply_verify_outcome,
    _record_verified_payment,
    fire_verify_failure_hooks,
)
from pry.payments.x402.metrics import record_operation_call, record_verify_failure

logger = logging.getLogger(__name__)


def _extension_header(result: dict[str, Any]) -> str:
    """Encode out-of-band extension data as base64 for EXTENSION-RESPONSES header."""
    extras = {
        k: v for k, v in result.items() if k not in ("verified", "reason", "success", "settlement")
    }
    return base64.b64encode(json.dumps(extras).encode()).decode()


class VerifyError(Exception):
    """Payment verification failed."""

    def __init__(self, reason: str, **extra: Any):
        self.reason = reason
        self.extra = extra
        super().__init__(reason)


class VerifyMixin:
    """Payment verification methods for X402Handler."""

    async def verify_payment(
        self,
        payment_id: str,
        tx_hash: str,
        network: str = "",
        asset: str = "",
        amount_usd: float = 0.0,
        operation: str = "",
        caller_key: str = "",
        attested_required_atomic: int = 0,
    ) -> dict[str, Any]:
        """Verify a payment via the x402 facilitator router.

        In production this calls POST /verify on the configured facilitator(s).
        Offline mode accepts the payment record directly for self-hosted Pry.

        Server-side pricing is authoritative: when ``operation`` is known the
        configured price is used and any client-supplied ``amount_usd`` is
        ignored. The recorded payment carries an ``expires_at`` and a
        ``caller_key`` so ``is_paid()`` can reject stale/replayed ids.

        ``attested_required_atomic`` (price binding, audit #7): when > 0 the
        attested challenge's SIGNED ``maxAmountRequired`` is forwarded to the
        facilitator as the authoritative required amount for volatile-asset
        comparison. The cross-operation price check (``validate_client_amount``)
        is UNCHANGED — only the source of the expected atomic amount changes.

        Pre-gates live in :mod:`.handler_verify_gate`; the replay-guarded record
        and outcome fan-out in :mod:`.handler_verify_record`.
        """
        network = network or X402_DEFAULT_NETWORK
        asset = asset or X402_DEFAULT_ASSET
        record_operation_call(operation)
        # Pre-verify hooks (before the lock): may abort verification outright.
        abort = _run_pre_verify_hooks(self, payment_id, tx_hash, network, asset, amount_usd)
        if abort is not None:
            return abort
        # Server-authoritative pricing: validate the client amount, then resolve
        # the configured price per (operation, network, asset) in integer atoms.
        # client-supplied ``amount_usd`` is ignored for the required price;
        # underpayment, non-finite and negative amounts are refused.
        abort, amount_usd = _resolve_server_amount(operation, amount_usd, asset, network)
        if abort is not None:
            return abort
        # Fail closed: never default to a hardcoded $0.001 price. If no
        # server-authoritative price is resolvable (operation unknown), refuse.
        abort, amount_usd = _resolve_fallback_amount(payment_id, operation, amount_usd, network)
        if abort is not None:
            return abort

        try:
            result = await self.router.verify(
                payment_id=payment_id,
                tx_hash=tx_hash,
                network=network,
                asset=asset,
                amount_usd=amount_usd,
                attested_required_atomic=attested_required_atomic,
            )
        except Exception as e:  # noqa: BLE001 — fail closed on facilitator error
            logger.warning(
                "x402_verify_router_error", extra={"payment_id": payment_id, "error": str(e)}
            )
            fire_verify_failure_hooks(
                self,
                payment_id=payment_id,
                tx_hash=tx_hash,
                network=network,
                asset=asset,
                reason=f"facilitator error: {e}",
            )
            record_verify_failure(network, f"facilitator error: {e}")
            return {"verified": False, "reason": f"facilitator error: {e}", "settlement": None}
        # Replay-hardening (fix #1): a tx_hash may only be consumed once, and the
        # check-then-record sequence is serialized under ``_verify_lock`` so two
        # concurrent requests carrying the same tx_hash cannot both pass. The lock
        # is class-level, so it is shared across per-request handler instances.
        abort, payment_record = _record_verified_payment(
            self,
            result,
            payment_id=payment_id,
            tx_hash=tx_hash,
            network=network,
            asset=asset,
            amount_usd=amount_usd,
            operation=operation,
            caller_key=caller_key,
        )
        if abort is not None:
            return abort
        _apply_verify_outcome(
            self,
            result,
            payment_record,
            payment_id=payment_id,
            tx_hash=tx_hash,
            network=network,
            asset=asset,
            amount_usd=amount_usd,
            operation=operation,
            caller_key=caller_key,
        )
        result["extension_responses"] = _extension_header(result)
        return result

    async def verify_payment_strict(
        self,
        payment_id: str,
        tx_hash: str,
        network: str = "",
        asset: str = "",
        amount_usd: float = 0.0,
        operation: str = "",
        caller_key: str = "",
        attested_required_atomic: int = 0,
    ) -> dict[str, Any]:
        """Verify a payment, raising :class:`VerifyError` on failure.

        Thin wrapper over :meth:`verify_payment` for callers who prefer
        try/except over inspecting the ``verified`` flag. On success the
        underlying result dict is returned unchanged.
        """
        result = await self.verify_payment(
            payment_id=payment_id,
            tx_hash=tx_hash,
            network=network,
            asset=asset,
            amount_usd=amount_usd,
            operation=operation,
            caller_key=caller_key,
            attested_required_atomic=attested_required_atomic,
        )
        if not result.get("verified"):
            raise VerifyError(
                result.get("reason", "verification failed"),
                payment_id=payment_id,
                tx_hash=tx_hash,
                network=network,
                asset=asset,
            )
        return result
