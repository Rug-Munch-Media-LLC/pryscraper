"""The backtest must fail a cheating strategy and pass a clean one.

Every test here exists because a backtest that cannot fail is a marketing
document. The two load-bearing cases are the lookahead canary (a signal that
reads the outcome must raise, not score) and the market baseline (a blind
bettor must lose roughly the book's margin, which is what the generator was
built to make computable).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import backtest_core as core  # noqa: E402
import backtest_strategy as cli  # noqa: E402
from backtest_data import data_fingerprint, generate_synthetic  # noqa: E402


def _events(n: int = 900, seed: int = 11) -> list[core.Event]:
    return generate_synthetic(n, seed=seed)


def _bet(i: int, ts: float, pnl: float, won: bool, stake: float = 1.0) -> core.Bet:
    return core.Bet(
        event_id=f"b{i}",
        ts=ts,
        prob=0.5,
        odds=2.0,
        net_odds=1.9,
        stake=stake,
        won=won,
        pnl=pnl,
        closing_odds=1.95,
    )


# ── causality ──────────────────────────────────────────────────────────────


def test_market_view_refuses_outcome_and_closing_line() -> None:
    v = core.view(_events(1)[0])
    for field in ("won", "outcome", "closing_odds"):
        with pytest.raises(core.LookaheadError):
            getattr(v, field)


def test_lookahead_signal_raises_instead_of_scoring() -> None:
    """The canary must not produce a number at all."""
    with pytest.raises(core.LookaheadError):
        core.walk_forward(
            _events(), lambda _h: cli.lookahead_signal, train_n=300, test_n=100, embargo_n=10
        )


def test_cli_returns_untrustworthy_for_the_lookahead_canary(capsys) -> None:
    code = cli.main(["--signal", "lookahead", "--events", "600", "--train", "300", "--test", "100"])
    assert code == cli.EXIT_UNTRUSTWORTHY
    assert "LOOKAHEAD" in capsys.readouterr().out


def test_clean_signal_runs_end_to_end() -> None:
    folds = core.walk_forward(
        _events(), lambda _h: cli.model_signal, train_n=300, test_n=100, embargo_n=10
    )
    bets = [b for f in folds for b in f["bets"]]
    assert folds
    assert bets
    summary = core.summarise(bets)
    assert 0.0 <= summary["hit_rate"] <= 1.0
    assert summary["roi"] is not None


# ── split integrity ────────────────────────────────────────────────────────


def test_train_and_test_are_separated_by_purge_plus_embargo() -> None:
    events = _events()
    index = {e.event_id: i for i, e in enumerate(events)}
    folds = core.walk_forward(
        events, lambda _h: cli.market_signal, train_n=300, test_n=100, purge_n=7, embargo_n=12
    )
    for fold in folds:
        train_end = index[fold["train"][1]]
        test_start = index[fold["test"][0]]
        # 7 purged + 12 embargoed events sit between the windows.
        assert test_start - train_end == 7 + 12 + 1
        assert events[test_start].ts > events[train_end].ts


def test_too_few_events_is_unmeasurable_not_zero() -> None:
    with pytest.raises(ValueError, match="cannot fill one fold"):
        core.walk_forward(_events(50), lambda _h: cli.market_signal, train_n=400, test_n=100)


# ── costs ──────────────────────────────────────────────────────────────────


def test_net_odds_are_never_better_than_the_quoted_price() -> None:
    costs = core.Costs(commission_pct=0.02, slippage_bps=25)
    for odds in (1.5, 2.0, 3.4, 10.0):
        assert costs.net_odds(odds) < odds
    assert core.Costs(0.0, 0.0).net_odds(2.0) == pytest.approx(2.0)


def test_costs_strictly_reduce_roi() -> None:
    events = _events(1200, seed=5)
    gross = core.walk_forward(
        events,
        lambda _h: cli.model_signal,
        train_n=300,
        test_n=100,
        costs=core.Costs(0.0, 0.0),
    )
    net = core.walk_forward(
        events,
        lambda _h: cli.model_signal,
        train_n=300,
        test_n=100,
        costs=core.Costs(0.02, 25.0),
    )
    gross_roi = core.summarise([b for f in gross for b in f["bets"]])["roi"]
    net_roi = core.summarise([b for f in net for b in f["bets"]])["roi"]
    assert gross_roi is not None
    assert net_roi is not None
    assert net_roi < gross_roi


def test_kelly_refuses_a_negative_ev_bet() -> None:
    sizing = core.Sizing(mode="kelly")
    assert sizing.fraction(0.50, 1.90) == 0.0  # EV = 0.5*1.9 - 1 = -5%
    assert sizing.fraction(0.60, 1.90) > 0.0
    assert sizing.fraction(0.99, 1.90) <= sizing.max_stake_pct


# ── metrics ────────────────────────────────────────────────────────────────


def test_sharpe_annualises_from_observed_bets_per_year() -> None:
    """500 bets over 365 days is 500 bets/year — not 252 trading days."""
    start = 1_700_000_000.0
    step = 365.0 * 86_400.0 / 500
    bets = [
        _bet(i, start + i * step, pnl=0.2 if i % 2 == 0 else 0.0, won=i % 2 == 0)
        for i in range(500)
    ]
    sharpe = core.summarise(bets)["sharpe"]
    assert sharpe["per_bet"] is not None
    assert sharpe["per_bet"] > 0
    assert sharpe["bets_per_year"] == pytest.approx(500.0, rel=0.01)
    assert sharpe["annualised"] == pytest.approx(sharpe["per_bet"] * 500**0.5, rel=0.01)
    assert sharpe["annualised"] != pytest.approx(sharpe["per_bet"] * 252**0.5, rel=0.01)


def test_max_drawdown_is_peak_to_trough() -> None:
    start = 1_700_000_000.0
    # +0.10, -0.05, -0.05 → equity 1.10 → 1.05 → 1.00; dd from 1.10 is 9.09%.
    bets = [
        _bet(0, start, 0.10, True),
        _bet(1, start + 60, -0.05, False),
        _bet(2, start + 120, -0.05, False),
    ]
    assert core.summarise(bets)["max_drawdown"] == pytest.approx(1 - 1.0 / 1.10)


# ── the canaries and the market baseline ───────────────────────────────────


def test_lookahead_flags_catch_an_impossible_hit_rate() -> None:
    start = 1_700_000_000.0
    cheat = [_bet(i, start + i * 60, 1.0, True) for i in range(40)]
    clean = [_bet(i, start + i * 60, 1.0 if i % 2 else -1.0, bool(i % 2)) for i in range(40)]
    assert core.lookahead_flags(cheat)
    assert core.lookahead_flags(clean) == []


def test_blind_betting_loses_roughly_the_margin() -> None:
    """Falsifiable baseline: a market follower has EV ≈ -margin by construction."""
    events = generate_synthetic(2000, seed=7, margin=0.045)
    folds = core.walk_forward(
        events,
        lambda _h: cli.market_signal,
        train_n=400,
        test_n=200,
        costs=core.Costs(0.0, 0.0),
        sizing=core.Sizing(mode="flat", flat_pct=0.01, min_edge=-1.0),
    )
    roi = core.summarise([b for f in folds for b in f["bets"]])["roi"]
    assert roi is not None
    assert -0.08 < roi < -0.02, roi


def test_synthetic_series_is_deterministic() -> None:
    assert data_fingerprint(generate_synthetic(200, seed=3)) == data_fingerprint(
        generate_synthetic(200, seed=3)
    )
    assert data_fingerprint(generate_synthetic(200, seed=3)) != data_fingerprint(
        generate_synthetic(200, seed=4)
    )
