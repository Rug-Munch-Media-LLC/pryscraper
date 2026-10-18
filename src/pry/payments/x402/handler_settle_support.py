"""Pry — settle input normalisation (amount, retry delay, audit record).

Pure helpers plus the :class:`SettleContext` value object. The settle flow
itself (idempotency, retry loop, hooks, persistence) lives in
``handler_settle_flow``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from pry.payments.x402 import X402_DEFAULT_ASSET, X402_DEFAULT_NETWORK

logger = logging.getLogger(__name__)

_SETTLE_OPTION_KEYS = frozenset({"network", "asset", "amount_usd", "operation"})


@dataclass(frozen=True)
class SettleContext:
    """Everything one settle call needs, resolved once."""

    payment_id: str
    tx_hash: str
    network: str
    asset: str
    amount_usd: float
    operation: str
    key: str


def _retry_after_seconds(exc: Exception, attempt: int) -> float:
    """Parse Retry-After from httpx error responses when present."""
    try:
        retry_after = int(
            (getattr(exc, "response", None) and exc.response.headers.get("Retry-After", "0")) or "0"
        )
    except (ValueError, TypeError) as err:
        logger.warning(
            "payments_exception_swallowed",
            extra={"error": str(err), "handler": "_retry_after_seconds"},
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
    """Self-describing audit record (payment_id/tx_hash/network/asset)."""
    record = dict(settlement or {})
    record.setdefault("payment_id", payment_id)
    record.setdefault("tx_hash", tx_hash)
    record.setdefault("network", network)
    record.setdefault("asset", asset)
    return record


def _settle_context(
    self: Any, payment_id: str, tx_hash: str, options: dict[str, Any]
) -> SettleContext:
    """Normalise the public keyword options into a :class:`SettleContext`."""
    unknown = set(options) - _SETTLE_OPTION_KEYS
    if unknown:
        raise TypeError(f"unexpected settle options: {sorted(unknown)}")
    network = str(options.get("network") or X402_DEFAULT_NETWORK)
    asset = str(options.get("asset") or X402_DEFAULT_ASSET)
    operation = str(options.get("operation") or "")
    amount_usd = float(options.get("amount_usd") or 0.0)
    key = self._settlement_key(
        {"payment_id": payment_id, "tx_hash": tx_hash, "network": network, "asset": asset}
    )
    return SettleContext(payment_id, tx_hash, network, asset, amount_usd, operation, key)
