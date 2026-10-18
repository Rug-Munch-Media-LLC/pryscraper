#!/usr/bin/env python3
"""Honest backtest core: causality guard, walk-forward, costs, metrics.

This module exists because a backtest is only worth the constraints it
enforces, not the number it prints. Four constraints are structural here, not
documentation:

1. **Causality.** A signal receives a :class:`MarketView`, which has no
   outcome and no closing line. Touching either raises :class:`LookaheadError`
   instead of quietly returning ``None`` — a cheat is loud.
2. **Walk-forward.** Folds are train → embargo → test. ``purge_n`` events are
   removed from the end of every training window so an outcome that overlaps
   the test boundary cannot leak; ``embargo_n`` events are skipped between
   train and test to break short-range autocorrelation.
3. **Costs.** :class:`Costs` applies adverse price slippage and commission to
   the *payout*, so ``net_odds < raw_odds`` whenever either is non-zero. The
   default is not zero: a zero-cost default is how a losing strategy turns
   into a "profitable" one.
4. **Honest metrics.** Sharpe is annualised from the *observed events per
   year*, not from a hard-coded ``sqrt(252)``. A betting/event strategy does
   not trade 252 times a year, and pretending it does inflates the ratio.

The engine never mutates inputs and never touches the network.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

#: Fields that exist only at or after settlement. Reading one from a signal is
#: lookahead by definition. ``closing_odds`` is included because the closing
#: line is published *after* the bet is placed.
FORBIDDEN_AT_BET_TIME = frozenset(
    {"won", "outcome", "result", "settled", "pnl", "closing_odds", "closing"}
)


class LookaheadError(RuntimeError):
    """A signal read information that did not exist when the bet was placed."""


@dataclass(frozen=True)
class Event:
    """One settled event. Never handed to a signal — see :func:`view`."""

    event_id: str
    ts: float
    odds: float
    closing_odds: float
    won: bool
    features: tuple[float, ...] = ()


@dataclass(frozen=True)
class MarketView:
    """What a signal is allowed to see: price and pre-event features only."""

    event_id: str
    ts: float
    odds: float
    features: tuple[float, ...] = ()

    def __getattr__(self, name: str) -> Any:
        if name in FORBIDDEN_AT_BET_TIME:
            raise LookaheadError(
                f"signal read {name!r} on {self.event_id!r}; it is only known after "
                "settlement (or at the close). This run is not a backtest."
            )
        raise AttributeError(name)


def view(event: Event) -> MarketView:
    """Project a settled event onto the pre-bet information set."""
    return MarketView(event.event_id, event.ts, event.odds, event.features)


@dataclass(frozen=True)
class Costs:
    """Adverse costs. Both default non-zero on purpose."""

    commission_pct: float = 0.02
    slippage_bps: float = 25.0

    def net_odds(self, odds: float) -> float:
        """Decimal odds after a price haircut and commission on net winnings."""
        if not math.isfinite(odds) or odds <= 1.0:
            return 0.0
        taken = odds * (1.0 - self.slippage_bps / 10_000.0)
        return 1.0 + (taken - 1.0) * (1.0 - self.commission_pct)


@dataclass(frozen=True)
class Sizing:
    """Stake as a fraction of bankroll. Capped, and never negative."""

    mode: str = "flat"  # flat | kelly
    flat_pct: float = 0.01
    kelly_pct: float = 0.25
    max_stake_pct: float = 0.02
    #: Minimum edge (``prob*net_odds - 1``) required to place a bet. The
    #: default refuses negative-EV bets, which is why the signal's probability
    #: matters even under flat staking. Set negative to bet blindly.
    min_edge: float = 0.0

    def fraction(self, prob: float, net_odds: float) -> float:
        if prob * net_odds - 1.0 < self.min_edge:
            return 0.0
        if self.mode == "kelly":
            b = net_odds - 1.0
            if b <= 0.0:
                return 0.0
            edge = prob * net_odds - 1.0
            frac = max(0.0, edge / b) * self.kelly_pct
        else:
            frac = self.flat_pct
        return min(max(frac, 0.0), self.max_stake_pct)


@dataclass(frozen=True)
class Bet:
    event_id: str
    ts: float
    prob: float
    odds: float
    net_odds: float
    stake: float
    won: bool
    pnl: float
    closing_odds: float


Signal = Callable[[Sequence[MarketView], MarketView], float | None]
Factory = Callable[[Sequence[MarketView]], Signal]


@dataclass(frozen=True)
class FoldPlan:
    """Everything one out-of-sample window needs, in one object."""

    history: Sequence[MarketView]
    costs: Costs
    sizing: Sizing
    bankroll: float = 1.0


def run_fold(test: Sequence[Event], signal: Signal, plan: FoldPlan) -> tuple[list[Bet], float]:
    """Score one out-of-sample window. ``history`` is strictly pre-window."""
    bets: list[Bet] = []
    rolling = list(plan.history)  # past events only; appended ones are settled
    costs, sizing, bankroll = plan.costs, plan.sizing, plan.bankroll
    for event in test:
        prob = signal(rolling, view(event))
        if prob is None or not (0.0 < prob < 1.0):
            continue
        net = costs.net_odds(event.odds)
        frac = sizing.fraction(prob, net)
        if frac <= 0.0 or bankroll <= 0.0:
            continue
        stake = bankroll * frac
        pnl = stake * (net - 1.0) if event.won else -stake
        bets.append(
            Bet(
                event_id=event.event_id,
                ts=event.ts,
                prob=prob,
                odds=event.odds,
                net_odds=net,
                stake=stake,
                won=event.won,
                pnl=pnl,
                closing_odds=event.closing_odds,
            )
        )
        bankroll += pnl
        rolling.append(view(event))
    return bets, bankroll


def walk_forward(
    events: Sequence[Event], factory: Factory, **options: Any
) -> list[dict[str, Any]]:
    """Rolling walk-forward. Returns one dict per fold.

    Train window ``[start, start+train_n-purge_n)``; ``purge_n`` outcomes at its
    tail are dropped; ``embargo_n`` events are skipped; the test window is the
    next ``test_n`` events. Raises ``ValueError`` when the series cannot yield
    at least one fold — the caller must report "unmeasurable", never a number.
    """
    train_n = int(options.get("train_n", 400))
    test_n = int(options.get("test_n", 200))
    embargo_n = int(options.get("embargo_n", 10))
    purge_n = int(options.get("purge_n", 5))
    costs = options.get("costs") or Costs()
    sizing = options.get("sizing") or Sizing()
    if train_n <= purge_n or test_n < 1:
        raise ValueError("train_n must exceed purge_n and test_n must be >= 1")
    folds: list[dict[str, Any]] = []
    bankroll = 1.0
    start = 0
    while start + train_n + embargo_n + test_n <= len(events):
        train = events[start : start + train_n - purge_n]
        history = [view(e) for e in train]
        signal = factory(history)
        test_start = start + train_n + embargo_n
        test = events[test_start : test_start + test_n]
        bets, bankroll = run_fold(
            test, signal, FoldPlan(history, costs, sizing, bankroll)
        )
        folds.append(
            {
                "train": (train[0].event_id, train[-1].event_id),
                "test": (test[0].event_id, test[-1].event_id),
                "embargo_events": embargo_n,
                "bets": bets,
                "bankroll_end": bankroll,
            }
        )
        start += test_n
    if not folds:
        raise ValueError(
            f"series of {len(events)} events cannot fill one fold "
            f"(train={train_n}, embargo={embargo_n}, test={test_n})"
        )
    return folds


def _annualised_sharpe(bets: Sequence[Bet]) -> dict[str, Any]:
    n = len(bets)
    if n < 3:
        return {"per_bet": None, "annualised": None, "bets_per_year": None}
    returns: list[float] = []
    equity = 1.0
    for bet in bets:
        if bet.stake > 0.0 and equity > 0.0:
            returns.append(bet.pnl / equity)  # portfolio return, not per-stake
        equity += bet.pnl
    mean = statistics.fmean(returns)
    sd = statistics.stdev(returns) if len(returns) > 1 else 0.0
    span_days = (bets[-1].ts - bets[0].ts) / 86_400.0
    if sd <= 0.0 or span_days <= 0.0:
        return {"per_bet": None, "annualised": None, "bets_per_year": None}
    bpy = n / (span_days / 365.25)
    per_bet = mean / sd
    return {"per_bet": per_bet, "annualised": per_bet * math.sqrt(bpy), "bets_per_year": bpy}


def _max_drawdown(bets: Sequence[Bet]) -> float:
    equity = 1.0
    peak = 1.0
    worst = 0.0
    for bet in bets:
        equity += bet.pnl
        peak = max(peak, equity)
        if peak > 0.0:
            worst = max(worst, (peak - equity) / peak)
    return worst


def summarise(bets: Sequence[Bet]) -> dict[str, Any]:
    """Pooled metrics. Every ratio names its denominator; nothing is implied."""
    n = len(bets)
    if n == 0:
        return {
            "bets": 0,
            "turnover": 0.0,
            "pnl": 0.0,
            "roi": None,
            "hit_rate": None,
            "clv": None,
            "brier": None,
            "max_drawdown": None,
            "sharpe": {"per_bet": None, "annualised": None, "bets_per_year": None},
        }
    turnover = sum(b.stake for b in bets)
    pnl = sum(b.pnl for b in bets)
    wins = sum(1 for b in bets if b.won)
    clv = statistics.fmean(b.odds / b.closing_odds - 1.0 for b in bets)
    brier = statistics.fmean((b.prob - (1.0 if b.won else 0.0)) ** 2 for b in bets)
    return {
        "bets": n,
        "turnover": turnover,
        "pnl": pnl,
        "roi": (pnl / turnover) if turnover > 0.0 else None,
        "hit_rate": wins / n,
        "clv": clv,
        "brier": brier,
        "max_drawdown": _max_drawdown(bets),
        "sharpe": _annualised_sharpe(bets),
    }


def lookahead_flags(bets: Sequence[Bet]) -> list[str]:
    """Statistical canaries for a strategy that is cheating.

    The structural guard stops the documented leak paths. These catch a
    strategy that leaks some other way (a global cache, a precomputed table, a
    feature built from settled rows): near-perfect hit rates and implausible
    returns are not reachable by a real market-facing model.
    """
    n = len(bets)
    if n < 30:
        return []
    reasons: list[str] = []
    hit = sum(1 for b in bets if b.won) / n
    turnover = sum(b.stake for b in bets)
    roi = (sum(b.pnl for b in bets) / turnover) if turnover > 0.0 else 0.0
    if hit >= 0.95:
        reasons.append(f"hit rate {hit:.1%} over {n} bets: not reachable without future data")
    if roi >= 2.0:
        reasons.append(f"ROI {roi:+.0%} over {n} bets: implausible for a priced market")
    return reasons
