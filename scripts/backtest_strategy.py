#!/usr/bin/env python3
"""Walk-forward backtest CLI — honest by construction.

    python3 scripts/backtest_strategy.py                      # synthetic, seeded
    python3 scripts/backtest_strategy.py --signal model --sizing kelly
    python3 scripts/backtest_strategy.py --csv series.csv --train 300 --test 100
    python3 scripts/backtest_strategy.py --signal lookahead    # canary: must fail

Exit codes, matching the ladder harness's contract:

    0  measured, no lookahead flags      → the numbers may be quoted
    1  measured AND flagged (or the signal was caught reading the future)
    2  could not measure at all          → no verdict; do not report a number

The signal never receives an outcome or a closing line (``backtest_core``
raises ``LookaheadError`` if it tries), the training window is purged, an
embargo separates it from the test window, and both costs default non-zero.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from typing import TYPE_CHECKING

from backtest_core import (
    Costs,
    LookaheadError,
    MarketView,
    Sizing,
    lookahead_flags,
    summarise,
    walk_forward,
)
from backtest_data import data_fingerprint, generate_synthetic, load_csv

if TYPE_CHECKING:
    from collections.abc import Sequence

EXIT_OK = 0
EXIT_UNTRUSTWORTHY = 1
EXIT_UNMEASURABLE = 2


def market_signal(_history: Sequence[MarketView], v: MarketView) -> float:
    """The book's own probability. No edge by construction — the baseline."""
    return 1.0 / v.odds


def model_signal(_history: Sequence[MarketView], v: MarketView) -> float | None:
    """A pre-event model estimate carried in ``features[0]``."""
    return v.features[0] if v.features else None


def momentum_signal(history: Sequence[MarketView], v: MarketView) -> float | None:
    """Trailing mean implied probability over the last 50 events (clean, weak)."""
    window = history[-50:]
    if len(window) < 10:
        return None
    return statistics.fmean(1.0 / e.odds for e in window)


def lookahead_signal(_history: Sequence[MarketView], v: MarketView) -> float:
    """CANARY. Reads the outcome — must raise ``LookaheadError``, never score."""
    return 0.99 if v.won else 0.01


SIGNALS = {
    "market": market_signal,
    "model": model_signal,
    "momentum": momentum_signal,
    "lookahead": lookahead_signal,
}


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--synthetic", action="store_true", help="seeded simulation (default)")
    src.add_argument("--csv", help="settled series (see docs/BACKTESTING.md)")
    ap.add_argument("--events", type=int, default=1500, help="synthetic event count")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--margin", type=float, default=0.045, help="synthetic book margin")
    ap.add_argument("--signal", choices=sorted(SIGNALS), default="model")
    ap.add_argument("--train", type=int, default=400)
    ap.add_argument("--test", type=int, default=200)
    ap.add_argument("--embargo", type=int, default=10, help="events skipped between windows")
    ap.add_argument("--purge", type=int, default=5, help="events dropped from the train tail")
    ap.add_argument("--commission", type=float, default=0.02, help="fraction of winnings")
    ap.add_argument("--slippage-bps", type=float, default=25.0)
    ap.add_argument("--sizing", choices=("flat", "kelly"), default="flat")
    ap.add_argument("--flat-pct", type=float, default=0.01)
    ap.add_argument("--kelly-pct", type=float, default=0.25)
    ap.add_argument("--max-stake-pct", type=float, default=0.02)
    ap.add_argument(
        "--min-edge",
        type=float,
        default=0.0,
        help="minimum prob*net_odds-1 to bet (default 0.0; negative bets blindly)",
    )
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    return ap.parse_args(argv)


def _load(args: argparse.Namespace):
    if args.csv:
        return load_csv(args.csv), f"csv:{args.csv}"
    return (
        generate_synthetic(args.events, seed=args.seed, margin=args.margin),
        f"synthetic:n={args.events} seed={args.seed} margin={args.margin:.3f}",
    )


