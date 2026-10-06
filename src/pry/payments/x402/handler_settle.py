"""Pry — X402Handler settle mixin.

Extracted from handler.py: ``settle_payment`` / ``settle_payment_strict``
with idempotent settlement caching, retry/backoff and the settlement
webhook. Mixed into :class:`~pry.payments.x402.handler.X402Handler`, which
owns the shared state (router, hooks, ledger, ``_verify_lock``,
``_settled_txs``).
"""
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import asyncio
import logging
from typing import Any

from pry.payments.x402 import X402_DEFAULT_ASSET, X402_DEFAULT_NETWORK
from pry.payments.x402.handler_verify import _extension_header
from pry.payments.x402.metrics import record_settle
from pry.payments.x402.scheme import X402_PRICING, resolve_price_usd

logger = logging.getLogger(__name__)


def _resolve_amount(
    payment_id: str,
    network: str,
    asset: str,
    amount_usd: float,
    operation: str,
) -> float:
    """Resolve the server-authoritative amount for the receipt."""
    if operation:
        # Resolve the server-authoritative price per (operation, network,
        # asset); ignore any client-supplied amount for the receipt.
        amount_usd = resolve_price_usd(operation, network=network, asset=asset)
    if amount_usd <= 0:
        amount_usd = X402_PRICING.get(payment_id, {}).get("price_usd", 0.001)
    return amount_usd


def _retry_after_seconds(exc: Exception, attempt: int) -> float:
    """Parse Retry-After from httpx error responses when present."""
    try:
        retry_after = int(
            (getattr(exc, "response", None) and exc.response.headers.get("Retry-After", "0")) or "0"
        )
    except (ValueError, TypeError) as exc:
        logger.warning(
            "payments_exception_swallowed",
            extra={"error": str(exc), "handler": "_retry_after_seconds"},
        )
        retry_after = 0
    return min(max(retry_after, 0.5 * 2**attempt), 30)


def _enrich_record(
    settlement: dict[str, Any] | None,
    payment_id: str,
    tx_hash: str,
    network: str,
    asset: str,
) -> dict[str, Any]:
    """Enrich the settlement audit record with the identity fields so the
    JSONL ledger is self-describing (payment_id/tx_hash/network/asset)."""
    record = dict(settlement or {})
    record.setdefault("payment_id", payment_id)
    record.setdefault("tx_hash", tx_hash)
    record.setdefault("network", network)
    record.setdefault("asset", asset)
    return record


def _db_idempotent_cached(self: Any, key: str) -> dict[str, Any] | None:
    """DB-first idempotency: authoritative across processes AND hosts (the
    in-memory index only sees this process's settles)."""
    if not (key and self._use_db):
        return None
    try:
        from pry.payments.x402.ledger_store import settlement_by_key

        cached = settlement_by_key(key)
        if cached is not None and cached.get("success") is True:
            self._settled_txs.setdefault(key, cached)
            logger.info("x402_settle_idempotent", extra={"settle_key": key})
            return cached
    except Exception as e:  # noqa: BLE001 — fall through to memory
        logger.warning("x402_settle_db_idempotency_failed", extra={"error": str(e)[:160]})
    return None


def _pre_settle_aborted(
    self: Any,
    payment_id: str,
    tx_hash: str,
    network: str,
    asset: str,
    amount_usd: float,
) -> dict[str, Any] | None:
    """Run pre-settle hooks; return an abort receipt if any hook aborts."""
    for hook in self._pre_settle_hooks:
        result = hook(
            payment_id=payment_id,
            tx_hash=tx_hash,
            network=network,
            asset=asset,
            amount_usd=amount_usd,
        )
        if isinstance(result, dict) and result.get("abort"):
            return {
                "success": False,
                "error": result.get("reason", "aborted by pre-settle hook"),
            }
    return None


async def _settle_with_retry(
    self: Any,
    payment_id: str,
    tx_hash: str,
    network: str,
    asset: str,
    amount_usd: float,
) -> dict[str, Any] | None:
    """Call the facilitator settle with bounded retry/backoff."""
    settlement = None
    for attempt in range(4):
        try:
            settlement = await self.router.settle(
                payment_id=payment_id,
                tx_hash=tx_hash,
                network=network,
                asset=asset,
                amount_usd=amount_usd,
            )
            break
        except Exception as exc:
            delay = _retry_after_seconds(exc, attempt)
            if attempt >= 3:
                raise
            logger.warning(
                "x402_settle_retry",
                extra={
                    "payment_id": payment_id,
                    "attempt": attempt,
                    "retry_after": int(delay),
                    "delay": delay,
                    "error": str(exc)[:160],
                },
            )
            await asyncio.sleep(delay)
    return settlement


