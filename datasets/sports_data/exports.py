"""Model-ready dataset exports + a minimal CLV backtest harness.

Two things serious bettors need that the raw odds feed does not give them:

* :func:`export_dataset` — flattens the canonical odds records into a
  model-ready table of odds **plus** derived features (implied probabilities,
  no-vig fair probabilities, per-side EV, and CLV when closing odds are
  available) so downstream pipelines can backtest or train without touching
  the network. CSV and JSON use only the standard library; Parquet uses
  ``pyarrow`` when installed and degrades honestly to JSON when it is not
  (flagged via ``degraded_from``).
* :func:`backtest` — a deliberately minimal CLV backtest harness: for the
  ``"closing_line"`` strategy, bet when the price beats the closing line by
  at least ``threshold_pct``, then report bets / win rate / ROI / EV. It
  evaluates caller-supplied records (see the contract) so it is testable and
  works offline; with no records it attempts a live feed and reports zero
  bets (closing odds are not part of the live feed).

Contract
--------
* :func:`export_dataset` — async, never raises, returns a ``dict``.
* :func:`backtest` — async, never raises, returns a ``dict``.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import csv
import io
import json
import logging
import os
import tempfile
from typing import Any

logger = logging.getLogger(__name__)

# Guarded imports: sports_data.odds is owned by a parallel agent and may not
# exist yet when this module is first imported; ev is stable.
try:
    from datasets.sports_data.odds import get_odds as _get_odds
except ImportError:  # pragma: no cover - parallel build guard
    _get_odds = None  # type: ignore[assignment]

try:
    from datasets.sports_data.ev import compute_no_vig as _compute_no_vig
except ImportError:  # pragma: no cover - parallel build guard
    _compute_no_vig = None  # type: ignore[assignment]

# pyarrow is optional; absent => parquet degrades to JSON.
try:
    import pyarrow as pa
    import pyarrow.parquet as pq
except ImportError:  # pragma: no cover - environment dependent
    pa = None
    pq = None

# Maximum records requested from sports_data.odds.get_odds per export.
_EXPORT_LIMIT = 100

# Fixed column order for CSV/JSON/parquet exports. ``closing_*`` columns are
# populated when the source record carries closing odds (e.g. injected by a
# test or an enriched pipeline); otherwise they are None.
_EXPORT_COLUMNS: list[str] = [
    "sport",
    "event",
    "event_id",
    "market",
    "book",
    "bookmaker",
    "home",
    "away",
    "home_odds",
    "away_odds",
    "draw_odds",
    "spread",
    "total",
    "implied_home",
    "implied_away",
    "fair_home_prob",
    "fair_away_prob",
    "ev_home_pct",
    "ev_away_pct",
    "clv_home_pct",
    "clv_away_pct",
    "last_update",
    "source",
]

_SUPPORTED_FORMATS = {"csv", "json", "parquet"}


def _as_float(value: Any) -> float | None:
    """Coerce to a positive decimal price / probability (garbage -> None)."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _derive_row(record: dict[str, Any]) -> dict[str, Any]:
    """Enrich one canonical odds record with model-ready derived features."""
    row: dict[str, Any] = dict.fromkeys(_EXPORT_COLUMNS)
    for column in _EXPORT_COLUMNS:
        if column in record:
            row[column] = record[column]
    home_odds = _as_float(record.get("home_odds"))
    away_odds = _as_float(record.get("away_odds"))
    if home_odds is not None and home_odds > 1.0:
        row["implied_home"] = round(1.0 / home_odds, 6)
    if away_odds is not None and away_odds > 1.0:
        row["implied_away"] = round(1.0 / away_odds, 6)
    if _compute_no_vig is not None and home_odds and away_odds:
        fair = _compute_no_vig(home_odds, away_odds)
        if fair.get("home_prob") is not None:
            row["fair_home_prob"] = fair["home_prob"]
            row["fair_away_prob"] = fair["away_prob"]
            row["ev_home_pct"] = round((float(fair["home_prob"]) * home_odds - 1.0) * 100.0, 2)
            row["ev_away_pct"] = round((float(fair["away_prob"]) * away_odds - 1.0) * 100.0, 2)
    closing_home = _as_float(record.get("closing_home_odds"))
    closing_away = _as_float(record.get("closing_away_odds"))
    if home_odds is not None and closing_home is not None and closing_home > 1.0:
        row["clv_home_pct"] = round((home_odds / closing_home - 1.0) * 100.0, 2)
    if away_odds is not None and closing_away is not None and closing_away > 1.0:
        row["clv_away_pct"] = round((away_odds / closing_away - 1.0) * 100.0, 2)
    return row