def _fmt(value: float | None, spec: str = ".3f") -> str:
    return "n/a" if value is None else format(value, spec)


def _print_report(args, events, label, folds) -> None:
    bets = [b for fold in folds for b in fold["bets"]]
    summary = summarise(bets)
    sharpe = summary["sharpe"]
    print(f"\n== data      {label}  fingerprint={data_fingerprint(events)}")
    print(
        f"== split     train={args.train} purge={args.purge} embargo={args.embargo} "
        f"test={args.test} folds={len(folds)}"
    )
    print(
        f"== costs     commission={args.commission:.2%} "
        f"slippage={args.slippage_bps:.0f}bps sizing={args.sizing} "
        f"min_edge={args.min_edge:+.2%}"
    )
    for i, fold in enumerate(folds, 1):
        fb = summarise(fold["bets"])
        print(
            f"   fold {i}: train {fold['train'][0]}..{fold['train'][1]} "
            f"test {fold['test'][0]}..{fold['test'][1]} "
            f"bets={fb['bets']:>4} roi={_fmt(fb['roi'], '+.2%')}"
        )
    print(
        f"\n== RESULT    bets={summary['bets']} hit={_fmt(summary['hit_rate'], '.1%')} "
        f"turnover={summary['turnover']:.4f} pnl={summary['pnl']:+.4f} "
        f"roi={_fmt(summary['roi'], '+.2%')}"
    )
    print(
        f"== METRICS   CLV={_fmt(summary['clv'], '+.2%')} "
        f"brier={_fmt(summary['brier'])} max_dd={_fmt(summary['max_drawdown'], '.1%')}"
    )
    print(
        f"== SHARPE    per_bet={_fmt(sharpe['per_bet'], '+.3f')} "
        f"annualised={_fmt(sharpe['annualised'], '+.2f')} "
        f"bets_per_year={_fmt(sharpe['bets_per_year'], '.0f')}"
    )


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        events, label = _load(args)
    except (OSError, ValueError) as exc:
        print(f"\n  UNMEASURABLE: {exc}")
        return EXIT_UNMEASURABLE

    costs = Costs(commission_pct=args.commission, slippage_bps=args.slippage_bps)
    sizing = Sizing(
        mode=args.sizing,
        flat_pct=args.flat_pct,
        kelly_pct=args.kelly_pct,
        max_stake_pct=args.max_stake_pct,
        min_edge=args.min_edge,
    )

    def factory(_history: Sequence[MarketView]):
        return SIGNALS[args.signal]

    try:
        folds = walk_forward(
            events,
            factory,
            train_n=args.train,
            test_n=args.test,
            embargo_n=args.embargo,
            purge_n=args.purge,
            costs=costs,
            sizing=sizing,
        )
    except LookaheadError as exc:
        print(f"\n  LOOKAHEAD: {exc}")
        print("  verdict: the signal used future data; its numbers are meaningless.")
        return EXIT_UNTRUSTWORTHY
    except ValueError as exc:
        print(f"\n  UNMEASURABLE: {exc}")
        return EXIT_UNMEASURABLE

    bets = [b for fold in folds for b in fold["bets"]]
    summary = summarise(bets)
    flags = lookahead_flags(bets)

    if args.json:
        print(
            json.dumps(
                {
                    "data": label,
                    "fingerprint": data_fingerprint(events),
                    "folds": len(folds),
                    "summary": summary,
                    "lookahead_flags": flags,
                },
                indent=2,
            )
        )
    else:
        _print_report(args, events, label, folds)
        if summary["bets"] == 0:
            print("\n== TRUST     no bet cleared the costs; nothing to report as a return")
        elif flags:
            print("\n== TRUST     NOT TRUSTWORTHY")
            for reason in flags:
                print(f"   - {reason}")
        else:
            print("\n== TRUST     measured; no lookahead canary fired. See docs/BACKTESTING.md")
    return EXIT_UNTRUSTWORTHY if flags else EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
