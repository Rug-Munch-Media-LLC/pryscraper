#!/usr/bin/env python3
"""Export a settled-outcome series in the walk-forward harness CSV schema.

There is no settled-outcome source in this repository. This is not a guess: the
committed data under ``datasets/sports_data/data/`` is book/sport registries
(``books.json``, ``odds.json``, ``props.json``, ...) with no event records, and
``datasets/sports_data/historical.get_closing_line()`` returns
``{event_id, sport, event, closing, best, source}`` — closing prices only, with
no ``won`` field and no bet-time price column. The word "outcome" in that module
means the *name of an odds side* (home/away), not a settled result.

So this tool never invents an outcome. It has exactly two honest inputs:

* ``--input user.csv`` — a settled series you supply (schema in docs/BACKTESTING.md).
  The file is validated by the same loader the harness uses, filtered by
  ``--since`` / ``--limit``, sorted by ``ts``, and re-emitted canonically.
* ``--input odds.csv|json --outcomes results.csv|json`` — the honest join: odds
  rows carry ``event_id, ts, odds, closing_odds`` (bet-time and closing prices);
  outcomes carry scores (or an explicit ``won``). Every odds row must match one
  settled outcome; **one unmatched row aborts the export** rather than shrinking
  the sample (see ``scripts/backtest_join.py``).
* ``--synthetic`` — the seeded generator, written with a ``source=synthetic``
  label in the fingerprint line so a simulation cannot be mistaken for history.

Without either flag it scans the repo, reports the missing ``won`` column and
exits ``2``. Exit codes match the harness: ``0`` series written, ``2`` unmeasurable.

    python3 scripts/export_backtest_series.py
    python3 scripts/export_backtest_series.py --input settled.csv --since 2026-01-01 --limit 500
    python3 scripts/export_backtest_series.py --synthetic --events 800 --out sim.csv
"""

from __future__ import annotations

import argparse
import csv
import sys
from datetime import UTC, datetime
from pathlib import Path

from backtest_data import Event, data_fingerprint, generate_synthetic, load_csv
from backtest_join import load_series

EXIT_OK = 0
EXIT_UNMEASURABLE = 2

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = REPO_ROOT / "datasets" / "sports_data" / "data"
COLUMNS = ("event_id", "ts", "odds", "closing_odds", "won", "prob")

MISSING = (
    "no settled outcome: in-repo odds data has no 'won' column "
    f"({DATA_DIR.relative_to(REPO_ROOT)}/*.json are book registries, and "
    "historical.get_closing_line() returns closing prices only). "
    "Supply --input <user.csv> or use --synthetic."
)


def _since_ts(raw: str | None) -> float | None:
    """Parse ``--since`` as epoch seconds or ISO-8601 (UTC when naive)."""
    if not raw:
        return None
    text = raw.strip()
    try:
        return float(text)
    except ValueError:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return (dt if dt.tzinfo else dt.replace(tzinfo=UTC)).timestamp()


def select(events: list[Event], since: str | None, limit: int | None) -> list[Event]:
    """Apply the time/row filters, keeping ``ts`` order."""
    cutoff = _since_ts(since)
    picked = [e for e in events if cutoff is None or e.ts >= cutoff]
    picked.sort(key=lambda e: e.ts)
    return picked[:limit] if limit else picked


def write_series(events: list[Event], out: Path) -> str:
    """Write the canonical CSV, returning the data fingerprint."""
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(COLUMNS), extrasaction="ignore")
        writer.writeheader()
        for e in events:
            writer.writerow(
                {
                    "event_id": e.event_id,
                    "ts": f"{e.ts:.0f}",
                    "odds": f"{e.odds:.4f}",
                    "closing_odds": f"{e.closing_odds:.4f}",
                    "won": int(e.won),
                    "prob": f"{e.features[0]:.6f}" if e.features else "",
                }
            )
    return data_fingerprint(events)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--input", help="settled CSV, or odds CSV/JSON when --outcomes is given")
    src.add_argument("--synthetic", action="store_true", help="seeded simulation, labelled")
    ap.add_argument("--outcomes", help="settled results CSV/JSON to join onto --input odds")
    ap.add_argument("--side", default="home", choices=("home", "away"), help="moneyline side to settle")
    ap.add_argument("--out", default="backtest_series.csv", help="output CSV path")
    ap.add_argument("--since", help="keep events at/after this epoch or ISO-8601 time")
    ap.add_argument("--limit", type=int, help="keep at most N events (oldest first)")
    ap.add_argument("--events", type=int, default=1500, help="synthetic event count")
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args(argv)

    if args.outcomes and not args.input:
        print("\n  UNMEASURABLE: --outcomes needs --input <odds.csv|json>")
        return EXIT_UNMEASURABLE
    if not args.input and not args.synthetic:
        print(f"\n  UNMEASURABLE: {MISSING}")
        return EXIT_UNMEASURABLE
    try:
        if args.outcomes:
            events, pushes = load_series(args.input, args.outcomes, side=args.side)
            label = f"join:odds={args.input} outcomes={args.outcomes} side={args.side} pushes={pushes}"
        elif args.input:
            events, label = load_csv(args.input), f"csv:{args.input}"
        else:
            events = generate_synthetic(args.events, seed=args.seed)
            label = f"synthetic:n={args.events} seed={args.seed}"
        picked = select(events, args.since, args.limit)
        if not picked:
            print("\n  UNMEASURABLE: filters selected zero events")
            return EXIT_UNMEASURABLE
        out = Path(args.out)
        fingerprint = write_series(picked, out)
    except (OSError, ValueError, KeyError) as exc:  # JoinError subclasses ValueError
        print(f"\n  UNMEASURABLE: {exc}")
        return EXIT_UNMEASURABLE

    print(f"== series    {out}  events={len(picked)}  source={label}")
    print(f"== fingerprint {fingerprint}")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