def _run_post_settle_hooks(self: Any, record: dict[str, Any], payment_id: str) -> None:
    """Best-effort post-settle hooks; never break settle."""
    for hook in self._post_settle_hooks:
        try:
            hook(record)
        except Exception as e:  # noqa: BLE001 — best-effort, never break settle
            logger.debug(
                "x402_post_settle_hook_error",
                extra={"payment_id": payment_id, "error": str(e)},
            )


async def _notify_success(
    self: Any,
    record: dict[str, Any],
    payment_id: str,
    amount_usd: float,
    network: str,
) -> None:
    """Customer notification (audit item #8): fire the settlement webhook
    ONLY for genuinely new settlements — the idempotent-cache hit path
    above returns early, so a replayed settle never re-notifies."""
    self.usage.record(payment_id, amount_usd=amount_usd, network=network)
    try:
        # Late-bound via the handler module so tests can patch
        # ``pry.payments.x402.handler.fire_settlement_webhook``.
        from pry.payments.x402.handler import fire_settlement_webhook

        await fire_settlement_webhook(record)
    except Exception as e:  # noqa: BLE001 — best-effort, never break settle
        logger.warning(
            "x402_settlement_webhook_error",
            extra={"payment_id": payment_id, "error": str(e)},
        )


class SettleError(Exception):
    """Payment settlement failed."""

    def __init__(self, reason: str, **extra: Any):
        self.reason = reason
        self.extra = extra
        super().__init__(reason)


class SettleMixin:
    """Payment settlement methods for X402Handler."""

    async def settle_payment(
        self,
        payment_id: str,
        tx_hash: str,
        network: str = "",
        asset: str = "",
        amount_usd: float = 0.0,
        operation: str = "",
    ) -> dict[str, Any]:
        """Settle a payment via the facilitator router.

        Returns a settlement receipt (to be Base64-encoded in PAYMENT-RESPONSE header).
        """
        network = network or X402_DEFAULT_NETWORK
        asset = asset or X402_DEFAULT_ASSET
        amount_usd = _resolve_amount(payment_id, network, asset, amount_usd, operation)

        # Idempotency (fix #4): a settled tx must never duplicate ledger
        # entries. If this payment was already settled successfully, return the
        # cached receipt WITHOUT re-rolling the facilitator and WITHOUT appending
        # a second line to settlements.jsonl.
        key = self._settlement_key(
            {"payment_id": payment_id, "tx_hash": tx_hash, "network": network, "asset": asset}
        )
        # Serialize the check-then-settle sequence under _verify_lock to prevent
        # TOCTOU double-settle under concurrent requests (same lock as verify_payment).
        with self._verify_lock:
            cached = _db_idempotent_cached(self, key)
            if cached is not None:
                return cached
            if key and key in self._settled_txs:
                logger.info("x402_settle_idempotent", extra={"settle_key": key})
                return self._settled_txs[key]

            aborted = _pre_settle_aborted(self, payment_id, tx_hash, network, asset, amount_usd)
            if aborted is not None:
                return aborted

            settlement = await _settle_with_retry(
                self, payment_id, tx_hash, network, asset, amount_usd
            )
            # Enrich the settlement audit record with the identity fields so the
            # JSONL ledger is self-describing (payment_id/tx_hash/network/asset).
            record = _enrich_record(settlement, payment_id, tx_hash, network, asset)
            # Only index successful settles so a failed attempt can be retried.
            if record.get("success") is True and key:
                self._settled_txs.setdefault(key, record)
            _run_post_settle_hooks(self, record, payment_id)

        self._record_settlement(record)
        record_settle(
            network,
            success=record.get("success") is True,
            amount_usd=amount_usd if record.get("success") is True else 0.0,
            asset=asset,
        )
        # Customer notification (audit item #8): fire the settlement webhook
        # ONLY for genuinely new settlements — the idempotent-cache hit path
        # above returns early, so a replayed settle never re-notifies.
        if record.get("success") is True:
            await _notify_success(self, record, payment_id, amount_usd, network)
        if settlement is not None:
            settlement["extension_responses"] = _extension_header(settlement)
        return settlement

    async def settle_payment_strict(
        self,
        payment_id: str,
        tx_hash: str,
        network: str = "",
        asset: str = "",
        amount_usd: float = 0.0,
        operation: str = "",
    ) -> dict[str, Any]:
        """Settle a payment, raising :class:`SettleError` on failure.

        Thin wrapper over :meth:`settle_payment` for callers who prefer
        try/except over inspecting the ``success`` flag. On success the
        settlement receipt dict is returned unchanged.
        """
        settlement = await self.settle_payment(
            payment_id=payment_id,
            tx_hash=tx_hash,
            network=network,
            asset=asset,
            amount_usd=amount_usd,
            operation=operation,
        )
        if not (settlement or {}).get("success"):
            raise SettleError(
                (settlement or {}).get("reason", "settlement failed"),
                payment_id=payment_id,
                tx_hash=tx_hash,
                network=network,
                asset=asset,
            )
        return settlement
