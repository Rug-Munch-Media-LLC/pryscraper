"""Pry — x402 usage tracking and subscription management.

Extracted from handler.py for cohesion. Provides:
- UsageTracker: per-token settlement volume, gas cost, response time
- SubscriptionManager: recurring billing with grace period state machine
- fire_settlement_webhook: best-effort settlement webhook delivery
"""

from __future__ import annotations

import os
from typing import Any

__all__ = ["SubscriptionManager", "UsageTracker", "fire_settlement_webhook"]

SETTLEMENT_WEBHOOK_URL_ENV = "PRY_SETTLEMENT_WEBHOOK_URL"


class SubscriptionManager:
    """Recurring subscription management with grace period state machine."""

    def __init__(self) -> None:
        self._subs: dict[str, dict] = {}

    def create(self, sub_id: str, tier: str, monthly_cost: float, payee: str = "") -> dict:
        self._subs[sub_id] = {
            "tier": tier,
            "monthly_cost": monthly_cost,
            "state": "pending",
            "grace_days": 0,
            "paid_until": 0,
            "payee": payee,
        }
        return self._subs[sub_id]

    def activate(self, sub_id: str, days: int = 30) -> dict:
        import time

        sub = self._subs.get(sub_id, {})
        sub["state"] = "active"
        sub["paid_until"] = int(time.time()) + days * 86400
        sub["grace_days"] = 0
        return sub

    def check_grace(self, sub_id: str, grace_period_days: int = 7) -> dict:
        import time

        sub = self._subs.get(sub_id, {})
        if sub.get("state") != "active":
            return sub
        now = int(time.time())
        if now > sub["paid_until"]:
            expired_days = (now - sub["paid_until"]) // 86400
            if expired_days > grace_period_days:
                sub["state"] = "inactive"
            else:
                sub["state"] = "pending"
                sub["grace_days"] = grace_period_days - expired_days
        return sub

    def get(self, sub_id: str) -> dict:
        return self._subs.get(sub_id, {})


async def fire_settlement_webhook(settlement: dict[str, Any]) -> None:
    """Best-effort settlement webhook (audit item #8)."""
    url = os.getenv(SETTLEMENT_WEBHOOK_URL_ENV, "").strip()
    if not url:
        return
    from pry.api.webhook_delivery import WebhookDelivery

    await WebhookDelivery().deliver(url, dict(settlement), "x402.settlement")


class UsageTracker:
    """Per-token usage analytics: settlement volume, gas cost, response time per API key."""

    def __init__(self) -> None:
        self._records: dict[str, dict] = {}

    def record(
        self,
        token: str,
        *,
        amount_usd: float = 0,
        gas_used: int = 0,
        response_ms: int = 0,
        endpoint: str = "",
        network: str = "",
    ) -> None:
        stats = self._records.setdefault(
            token,
            {
                "total_settlement_volume": 0.0,
                "total_gas_cost": 0,
                "total_requests": 0,
                "avg_response_ms": 0,
                "by_endpoint": {},
                "by_network": {},
            },
        )
        stats["total_settlement_volume"] += amount_usd
        stats["total_gas_cost"] += gas_used
        stats["total_requests"] += 1
        stats["avg_response_ms"] = int(
            (stats["avg_response_ms"] * (stats["total_requests"] - 1) + response_ms)
            / stats["total_requests"]
        )
        if endpoint:
            stats["by_endpoint"][endpoint] = stats["by_endpoint"].get(endpoint, 0) + 1
        if network:
            stats["by_network"][network] = stats["by_network"].get(network, 0) + 1

    def get_stats(self, token: str = "") -> dict:
        if token:
            return self._records.get(token, {})
        return dict(self._records)