def _rows_to_csv(rows: list[dict[str, Any]]) -> str:
    """Serialize derived rows to a CSV string (stdlib only)."""
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=_EXPORT_COLUMNS, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return buffer.getvalue()


def _rows_to_json(rows: list[dict[str, Any]]) -> str:
    """Serialize derived rows to a JSON string (stdlib only)."""
    return json.dumps(rows, ensure_ascii=False, default=str)


def _rows_to_parquet(rows: list[dict[str, Any]]) -> str:
    """Write derived rows to a temporary .parquet file (pyarrow required).

    Raises:
        LookupError: When pyarrow is not installed — callers degrade.
    """
    if pa is None or pq is None:
        raise LookupError("pyarrow is not installed; parquet export unavailable")
    table = pa.Table.from_pylist(rows)
    fd, path = tempfile.mkstemp(suffix=".parquet", prefix="pry_export_")
    os.close(fd)
    pq.write_table(table, path)
    return path


async def export_dataset(
    sport: str,
    market: str = "h2h",
    format: str = "csv",
) -> dict[str, Any]:
    """Export odds + derived features as a model-ready dataset.

    Args:
        sport: Sport key as accepted by :func:`sports_data.odds.get_odds`
            (e.g. ``"nba"``, ``"basketball_nba"``).
        market: Market to export — ``"h2h"`` (default), ``"spreads"``,
            ``"totals"``, or a combo.
        format: ``"csv"`` (default), ``"json"``, or ``"parquet"``.

    Returns:
        ``{format, rows, columns, payload_or_path, ...}``. For CSV/JSON,
        ``payload_or_path`` is the serialized string. For parquet it is the
        path of a temporary file (``temporary_file: True``). When pyarrow is
        missing, parquet degrades to JSON with ``degraded_from: "parquet"``.
        Never raises — failures return ``rows: 0`` with an ``error`` note.
    """
    requested = str(format or "").strip().lower()
    if requested not in _SUPPORTED_FORMATS:
        return {
            "format": requested or "csv",
            "rows": 0,
            "columns": [],
            "payload_or_path": None,
            "error": f"unsupported format {requested!r}; use csv, json or parquet",
        }
    try:
        if _get_odds is None:
            records = []
        else:
            records = await _get_odds(sport=sport, limit=_EXPORT_LIMIT, market=market)
    except Exception:
        logger.exception("sports_export_odds_failed", extra={"sport": sport, "market": market})
        records = []
    if not isinstance(records, list) or not records:
        return {
            "format": requested,
            "rows": 0,
            "columns": _EXPORT_COLUMNS,
            "payload_or_path": None,
            "error": "no odds records available",
        }
    rows = [_derive_row(record) for record in records if isinstance(record, dict)]
    if requested == "csv":
        return {
            "format": "csv",
            "rows": len(rows),
            "columns": _EXPORT_COLUMNS,
            "payload_or_path": _rows_to_csv(rows),
        }
    if requested == "json":
        return {
            "format": "json",
            "rows": len(rows),
            "columns": _EXPORT_COLUMNS,
            "payload_or_path": _rows_to_json(rows),
        }
    # parquet
    try:
        path = _rows_to_parquet(rows)
    except LookupError:
        payload = _rows_to_json(rows)
        return {
            "format": "json",
            "rows": len(rows),
            "columns": _EXPORT_COLUMNS,
            "payload_or_path": payload,
            "degraded_from": "parquet",
            "note": "pyarrow unavailable; fell back to JSON (see [REVIEW])",
        }
    except Exception:
        logger.exception("sports_export_parquet_failed", extra={"sport": sport})
        return {
            "format": "parquet",
            "rows": 0,
            "columns": _EXPORT_COLUMNS,
            "payload_or_path": None,
            "error": "parquet serialization failed",
        }
    return {
        "format": "parquet",
        "rows": len(rows),
        "columns": _EXPORT_COLUMNS,
        "payload_or_path": path,
        "temporary_file": True,
    }


# ── Backtest harness ────────────────────────────────────────────────────


