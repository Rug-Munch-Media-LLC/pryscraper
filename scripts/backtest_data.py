#!/usr/bin/env python3
"""Deterministic data for the strategy backtest.

There is no committed P&L dataset in this repo: the sports modules ship odds
*snapshots* (``datasets/sports_data/data/*.json``) and a paid closing-line
fetcher, but no settled results and no prices at bet time. Rather than invent a
file and call it history, the backtest has two honest inputs:

* :func:`generate_synthetic` — a seeded, fully specified market simulation.
  The market prices with a known margin and noise; outcomes are drawn from the
  true probability. Because the generator is explicit, the *expected* ROI of a
  naive strategy is computable (``-margin``), which makes the harness's output
  falsifiable instead of merely plausible.
* :func:`load_csv` — a real series if one exists (columns are documented in
  ``docs/BACKTESTING.md``).

Both return ``Event`` objects sorted by ``ts``. No network, no clock reads.
"""

from __future__ import annotations

import csv
import hashlib
import math
import random
from typing import TYPE_CHECKING

from backtest_core import Event

if TYPE_CHECKING:
    from pathlib import Path


def _clamp(value: float, lo: float, hi: float) -> float:
    return min(hi, max(lo, value))


def generate_synthetic(n: int = 1500, **options: float) -> list[Event]:
    """Simulate ``n`` settled events with a margin-priced book.

    The book's implied probability is ``true_p * exp(N(0, market_noise))`` and
    the price is ``(1 - margin) / q``, so a bettor who takes every price at the
    model's estimate loses roughly ``margin`` minus whatever skill overcomes
    the noise. ``features[0]`` is a noisy *pre-event* model estimate of
    ``true_p`` — the only thing a signal can legitimately use.

    Deterministic: the same arguments always produce the same series (asserted
    by ``tests/test_backtest_strategy.py``).
    """
    if n < 1:
        raise ValueError("n must be >= 1")
    seed = int(options.get("seed", 7))
    margin = float(options.get("margin", 0.045))
    market_noise = float(options.get("market_noise", 0.08))
    model_noise = float(options.get("model_noise", 0.06))
    spacing_hours = float(options.get("spacing_hours", 12.0))
    rng = random.Random(seed)  # noqa: S311 - deterministic simulation, not crypto
    t0 = 1_700_000_000.0
    out: list[Event] = []
    for i in range(n):
        true_p = _clamp(rng.betavariate(2.2, 2.2), 0.02, 0.98)
        q = _clamp(true_p * math.exp(rng.gauss(0.0, market_noise)), 0.02, 0.98)
        odds = round((1.0 - margin) / q, 4)
        closing = round(odds * math.exp(rng.gauss(0.0, 0.02)), 4)
        model_p = _clamp(true_p + rng.gauss(0.0, model_noise), 0.01, 0.99)
        won = rng.random() < true_p
        out.append(
            Event(
                event_id=f"s{i:05d}",
                ts=t0 + i * spacing_hours * 3600.0,
                odds=max(1.01, odds),
                closing_odds=max(1.01, closing),
                won=won,
                features=(model_p,),
            )
        )
    return out


def data_fingerprint(events: list[Event]) -> str:
    """Short hash of the series, printed with every run so it is reproducible."""
    h = hashlib.sha256()
    for e in events:
        h.update(f"{e.event_id}|{e.ts:.0f}|{e.odds:.4f}|{e.won}\n".encode())
    return h.hexdigest()[:12]


def _ts(raw: str) -> float:
    from datetime import UTC, datetime

    raw = raw.strip()
    try:
        return float(raw)
    except ValueError:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.timestamp()


def _bool(raw: str) -> bool:
    v = raw.strip().lower()
    if v in {"1", "true", "win", "won", "yes"}:
        return True
    if v in {"0", "false", "loss", "lost", "no"}:
        return False
    raise ValueError(f"not a boolean outcome: {raw!r}")


def _row_to_event(row: dict, seen: set[str]) -> Event:
    eid = (row.get("event_id") or "").strip()
    if not eid or eid in seen:
        raise ValueError(f"missing or duplicate event_id: {eid!r}")
    seen.add(eid)
    prob = row.get("prob")
    return Event(
        event_id=eid,
        ts=_ts(row["ts"]),
        odds=float(row["odds"]),
        closing_odds=float(row["closing_odds"]),
        won=_bool(row["won"]),
        features=(float(prob),) if prob not in (None, "") else (),
    )


def load_csv(path: str | Path) -> list[Event]:
    """Load a settled series from CSV.

    Required columns: ``event_id, ts, odds, closing_odds, won``.
    ``ts`` may be epoch seconds or an ISO-8601 timestamp; ``won`` accepts
    ``true/false``, ``1/0``, ``win/loss``. Optional ``prob`` becomes
    ``features[0]``. Rows are sorted by ``ts``; duplicate ids are rejected.
    """
    events: list[Event] = []
    seen: set[str] = set()
    with open(path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            events.append(_row_to_event(row, seen))
    events.sort(key=lambda e: e.ts)
    return events
