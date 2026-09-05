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
from datetime import UTC, datetime, timedelta
from typing import Any

from pry.payments.x402 import (
    PAYMENT_VALIDITY_SECONDS,
    X402_DEFAULT_ASSET,
    X402_DEFAULT_NETWORK,
)
from pry.payments.x402.metrics import (
    record_operation_call,
    record_replay,
    record_verify_failure,
    record_verify_success,
)
from pry.payments.x402.scheme import (
    X402_PRICING,
    asset_to_atomic,
    resolve_price_usd,
    validate_client_amount,
)

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
        comparison. The cross-operation price check
        (``validate_client_amount``) is UNCHANGED — only the source of the
        expected atomic amount for the oracle-priced comparison changes.
        """
        network = network or X402_DEFAULT_NETWORK
        asset = asset or X402_DEFAULT_ASSET
        record_operation_call(operation)
        # Pre-verify hooks (before the lock): may abort verification outright.
        for hook in self._pre_verify_hooks:
            result = hook(
                payment_id=payment_id,
                tx_hash=tx_hash,
                network=network,
                asset=asset,
                amount_usd=amount_usd,
            )
            if isinstance(result, dict) and result.get("abort"):
                logger.info(
                    "x402_verify_aborted_by_pre_verify_hook",
                    extra={"payment_id": payment_id, "reason": result.get("reason", "")},
                )
                return {
                    "verified": False,
                    "reason": result.get("reason", "aborted by pre-verify hook"),
                    "settlement": None,
                }
        if operation:
            # Server-authoritative pricing, resolved per (operation, network,
            # asset) and compared in integer atoms. client-supplied
            # ``amount_usd`` is ignored for the required price; underpayment,
            # non-finite and negative amounts are refused. Overpayment allowed.
            ok, reason = validate_client_amount(operation, amount_usd, asset, network=network)
            if not ok:
                logger.warning(
                    "x402_verify_underpayment_rejected",
                    extra={"operation": operation, "reason": reason},
                )
                return {"verified": False, "reason": reason, "settlement": None}
            record_verify_failure(network, reason)
            amount_usd = resolve_price_usd(operation, network=network, asset=asset)
        if amount_usd <= 0:
            # Fail closed: never default to a hardcoded $0.001 price. If no
            # server-authoritative price is resolvable (operation unknown),
            # refuse the payment rather than accepting it at a made-up price.
            amount_usd = X402_PRICING.get(payment_id, {}).get("price_usd", 0.0)
            if amount_usd <= 0:
                logger.warning(
                    "x402_verify_pricing_unavailable",
                    extra={"operation": operation, "payment_id": payment_id},
                )
                return {
                    "verified": False,
                    "reason": "unknown operation: pricing unavailable",
                    "settlement": None,
                }
            record_verify_failure(network, "unknown operation: pricing unavailable")

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
            self._fire_verify_failure_hooks(
                payment_id=payment_id,
                tx_hash=tx_hash,
                network=network,
                asset=asset,
                reason=f"facilitator error: {e}",
            )
            record_verify_failure(network, f"facilitator error: {e}")
            return {"verified": False, "reason": f"facilitator error: {e}", "settlement": None}
        # Replay-hardening (fix #1): a tx_hash may only be consumed once. A payer
        # who swaps a fresh payment_id onto an already-verified tx_hash is trying
        # to mint unlimited payment_ids from one on-chain tx — refuse it.
        #
        # The check-then-record sequence is serialized under ``_verify_lock`` so
        # two concurrent requests carrying the same tx_hash cannot both pass the
        # ``_tx_consumed()`` check before either records the payment (double-spend
        # race). The lock is class-level, so it is shared across the fresh handler
        # instances created per request.
        with self._verify_lock:
            if result.get("verified") and self._tx_consumed(tx_hash):
                logger.warning(
                    "x402_verify_tx_replay_rejected",
                    extra={"payment_id": payment_id, "tx_hash": tx_hash},
                )
                return {
                    "verified": False,
                    "reason": "tx_hash already consumed",
                    "settlement": None,
                }
            record_replay(network)
            record_verify_failure(network, "tx_hash already consumed")
            # Server-authoritative atomic pricing: the verified payment records the
            # operation it was purchased for and the minimum amount (atomic units)
            # the server required at verify time. ``is_paid()`` re-checks both so a
            # cheap payment can never be replayed against a more expensive gated
            # operation, and a payment that under-pays the CURRENT price is refused.
            payment_record = {
                "payment_id": payment_id,
                "tx_hash": tx_hash,
                "network": network,
                "asset": asset,
                "amount_usd": amount_usd,
                "required_amount_atomic": asset_to_atomic(amount_usd, asset, network),
                "operation": operation,
                "verified": result["verified"],
                "reason": result.get("reason", ""),
                "facilitator": result.get("facilitator", ""),
                "caller_key": caller_key or "",
                "expires_at": (
                    datetime.now(UTC) + timedelta(seconds=PAYMENT_VALIDITY_SECONDS)
                ).isoformat(),
                "verified_at": datetime.now(UTC).isoformat(),
            }
            self._record_payment(payment_record)
        if result.get("verified"):
            record_verify_success(network)
            self.usage.record(
                caller_key or payment_id,
                amount_usd=amount_usd,
                endpoint=operation,
                network=network,
            )
            for hook in self._post_verify_hooks:
                try:
                    hook(payment_record)
                except Exception as e:  # noqa: BLE001 — best-effort, never break verify
                    logger.debug(
                        "x402_post_verify_hook_error",
                        extra={"payment_id": payment_id, "error": str(e)},
                    )
        else:
            record_verify_failure(network, result.get("reason", "verification failed"))
            self._fire_verify_failure_hooks(
                payment_id=payment_id,
                tx_hash=tx_hash,
                network=network,
                asset=asset,
                reason=result.get("reason", "verification failed"),
            )
        result["extension_responses"] = _extension_header(result)
        return result

    def _fire_verify_failure_hooks(
        self, payment_id: str, tx_hash: str, network: str, asset: str, reason: str
    ) -> None:
        """Best-effort on-verify-failure hooks — never break the verify flow."""
        for hook in self._on_verify_failure_hooks:
            try:
                hook(
                    payment_id=payment_id,
                    tx_hash=tx_hash,
                    network=network,
                    asset=asset,
                    reason=reason,
                )
            except Exception as e:  # noqa: BLE001 — best-effort
                logger.debug(
                    "x402_verify_failure_hook_error",
                    extra={"payment_id": payment_id, "error": str(e)},
                )

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

    async def authorize_payment(
        self,
        payment_id: str,
        tx_hash: str,
        network: str,
        asset: str,
        amount_usd: float = 0,
        caller_key: str = "",
        operation: str = "",
    ) -> dict[str, Any]:
        """Authorize a payment without capturing. Returns authorization record."""
        result = await self.verify_payment(
            payment_id, tx_hash, network, asset, amount_usd, caller_key, operation
        )
        if result.get("verified"):
            import time

            self._authorized_payments[payment_id] = {
                "tx_hash": tx_hash,
                "network": network,
                "asset": asset,
                "amount_usd": amount_usd,
                "authorized_at": time.time(),
            }
            return {"authorized": True, "payment_id": payment_id, "captured": False}
        return {"authorized": False, "reason": result.get("reason", "verification failed")}

    def capture_payment(self, payment_id: str) -> dict[str, Any]:
        """Capture a previously authorized payment."""
        auth = self._authorized_payments.pop(payment_id, None)
        if not auth:
            return {"success": False, "error": "no authorization found"}
        return {"success": True, "payment_id": payment_id, "captured": True}

    def void_payment(self, payment_id: str) -> dict[str, Any]:
        """Void a previously authorized payment without capturing."""
        self._authorized_payments.pop(payment_id, None)
        return {"success": True, "payment_id": payment_id, "voided": True}
