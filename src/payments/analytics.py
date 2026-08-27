# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Payment analytics dashboard for Pry.

Tracks revenue, volume, top payers, conversion funnels, and payment method performance.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)


class PaymentAnalytics:
    """Payment analytics engine for tracking revenue and conversion."""

    def __init__(self, payments_file: str = "", settlements_file: str = ""):
        from pry.core.settings import settings

        self.payments_file = payments_file or str(settings.x402_dir / "payments.jsonl")
        self.settlements_file = settlements_file or str(settings.x402_dir / "settlements.jsonl")

    def get_revenue_summary(self, days: int = 30) -> dict[str, Any]:
        """Get revenue summary for the last N days."""
        payments = self._load_payments(days)
        settlements = self._load_settlements(days)

        total_revenue = sum(p.get("amount_usd", 0) for p in payments)
        total_settled = sum(s.get("amount_usd", 0) for s in settlements)
        successful_payments = len([p for p in payments if p.get("verified")])
        failed_payments = len([p for p in payments if not p.get("verified")])

        return {
            "period_days": days,
            "total_revenue_usd": round(total_revenue, 6),
            "total_settled_usd": round(total_settled, 6),
            "pending_settlement_usd": round(total_revenue - total_settled, 6),
            "successful_payments": successful_payments,
            "failed_payments": failed_payments,
            "conversion_rate": round(successful_payments / max(len(payments), 1) * 100, 2),
            "average_payment_usd": round(total_revenue / max(successful_payments, 1), 6),
        }

    def get_top_payers(self, limit: int = 10) -> list[dict[str, Any]]:
        """Get top payers by total spend."""
        payments = self._load_payments(30)
        payer_totals: dict[str, float] = {}
        for p in payments:
            payer = p.get("signer", "anonymous")
            payer_totals[payer] = payer_totals.get(payer, 0) + p.get("amount_usd", 0)

        sorted_payers = sorted(payer_totals.items(), key=lambda x: x[1], reverse=True)
        return [{"payer": p, "total_usd": round(a, 6)} for p, a in sorted_payers[:limit]]

    def get_network_breakdown(self, days: int = 30) -> dict[str, Any]:
        """Get payment breakdown by network."""
        payments = self._load_payments(days)
        network_totals: dict[str, dict[str, Any]] = {}
        for p in payments:
            network = p.get("network", "unknown")
            if network not in network_totals:
                network_totals[network] = {"count": 0, "total_usd": 0.0}
            network_totals[network]["count"] += 1
            network_totals[network]["total_usd"] += p.get("amount_usd", 0)

        return {
            network: {"count": d["count"], "total_usd": round(d["total_usd"], 6)}
            for network, d in network_totals.items()
        }

    def get_asset_breakdown(self, days: int = 30) -> dict[str, Any]:
        """Get payment breakdown by asset."""
        payments = self._load_payments(days)
        asset_totals: dict[str, dict[str, Any]] = {}
        for p in payments:
            asset = p.get("asset", "unknown")
            if asset not in asset_totals:
                asset_totals[asset] = {"count": 0, "total_usd": 0.0}
            asset_totals[asset]["count"] += 1
            asset_totals[asset]["total_usd"] += p.get("amount_usd", 0)

        return {
            asset: {"count": d["count"], "total_usd": round(d["total_usd"], 6)}
            for asset, d in asset_totals.items()
        }

    def get_daily_revenue(self, days: int = 30) -> list[dict[str, Any]]:
        """Get daily revenue for the last N days."""
        payments = self._load_payments(days)
        daily: dict[str, float] = {}
        for p in payments:
            day = p.get("verified_at", "")[:10]  # YYYY-MM-DD
            if day:
                daily[day] = daily.get(day, 0) + p.get("amount_usd", 0)

        return [{"date": d, "revenue_usd": round(a, 6)} for d, a in sorted(daily.items())]

    def get_facilitator_performance(self) -> dict[str, Any]:
        """Get payment facilitator performance."""
        from pry.payments.x402 import get_facilitator_router

        router = get_facilitator_router()
        return router.facilitator_stats()

    def _load_payments(self, days: int) -> list[dict[str, Any]]:
        """Load payments from JSONL file."""
        import json
        import os

        if not os.path.exists(self.payments_file):
            return []

        cutoff = datetime.now(UTC) - timedelta(days=days)
        payments = []
        try:
            with open(self.payments_file) as f:
                for line in f:
                    if line.strip():
                        p = json.loads(line)
                        try:
                            verified_at = datetime.fromisoformat(p.get("verified_at", ""))
                            if verified_at >= cutoff:
                                payments.append(p)
                        except (ValueError, TypeError):
                            continue
        except OSError:
            pass
        return payments

    def _load_settlements(self, days: int) -> list[dict[str, Any]]:
        """Load settlements from JSONL file."""
        import json
        import os

        if not os.path.exists(self.settlements_file):
            return []

        cutoff = datetime.now(UTC) - timedelta(days=days)
        settlements = []
        try:
            with open(self.settlements_file) as f:
                for line in f:
                    if line.strip():
                        s = json.loads(line)
                        try:
                            settled_at = datetime.fromisoformat(s.get("settled_at", ""))
                            if settled_at >= cutoff:
                                settlements.append(s)
                        except (ValueError, TypeError):
                            continue
        except OSError:
            pass
        return settlements


# Global analytics instance
_analytics: PaymentAnalytics | None = None


def get_analytics() -> PaymentAnalytics:
    """Get the global payment analytics instance."""
    global _analytics
    if _analytics is None:
        _analytics = PaymentAnalytics()
    return _analytics
