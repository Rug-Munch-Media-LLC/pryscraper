"""Payment analytics dashboard for Pry.
Tracks revenue, volume, top payers, conversion funnels, and payment method performance.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pry.payments.earnings import EarningsTracker
logger = logging.getLogger(__name__)

#: Canonical payment timestamp precedence. Rows written by different eras use
#: different keys; reading only one of them silently empties short windows.
TIMESTAMP_KEYS = ("verified_at", "ts", "created_at")

#: Postgres view definition for ledger <-> settlement reconciliation.
#: No migration ships with this change: apply the view manually (or fold it
#: into a later Alembic revision) once the ledger is the only writer.
REVENUE_RECONCILIATION_SQL = """
CREATE OR REPLACE VIEW revenue_reconciliation AS
SELECT
    p.payment_id,
    p.tx_hash,
    p.network,
    p.asset,
    p.amount_usd,
    p.verified,
    COALESCE(p.verified_at, p.created_at) AS booked_at,
    s.settled_at,
    s.amount_usd AS settled_usd,
    CASE
        WHEN p.verified AND s.settled_at IS NOT NULL THEN $$settled$$
        WHEN p.verified THEN $$verified_unsettled$$
        ELSE $$unverified$$
    END AS reconciliation_state
FROM x402_payment_records AS p
LEFT JOIN x402_settlement_records AS s
       ON s.payment_id = p.payment_id
      AND s.tx_hash = p.tx_hash;
"""

#: The three operator queries the reconciliation view exists to answer.
REVENUE_RECONCILIATION_QUERIES = {
    # 1. Verified revenue by day (never trust an unverified row as income).
    "revenue_by_day": """
SELECT date_trunc($$day$$, COALESCE(verified_at, created_at)) AS day,
       COUNT(*) AS payments,
       ROUND(SUM(amount_usd)::numeric, 6) AS revenue_usd
FROM x402_payment_records
WHERE verified
GROUP BY 1
ORDER BY 1 DESC;
""",
    # 2. Verified but unsettled after 24h = money that never moved.
    "verified_but_unsettled": """
SELECT p.payment_id, p.tx_hash, p.amount_usd, p.verified_at
FROM x402_payment_records AS p
LEFT JOIN x402_settlement_records AS s
       ON s.payment_id = p.payment_id
      AND s.tx_hash = p.tx_hash
WHERE p.verified
  AND s.settled_at IS NULL
  AND COALESCE(p.verified_at, p.created_at) < now() - interval $$24 hours$$
ORDER BY p.verified_at NULLS LAST;
""",
    # 3. Payment amount vs settled amount drift (should be exact).
    "amount_mismatches": """
SELECT p.payment_id, p.tx_hash, p.amount_usd, s.amount_usd AS settled_usd
FROM x402_payment_records AS p
JOIN x402_settlement_records AS s
  ON s.payment_id = p.payment_id
 AND s.tx_hash = p.tx_hash
WHERE p.verified
  AND ABS(COALESCE(p.amount_usd, 0) - COALESCE(s.amount_usd, 0)) > 0.000001;
""",
}


def parse_payment_ts(value: Any) -> datetime | None:
    """Parse a timestamp to an aware UTC datetime; naive values are UTC."""
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def payment_ts(record: dict[str, Any]) -> datetime | None:
    """Canonical payment time: verified_at -> ts -> created_at (aware UTC)."""
    for key in TIMESTAMP_KEYS:
        parsed = parse_payment_ts(record.get(key))
        if parsed is not None:
            return parsed
    return None


def _amount_usd(record: dict[str, Any]) -> float:
    """Coerce a row amount to float; corrupt rows count as 0, never raise."""
    try:
        return float(record.get("amount_usd", 0) or 0)
    except (TypeError, ValueError):
        return 0.0


def _payment_identity(record: dict[str, Any]) -> tuple[str, str] | None:
    tx_hash = str(record.get("tx_hash") or "")
    if tx_hash:
        return ("tx", tx_hash)
    payment_id = str(record.get("payment_id") or "")
    if payment_id:
        return ("pid", payment_id)
    return None


def dedupe_payment_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop duplicate rows, keeping the first (ledger-first) occurrence."""
    seen: set[tuple[str, str]] = set()
    unique: list[dict[str, Any]] = []
    for record in records:
        identity = _payment_identity(record)
        if identity is not None:
            if identity in seen:
                continue
            seen.add(identity)
        unique.append(record)
    return unique


def _load_jsonl_records(path: str) -> list[dict[str, Any]]:
    import json
    import os

    if not path or not os.path.exists(path):
        return []
    records: list[dict[str, Any]] = []
    try:
        with open(path) as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(row, dict):
                    records.append(row)
    except OSError as exc:
        logger.warning("analytics_load_failed", extra={"error": str(exc)[:160]})
    return records


