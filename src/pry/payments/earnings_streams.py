"""Pry — earnings stream loaders.

Stream loaders for :class:`pry.payments.earnings.EarningsTracker`. Each returns
a list of ``{amount_usd, date, ...}`` entries for one revenue stream:

- **x402 per-call** revenue (``payments.jsonl`` + ``settlements.jsonl``,
  via :class:`pry.payments.analytics.PaymentAnalytics`)
- **Pack purchases** (billing ledger ``deposit`` credits with
  ``reference`` prefixed ``pack:`` — see ``billing.packs._settle_pack_purchase``)
- **Subscription revenue** (settled x402/btcpay subscription invoices from
  ``billing.subscription``)
- **Apify actor earnings** (projection-only today — ``actor_factory.economics``
  models revenue/cost/profit per run; there is no runtime earnings ledger yet,
  so this stream reports projections and is always best-effort). [REVIEW]

Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.exc import SQLAlchemyError

from pry.payments.earnings_shared import _ensure_aware

logger = logging.getLogger(__name__)


class StreamMixin:
    """Stream loaders (each returns list of {amount_usd, date, ...})."""

    def _x402_stream(self, days: int) -> list[dict[str, Any]]:
        """Verified x402 per-call payments."""
        out: list[dict[str, Any]] = []
        for p in self.analytics._load_payments(days):
            if not p.get("verified"):
                continue
            out.append(
                {
                    "amount_usd": float(p.get("amount_usd", 0) or 0),
                    "date": str(p.get("verified_at", ""))[:10],
                    "network": str(p.get("network", "unknown")),
                    "asset": str(p.get("asset", "unknown")),
                    "payer": str(p.get("signer", "anonymous")),
                }
            )
        return out

    def _pack_stream(self, days: int) -> list[dict[str, Any]]:
        """Pack purchases from the billing ledger (deposit, reference=pack:*)."""
        cutoff = datetime.now(UTC) - timedelta(days=days)
        out: list[dict[str, Any]] = []
        try:
            from pry.core.db import models as _models
            from pry.core.db.session import get_session

            with get_session() as session:
                rows = (
                    session.query(_models.LedgerEntry)
                    .filter(
                        _models.LedgerEntry.reason == "deposit",
                        _models.LedgerEntry.reference.like("pack:%"),
                        _models.LedgerEntry.created_at >= cutoff,
                    )
                    .order_by(_models.LedgerEntry.created_at.desc())
                    .limit(1000)
                    .all()
                )
                for r in rows:
                    out.append(
                        {
                            "amount_usd": float(r.delta_usd),
                            "date": r.created_at.date().isoformat() if r.created_at else "",
                            "reference": str(r.reference or ""),
                            "payer": str(r.user_id),
                        }
                    )
        except (ImportError, OSError, ValueError, TypeError, SQLAlchemyError) as exc:
            logger.warning("EarningsTracker: pack ledger unavailable: %s", exc)
        return out

    def _subscription_stream(self, days: int) -> list[dict[str, Any]]:
        """Settled subscription invoices from billing.subscription."""
        cutoff = datetime.now(UTC) - timedelta(days=days)
        out: list[dict[str, Any]] = []
        try:
            from pry.commerce.billing import subscription as _sub

            _sub._ensure_loaded()
            with _sub._lock:
                invoices = [dict(inv) for inv in _sub._INVOICES.values()]
            for inv in invoices:
                if str(inv.get("status", "")) != "paid":
                    continue
                # Best-effort settlement date: no explicit settled_at is stored
                # on the invoice today, so fall back to "now" (revenue is
                # counted in the current window). [REVIEW]
                date = str(
                    inv.get("settled_at") or (inv.get("payment") or {}).get("confirmed_at") or ""
                )[:10]
                if not date:
                    date = datetime.now(UTC).date().isoformat()
                try:
                    when = datetime.fromisoformat(date)
                    if _ensure_aware(when) < cutoff:
                        continue
                except ValueError:
                    pass
                out.append(
                    {
                        "amount_usd": float(inv.get("amount_usd", 0) or 0),
                        "date": date,
                        "tier": str(inv.get("tier", "")),
                        "chain": str(inv.get("chain", "unknown")),
                        "payer": str(inv.get("api_key", "")),
                    }
                )
        except (ImportError, OSError, ValueError, TypeError, KeyError) as exc:
            logger.warning("EarningsTracker: subscription stream unavailable: %s", exc)
        return out

    def _actor_stream(self, days: int) -> list[dict[str, Any]]:
        """Apify actor earnings.

        ``actor_factory.economics`` is projection-only today (no runtime
        earnings ledger), so this returns an empty list rather than
        fabricating numbers. The hook exists so a real earnings source can be
        wired in without changing the tracker's API. [REVIEW]
        """
        return []

    def _streams(self, days: int) -> dict[str, list[dict[str, Any]]]:
        return {
            "x402": self._x402_stream(days),
            "packs": self._pack_stream(days),
            "subscriptions": self._subscription_stream(days),
            "apify_actors": self._actor_stream(days),
        }