def _bet_profit(bet_odds: float, result: Any) -> float | None:
    """Unit-stake profit for a settled bet (None when unsettled)."""
    if result is None:
        return None
    try:
        outcome = float(result)
    except (TypeError, ValueError):
        return None
    if outcome >= 0.5:  # win (also accepts bool True / 1)
        return bet_odds - 1.0
    return -1.0


async def backtest(
    sport: str,
    strategy: str = "closing_line",
    *,
    threshold_pct: float = 5.0,
    records: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Run a minimal CLV backtest over bet records.

    Args:
        sport: Sport key (reported back; used only for the live-odds fallback).
        strategy: ``"closing_line"`` (default) — bet when the price beats the
            closing line by at least ``threshold_pct`` percent.
        threshold_pct: Minimum CLV (percent) required to enter a bet.
        records: Optional list of bet dicts::

                {
                    "bet_odds": 2.10,          # decimal price taken
                    "closing_odds": 2.00,      # closing price for same side
                    "result": 1.0,             # 1.0/True = win, 0.0 = loss, None = unsettled
                }

            When omitted, a live odds feed is attempted and zero bets are
            reported (the live feed has no closing odds).

    Returns:
        ``{strategy, sport, threshold_pct, bets, win_rate, roi_pct,
        ev_per_bet, ...}``. ``win_rate`` is a 0-1 fraction over settled bets;
        ``roi_pct`` is per-bet return on a unit stake; ``ev_per_bet`` is the
        mean theoretical edge ``(bet_odds / closing_odds - 1)`` over entered
        bets. Never raises — unsupported strategies degrade to zeroed results
        with an ``error`` note.
    """
    strategy_key = str(strategy or "").strip().lower()
    try:
        threshold = max(0.0, float(threshold_pct))
    except (TypeError, ValueError):
        threshold = 5.0
    if strategy_key != "closing_line":
        return {
            "strategy": strategy_key,
            "sport": str(sport or ""),
            "threshold_pct": threshold,
            "bets": 0,
            "win_rate": None,
            "roi_pct": None,
            "ev_per_bet": None,
            "error": f"unsupported strategy {strategy_key!r}; use 'closing_line'",
        }
    bets: list[dict[str, Any]] = []
    records_provided = records is not None
    if records is None:
        try:
            if _get_odds is None:
                live = []
            else:
                live = await _get_odds(sport=sport, limit=_EXPORT_LIMIT, market="h2h")
        except Exception:
            logger.exception("sports_backtest_odds_failed", extra={"sport": sport})
            live = []
        records = [{"bet_odds": rec.get("home_odds")} for rec in live if isinstance(rec, dict)]
    for record in records or []:
        if not isinstance(record, dict):
            continue
        bet_odds = _as_float(record.get("bet_odds"))
        closing_odds = _as_float(record.get("closing_odds"))
        if bet_odds is None or bet_odds <= 1.0 or closing_odds is None or closing_odds <= 1.0:
            continue
        clv_pct = (bet_odds / closing_odds - 1.0) * 100.0
        if clv_pct < threshold:
            continue
        bets.append(
            {
                "bet_odds": bet_odds,
                "closing_odds": closing_odds,
                "clv_pct": round(clv_pct, 4),
                "result": record.get("result"),
            }
        )
    settled: list[dict[str, Any]] = []
    for bet in bets:
        profit = _bet_profit(float(bet["bet_odds"]), bet.get("result"))
        if profit is None:
            continue
        bet["profit"] = profit
        settled.append(bet)
    wins = sum(1 for bet in settled if float(bet.get("profit") or 0.0) > 0.0)
    total_profit = sum(float(bet.get("profit") or 0.0) for bet in settled)
    edge_values = [(float(bet["bet_odds"]) / float(bet["closing_odds"]) - 1.0) for bet in bets]
    return {
        "strategy": strategy_key,
        "sport": str(sport or ""),
        "threshold_pct": threshold,
        "bets": len(bets),
        "win_rate": round(wins / len(settled), 4) if settled else None,
        "roi_pct": round(total_profit / len(settled) * 100.0, 4) if settled else None,
        "ev_per_bet": round(sum(edge_values) / len(edge_values), 6) if edge_values else None,
        "settled": len(settled),
        "wins": wins,
        "source": "synthetic" if records_provided else "live",
    }
