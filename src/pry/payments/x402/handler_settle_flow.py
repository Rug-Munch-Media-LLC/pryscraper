"""Pry — the settle flow (idempotency, retry, hooks, persistence).

Operates on :class:`~pry.payments.x402.handler_settle_support.SettleContext`;
``handler_settle.SettleMixin`` supplies the public entry points.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from pry.payments.x402.handler_settle_support import (
    SettleContext,
    _enrich_record,
    _retry_after_seconds,
)
from pry.payments.x402.handler_verify import _extension_header
from pry.payments.x402.metrics import record_settle

logger = logging.getLogger(__name__)


def _db_idempotent_cached(self: Any, key: str) -> dict[str, Any] | None:
    """DB-first idempotency: authoritative across processes AND hosts."""
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


def _cached_settlement(self: Any, ctx: SettleContext) -> dict[str, Any] | None:
    """Return an already-settled receipt for this key, if any."""
    cached = _db_idempotent_cached(self, ctx.key)
    if cached is not None:
        return cached
    if ctx.key and ctx.key in self._settled_txs:
        logger.info("x402_settle_idempotent", extra={"settle_key": ctx.key})
        return self._settled_txs[ctx.key]
    return None


def _pre_settle_aborted(self: Any, ctx: SettleContext) -> dict[str, Any] | None:
    """Run pre-settle hooks; return an abort receipt if any hook aborts."""
    for hook in self._pre_settle_hooks:
        result = hook(
            payment_id=ctx.payment_id,
            tx_hash=ctx.tx_hash,
            network=ctx.network,
            asset=ctx.asset,
            amount_usd=ctx.amount_usd,
        )
        if isinstance(result, dict) and result.get("abort"):
            return {
                "success": False,
                "error": result.get("reason", "aborted by pre-settle hook"),
            }
    return None


async def _settle_with_retry(self: Any, ctx: SettleContext) -> dict[str, Any] | None:
    """Call the facilitator settle with bounded retry/backoff."""
    settlement = None
    for attempt in range(4):
        try:
            settlement = await self.router.settle(
                payment_id=ctx.payment_id,
                tx_hash=ctx.tx_hash,
                network=ctx.network,
                asset=ctx.asset,
                amount_usd=ctx.amount_usd,
            )
            break
        except Exception as exc:
            delay = _retry_after_seconds(exc, attempt)
            if attempt >= 3:
                raise
            logger.warning(
                "x402_settle_retry",
                extra={
                    "payment_id": ctx.payment_id,
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


async def _notify_success(self: Any, ctx: SettleContext, record: dict[str, Any]) -> None:
    """Record usage and fire the settlement webhook — new settlements only."""
    self.usage.record(ctx.payment_id, amount_usd=ctx.amount_usd, network=ctx.network)
    try:
        # Late-bound via the handler module so tests can patch
        # ``pry.payments.x402.handler.fire_settlement_webhook``.
        from pry.payments.x402.handler import fire_settlement_webhook

        await fire_settlement_webhook(record)
    except Exception as e:  # noqa: BLE001 — best-effort, never break settle
        logger.warning(
            "x402_settlement_webhook_error",
            extra={"payment_id": ctx.payment_id, "error": str(e)},
        )


async def _settle_locked(self: Any, ctx: SettleContext) -> tuple[Any, dict[str, Any]]:
    """Settle and index under the verify lock; returns (raw settlement, record)."""
    settlement = await _settle_with_retry(self, ctx)
    record = _enrich_record(settlement, ctx.payment_id, ctx.tx_hash, ctx.network, ctx.asset)
    if record.get("success") is True and ctx.key:
        self._settled_txs.setdefault(ctx.key, record)
    _run_post_settle_hooks(self, record, ctx.payment_id)
    return settlement, record


def _persist_settle(self: Any, record: dict[str, Any], ctx: SettleContext) -> None:
    """Write the ledger row and the settlement metric (success-weighted)."""
    self._record_settlement(record)
    success = record.get("success") is True
    record_settle(
        ctx.network,
        success=success,
        amount_usd=ctx.amount_usd if success else 0.0,
        asset=ctx.asset,
    )


def _finalize_receipt(settlement: Any, ctx: SettleContext) -> dict[str, Any]:
    """Return the receipt callers see, failing closed when the facilitator is mute."""
    if settlement is None:
        logger.warning(
            "x402_settle_no_receipt",
            extra={"payment_id": ctx.payment_id, "tx_hash": ctx.tx_hash, "network": ctx.network},
        )
        return {"success": False, "reason": "empty settlement response"}
    settlement["extension_responses"] = _extension_header(settlement)
    return settlement
