"""Pry — earnings computation.

Public earnings computations for :class:`pry.payments.earnings.EarningsTracker`:
totals, daily breakdowns, per-stream/per-chain splits, MRR, growth rate, CSV
export, and the previous-window comparison.

Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import csv
import io
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from pry.payments.earnings_shared import TIERS_SAFE, _count_by, _ensure_aware

logger = logging.getLogger(__name__)


class ComputeMixin:
    """Public earnings computations (totals, daily, MRR, growth, export)."""

    def get_total_earnings(self, days: int = 30) -> dict[str, Any]:
        """Total earnings across all streams for the last N days."""
        streams = self._streams(days)
        by_stream = {
            name: round(sum(e["amount_usd"] for e in entries), 6)
            for name, entries in streams.items()
        }
        return {
            "period_days": days,
            "total_usd": round(sum(by_stream.values()), 6),
            "by_stream": by_stream,
            "counts": {name: len(entries) for name, entries in streams.items()},
        }

    def get_daily_earnings(self, days: int = 30) -> list[dict[str, Any]]:
        """Per-day earnings broken down by stream, sorted by date."""
        streams = self._streams(days)
        daily: dict[str, dict[str, float]] = {}
        for name, entries in streams.items():
            for e in entries:
                day = e.get("date", "")
                if not day:
                    continue
                row = daily.setdefault(day, {})
                row[name] = row.get(name, 0.0) + e["amount_usd"]
        out = []
        for day in sorted(daily):
            row = daily[day]
            out.append(
                {
                    "date": day,
                    **{k: round(v, 6) for k, v in row.items()},
                    "total_usd": round(sum(row.values()), 6),
                }
            )
        return out

    def get_revenue_by_stream(self, days: int = 30) -> dict[str, Any]:
        """Revenue split by stream (x402 / packs / subscriptions / actors)."""
        by_stream: dict[str, Any] = self.get_total_earnings(days)["by_stream"]
        return by_stream

    def get_revenue_by_chain(self, days: int = 30) -> dict[str, Any]:
        """Revenue split by settlement chain (x402 payments + subscription invoices)."""
        chains: dict[str, dict[str, Any]] = {}
        for e in self._x402_stream(days):
            chain = str(e.get("network", "unknown"))
            d = chains.setdefault(chain, {"count": 0, "total_usd": 0.0})
            d["count"] += 1
            d["total_usd"] += e["amount_usd"]
        for e in self._subscription_stream(days):
            chain = str(e.get("chain", "unknown")) or "unknown"
            d = chains.setdefault(chain, {"count": 0, "total_usd": 0.0})
            d["count"] += 1
            d["total_usd"] += e["amount_usd"]
        return {
            chain: {"count": d["count"], "total_usd": round(d["total_usd"], 6)}
            for chain, d in sorted(chains.items())
        }

    def get_mrr(self) -> dict[str, Any]:
        """Monthly recurring revenue from active paid subscriptions."""
        try:
            from pry.commerce.billing import subscription as _sub

            _sub._ensure_loaded()
            with _sub._lock:
                subs = [dict(s) for s in _sub._SUBSCRIPTIONS.values()]
        except (ImportError, OSError, ValueError, TypeError, KeyError) as exc:
            logger.warning(
                "payments_exception_swallowed",
                extra={"error": str(exc), "handler": "ComputeMixin.get_mrr"},
            )
            subs = []

        now = datetime.now(UTC)
        active: list[dict[str, Any]] = []
        mrr = 0.0
        for s in subs:
            tier_name = str(s.get("tier", "free"))
            tier = TIERS_SAFE.get(tier_name)
            if tier is None or tier["price_usd_monthly"] is None:
                continue
            try:
                expires = datetime.fromisoformat(str(s.get("expires_at", "")))
            except ValueError as exc:
                logger.warning(
                    "payments_exception_swallowed",
                    extra={"error": str(exc), "handler": "ComputeMixin.get_mrr"},
                )
                continue
            if expires <= now:
                continue
            active.append({"tier": tier_name, "expires_at": s.get("expires_at")})
            mrr += float(tier["price_usd_monthly"])
        return {
            "mrr_usd": round(mrr, 2),
            "arr_usd": round(mrr * 12, 2),
            "active_subscriptions": len(active),
            "by_tier": _count_by(active, "tier"),
        }

    def get_growth_rate(self, days: int = 30) -> dict[str, Any]:
        """Earnings growth: current window vs the immediately preceding window."""
        current = self.get_total_earnings(days)["total_usd"]
        previous = self._previous_window_total(days)
        if previous <= 0:
            rate = None if current <= 0 else 100.0
        else:
            rate = round((current - previous) / previous * 100, 2)
        return {
            "period_days": days,
            "current_usd": round(current, 6),
            "previous_usd": round(previous, 6),
            "growth_rate_pct": rate,
        }

    def export_csv(self, days: int = 30) -> str:
        """Export daily earnings as CSV text."""
        rows = self.get_daily_earnings(days)
        stream_names = ["x402", "packs", "subscriptions", "apify_actors"]
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["date", *stream_names, "total_usd"])
        for row in rows:
            writer.writerow(
                [
                    row.get("date", ""),
                    *[row.get(s, 0.0) for s in stream_names],
                    row.get("total_usd", 0.0),
                ]
            )
        return buf.getvalue()

    def _previous_window_total(self, days: int) -> float:
        """Total earnings for the window immediately before the current one."""
        cutoff_start = datetime.now(UTC) - timedelta(days=days * 2)
        cutoff_end = datetime.now(UTC) - timedelta(days=days)
        total = 0.0
        for entries in self._streams(days * 2).values():
            for e in entries:
                try:
                    when = datetime.fromisoformat(e.get("date", ""))
                    if cutoff_start <= _ensure_aware(when) < cutoff_end:
                        total += e["amount_usd"]
                except ValueError as exc:
                    logger.warning(
                        "payments_exception_swallowed",
                        extra={"error": str(exc), "handler": "ComputeMixin._previous_window_total"},
                    )
                    continue
        return total