def load_payment_records(fallback_path: str = "") -> list[dict[str, Any]]:
    """Load payments with Postgres as the source of truth.

    x402_payment_records is authoritative; the JSONL log is the fallback.
    Ledger rows come first so they win on identity, but JSONL rows the ledger
    has not ingested yet are appended so history is never silently dropped.
    Deduped by tx_hash, then payment_id.
    """
    records: list[dict[str, Any]] = []
    try:
        from pry.payments.x402 import ledger_store

        if ledger_store.available():
            records.extend(ledger_store.get_payments())
    except Exception as exc:  # noqa: BLE001 - any ledger failure degrades to JSONL
        logger.warning("payment_ledger_unavailable", extra={"error": str(exc)[:160]})
    records.extend(_load_jsonl_records(fallback_path))
    return dedupe_payment_records(records)


class PaymentAnalytics:
    """Payment analytics engine for tracking revenue and conversion."""

    def __init__(self, payments_file: str = "", settlements_file: str = ""):
        from pry.core.paths import PRY_DATA_DIR

        x402_dir = PRY_DATA_DIR / "x402"
        self.payments_file = payments_file or str(x402_dir / "payments.jsonl")
        self.settlements_file = settlements_file or str(x402_dir / "settlements.jsonl")

    def get_revenue_summary(self, days: int = 30) -> dict[str, Any]:
        """Get revenue summary for the last N days."""
        payments = self._load_payments(days)
        settlements = self._load_settlements(days)

        verified = [p for p in payments if p.get("verified")]
        total_revenue = sum(_amount_usd(p) for p in verified)
        total_settled = sum(_amount_usd(s) for s in settlements)
        successful_payments = len(verified)
        failed_payments = len(payments) - successful_payments

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
            if not p.get("verified"):
                continue
            payer = p.get("signer", "anonymous")
            payer_totals[payer] = payer_totals.get(payer, 0) + _amount_usd(p)
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
            if not p.get("verified"):
                continue
            parsed = payment_ts(p)
            if parsed is None:
                continue
            day = parsed.date().isoformat()
            daily[day] = daily.get(day, 0) + _amount_usd(p)

        return [{"date": d, "revenue_usd": round(a, 6)} for d, a in sorted(daily.items())]

    def get_facilitator_performance(self) -> dict[str, Any]:
        """Get payment facilitator performance."""
        from pry.payments.x402 import get_facilitator_router

        router = get_facilitator_router()
        return router.facilitator_stats()

    def get_total_earnings(self, days: int = 30) -> dict[str, Any]:
        """Total earnings across ALL streams (x402, packs, subscriptions, actors)."""
        return self._tracker().get_total_earnings(days)

    def get_daily_earnings(self, days: int = 30) -> list[dict[str, Any]]:
        """Per-day earnings across ALL streams, broken down by stream."""
        return self._tracker().get_daily_earnings(days)

    def get_revenue_by_stream(self, days: int = 30) -> dict[str, Any]:
        """Revenue split by stream."""
        return self._tracker().get_revenue_by_stream(days)

    def get_revenue_by_chain(self, days: int = 30) -> dict[str, Any]:
        """Revenue split by settlement chain."""
        return self._tracker().get_revenue_by_chain(days)

    def get_mrr(self) -> dict[str, Any]:
        """Monthly recurring revenue from active paid subscriptions."""
        return self._tracker().get_mrr()

    def get_growth_rate(self, days: int = 30) -> dict[str, Any]:
        """Earnings growth vs the preceding window."""
        return self._tracker().get_growth_rate(days)

    def get_treasury_balances(self) -> dict[str, Any]:
        """On-chain operator treasury balances (cached, never raises)."""
        return self._tracker().get_treasury_balances()

    def export_earnings_csv(self, days: int = 30) -> str:
        """Export daily earnings across all streams as CSV."""
        return self._tracker().export_csv(days)

    def _tracker(self) -> EarningsTracker:
        """Lazy EarningsTracker bound to this instance's payment files."""
        from pry.payments.earnings import EarningsTracker

        return EarningsTracker(analytics=self)

    def _load_payments(self, days: int) -> list[dict[str, Any]]:
        """Load payments in the window from the ledger or the JSONL fallback.

        x402_payment_records is the declared source of truth; JSONL is a
        compatibility fallback. The window uses the canonical timestamp helper
        (verified_at -> ts -> created_at) so short windows are not empty.
        """
        cutoff = datetime.now(UTC) - timedelta(days=days)
        return [
            record
            for record in load_payment_records(self.payments_file)
            if (timestamp := payment_ts(record)) is not None and timestamp >= cutoff
        ]

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
                        except (ValueError, TypeError) as exc:
                            logger.warning(
                                "payments_exception_swallowed",
                                extra={
                                    "error": str(exc),
                                    "handler": "PaymentAnalytics._load_settlements",
                                },
                            )
                            continue
        except OSError as e:
            logger.warning("analytics_load_failed", extra={"error": str(e)[:160]})
        return settlements


_analytics: PaymentAnalytics | None = None


def get_analytics() -> PaymentAnalytics:
    """Get the global payment analytics instance."""
    global _analytics
    if _analytics is None:
        _analytics = PaymentAnalytics()
    return _analytics
