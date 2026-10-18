#!/usr/bin/env python3
"""Pull one ESPN window into the two files the honest join needs.

Builds ``odds.csv`` (bet-time open, closing line) and ``outcomes.json`` (final
scores) for every completed game in the requested days, using the keyless ESPN
endpoints in :mod:`datasets.sports_data.results`. Then run::

    python3 scripts/export_backtest_series.py \\
        --input /tmp/espn/odds.csv --outcomes /tmp/espn/outcomes.json \\
        --side home --out /tmp/espn/series.csv
    python3 scripts/backtest_strategy.py --csv /tmp/espn/series.csv --signal market \\
        --train 20 --test 10

A game with no fetched moneyline is reported and omitted from *both* files, so
the join never sees an odds row it cannot settle.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

from backtest_join import results_module

ODDS_COLUMNS = ("event_id", "ts", "odds", "closing_odds", "side", "date", "home", "away")


def _days(raw: list[str]) -> list[str]:
    """Expand ``YYYYMMDD`` / ``YYYY-MM-DD`` values; ranges use ``A..B`` on 8-char days."""
    out: list[str] = []
    for item in raw:
        text = item.replace("-", "")
        if ".." in text:
            first, last = text.split("..", 1)
            start = f"{first[:4]}-{first[4:6]}-{first[6:]}"
            end = f"{last[:4]}-{last[4:6]}-{last[6:]}"
            a, b = date.fromisoformat(start), date.fromisoformat(end)
            while a <= b:
                out.append(a.strftime("%Y%m%d"))
                a += timedelta(days=1)
        else:
            out.append(text)
    return out


def build(
    sport: str, league: str, days: list[str], side: str
) -> tuple[list[dict], list[dict], list[str]]:
    """Return ``(odds_rows, outcome_rows, skipped)`` for completed games only."""
    mod = results_module()
    odds_rows: list[dict] = []
    outcome_rows: list[dict] = []
    skipped: list[str] = []
    for day in days:
        for game in mod.fetch_results(sport, league, day):
            ml = mod.fetch_moneyline(sport, league, game["event_id"], game["competition_id"], side)
            if not ml:
                skipped.append(f"{game['event_id']} {game['date']} (no moneyline)")
                continue
            odds_rows.append(
                {
                    "event_id": game["event_id"],
                    "ts": game["date"],
                    "odds": f"{ml['odds']:.4f}",
                    "closing_odds": f"{ml['closing_odds']:.4f}",
                    "side": side,
                    "date": game["date"],
                    "home": game["home"],
                    "away": game["away"],
                }
            )
            outcome_rows.append(
                {
                    "event_id": game["event_id"],
                    "date": game["date"],
                    "home": game["home"],
                    "away": game["away"],
                    "home_score": game["home_score"],
                    "away_score": game["away_score"],
                }
            )
    return odds_rows, outcome_rows, skipped


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--sport", default="basketball")
    ap.add_argument("--league", default="nba")
    ap.add_argument("--dates", nargs="+", required=True, help="YYYYMMDD or A..B range")
    ap.add_argument("--side", default="home", choices=("home", "away"))
    ap.add_argument("--out-dir", default="", help="output dir (default: system temp)")
    args = ap.parse_args(argv)

    out = Path(args.out_dir or Path(tempfile.gettempdir()) / "espn-window")
    out.mkdir(parents=True, exist_ok=True)
    try:
        odds_rows, outcome_rows, skipped = build(
            args.sport, args.league, _days(args.dates), args.side
        )
    except (OSError, ValueError) as exc:
        print(f"\n  UNMEASURABLE: ESPN pull failed: {exc}")
        raise SystemExit(2) from exc
    if not odds_rows:
        print("\n  UNMEASURABLE: no completed game with a moneyline in this window")
        for item in skipped[:5]:
            print(f"    skipped {item}")
        return 2
    with (out / "odds.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(ODDS_COLUMNS))
        writer.writeheader()
        writer.writerows(odds_rows)
    (out / "outcomes.json").write_text(json.dumps(outcome_rows, indent=1), encoding="utf-8")
    print(f"== window    {args.sport}/{args.league} side={args.side} days={len(_days(args.dates))}")
    print(f"== odds      {out / 'odds.csv'}  games={len(odds_rows)}")
    print(f"== outcomes  {out / 'outcomes.json'}  games={len(outcome_rows)}")
    for item in skipped:
        print(f"   skipped {item}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
