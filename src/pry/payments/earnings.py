"""Pry — unified earnings tracker.

Aggregates ALL revenue streams into one view:

- **x402 per-call** revenue (``payments.jsonl`` + ``settlements.jsonl``,
  via :class:`pry.payments.analytics.PaymentAnalytics`)
- **Pack purchases** (billing ledger ``deposit`` credits with
  ``reference`` prefixed ``pack:`` — see ``billing.packs._settle_pack_purchase``)
- **Subscription revenue** (settled x402/btcpay subscription invoices from
  ``billing.subscription``)
- **Apify actor earnings** (projection-only today — ``actor_factory.economics``
  models revenue/cost/profit per run; there is no runtime earnings ledger yet,
  so this stream reports projections and is always best-effort). [REVIEW]

Also queries the three operator treasuries (EVM / Solana / TRON) for on-chain
balances via free public endpoints. Treasury queries are resilient by design:
10s timeout, 5-minute cache, and every failure degrades to an ``error`` entry —
they can never crash the caller.

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
import os
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy.exc import SQLAlchemyError

from pry.payments.analytics import PaymentAnalytics

logger = logging.getLogger(__name__)

#: Operator treasuries (public receiving addresses — safe to embed).
TREASURY_EVM = "0x1E3AC01d0fdb976179790BDD02823196A92705C9"
TREASURY_SOLANA = "G1uZFfsdxK2PuH2Em5LhRkEcptxHWe4vy5BZak67QyKv"
TREASURY_TRON = "TYSWXWr24QTe3c99V9dtzhe1aZTneE261p"

#: Treasury query tuning.
TREASURY_TIMEOUT_S = 10.0
TREASURY_CACHE_TTL_S = 300.0  # 5 minutes

#: Free public endpoints (no key required except Etherscan, which is optional —
#: when absent we fall back to a public RPC for the native balance).
ETHERSCAN_API = "https://api.etherscan.io/api"
ETHERSCAN_API_KEY_ENV = "ETHERSCAN_API_KEY"
EVM_PUBLIC_RPC = "https://eth.llamarpc.com"
SOLANA_RPC = "https://api.mainnet-beta.solana.com"
TRONGRID_API = "https://api.trongrid.io"

#: USDC contract on Ethereum mainnet (for the Etherscan tokenbalance probe).
USDC_ETHEREUM = "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48"
WEI = 10**18
LAMPORTS = 10**9
#: 6-decimal stablecoin atomic units (USDC).
STABLE_ATOMIC = 10**6

# ── Treasury balance cache (module-level, shared across instances) ──────────
_treasury_cache: dict[str, tuple[float, dict[str, Any]]] = {}


def _cached(key: str) -> dict[str, Any] | None:
    hit = _treasury_cache.get(key)
    if hit and (time.monotonic() - hit[0]) < TREASURY_CACHE_TTL_S:
        return hit[1]
    return None


def _store(key: str, value: dict[str, Any]) -> dict[str, Any]:
    _treasury_cache[key] = (time.monotonic(), value)
    return value


class EarningsTracker:
    """Aggregate earnings across every Pry revenue stream."""

    def __init__(
        self,
        payments_file: str = "",
        settlements_file: str = "",
        analytics: PaymentAnalytics | None = None,
    ):
        self.analytics = analytics or PaymentAnalytics(
            payments_file=payments_file, settlements_file=settlements_file
        )

    # ── Stream loaders (each returns list of {amount_usd, date, ...}) ────────

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

    # ── Public API ───────────────────────────────────────────────────────────

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
        except (ImportError, OSError, ValueError, TypeError, KeyError):
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
            except ValueError:
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

    def get_treasury_balances(self) -> dict[str, Any]:
        """On-chain balances for the three operator treasuries.

        Resilient: 10s timeout, 5-minute cache, per-chain error isolation.
        Never raises.
        """
        return {
            "evm": self._evm_balance(),
            "solana": self._solana_balance(),
            "tron": self._tron_balance(),
            "cached_ttl_s": TREASURY_CACHE_TTL_S,
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

    # ── Internals ────────────────────────────────────────────────────────────

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
                except ValueError:
                    continue
        return total

    # ── Treasury balance probes (each fully isolated) ────────────────────────

    def _evm_balance(self) -> dict[str, Any]:
        cache_key = f"evm:{TREASURY_EVM}"
        if (hit := _cached(cache_key)) is not None:
            return hit
        try:
            api_key = os.getenv(ETHERSCAN_API_KEY_ENV, "")
            native = self._evm_etherscan(api_key) if api_key else self._evm_rpc_native()
            usdc = self._evm_usdc(api_key) if api_key else None
            result: dict[str, Any] = {
                "address": TREASURY_EVM,
                "native_balance": native,
                **({"usdc_balance": usdc} if usdc is not None else {}),
            }
            return _store(cache_key, result)
        except (ImportError, OSError, ValueError, TypeError, KeyError, httpx.HTTPError) as exc:
            return {"address": TREASURY_EVM, "error": str(exc)}

    def _evm_etherscan(self, api_key: str) -> float:
        import httpx

        resp = httpx.get(
            ETHERSCAN_API,
            params={
                "module": "account",
                "action": "balance",
                "address": TREASURY_EVM,
                "tag": "latest",
                "apikey": api_key,
            },
            timeout=TREASURY_TIMEOUT_S,
        )
        resp.raise_for_status()
        data = resp.json()
        if str(data.get("status")) != "1":
            raise ValueError(f"etherscan error: {data.get('result')}")
        return round(int(data["result"]) / WEI, 8)

    def _evm_rpc_native(self) -> float:
        import httpx

        resp = httpx.post(
            EVM_PUBLIC_RPC,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "eth_getBalance",
                "params": [TREASURY_EVM, "latest"],
            },
            timeout=TREASURY_TIMEOUT_S,
        )
        resp.raise_for_status()
        hex_balance = resp.json()["result"]
        return round(int(hex_balance, 16) / WEI, 8)

    def _evm_usdc(self, api_key: str) -> float | None:
        try:
            import httpx

            resp = httpx.get(
                ETHERSCAN_API,
                params={
                    "module": "account",
                    "action": "tokenbalance",
                    "contractaddress": USDC_ETHEREUM,
                    "address": TREASURY_EVM,
                    "tag": "latest",
                    "apikey": api_key,
                },
                timeout=TREASURY_TIMEOUT_S,
            )
            resp.raise_for_status()
            data = resp.json()
            if str(data.get("status")) != "1":
                return None
            return round(int(data["result"]) / STABLE_ATOMIC, 6)
        except (ImportError, OSError, ValueError, TypeError, KeyError, httpx.HTTPError):
            return None

    def _solana_balance(self) -> dict[str, Any]:
        cache_key = f"sol:{TREASURY_SOLANA}"
        if (hit := _cached(cache_key)) is not None:
            return hit
        try:
            import httpx

            resp = httpx.post(
                SOLANA_RPC,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "getBalance",
                    "params": [TREASURY_SOLANA],
                },
                timeout=TREASURY_TIMEOUT_S,
            )
            resp.raise_for_status()
            data = resp.json()
            if "error" in data:
                raise ValueError(f"solana rpc error: {data['error']}")
            lamports = int(data["result"]["value"])
            return _store(
                cache_key,
                {
                    "address": TREASURY_SOLANA,
                    "native_balance": round(lamports / LAMPORTS, 8),
                },
            )
        except (ImportError, OSError, ValueError, TypeError, KeyError, httpx.HTTPError) as exc:
            return {"address": TREASURY_SOLANA, "error": str(exc)}

    def _tron_balance(self) -> dict[str, Any]:
        cache_key = f"trx:{TREASURY_TRON}"
        if (hit := _cached(cache_key)) is not None:
            return hit
        try:
            import httpx

            resp = httpx.get(
                f"{TRONGRID_API}/v1/accounts/{TREASURY_TRON}",
                timeout=TREASURY_TIMEOUT_S,
            )
            resp.raise_for_status()
            data = resp.json()
            accounts = data.get("data") or []
            sun = int(accounts[0].get("balance", 0)) if accounts else 0
            return _store(
                cache_key,
                {
                    "address": TREASURY_TRON,
                    "native_balance": round(sun / 1_000_000, 8),
                },
            )
        except (ImportError, OSError, ValueError, TypeError, KeyError, httpx.HTTPError) as exc:
            return {"address": TREASURY_TRON, "error": str(exc)}


def _ensure_aware(dt: datetime) -> datetime:
    """Normalize a parsed datetime to timezone-aware UTC (naive == UTC)."""
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


def _count_by(items: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        k = str(item.get(key, "unknown"))
        counts[k] = counts.get(k, 0) + 1
    return counts


#: Safe tier price lookup (name -> {"price_usd_monthly": float | None}).
def _tiers_safe() -> dict[str, dict[str, Any]]:
    try:
        from pry.commerce.billing.tiers import TIERS

        return {name: {"price_usd_monthly": tier.price_usd_monthly} for name, tier in TIERS.items()}
    except (ImportError, AttributeError):  # pragma: no cover
        return {}


TIERS_SAFE: dict[str, dict[str, Any]] = _tiers_safe()


# Global tracker instance
_tracker: EarningsTracker | None = None


def get_earnings_tracker() -> EarningsTracker:
    """Get the global earnings tracker instance."""
    global _tracker
    if _tracker is None:
        _tracker = EarningsTracker()
    return _tracker
