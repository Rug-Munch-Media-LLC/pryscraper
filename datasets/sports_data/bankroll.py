"""Bankroll management and Kelly-criterion bet sizing.

Pure-math, synchronous module. No HTTP calls, no I/O. Every function is
unit-testable and never raises: invalid inputs degrade to a dict with
``None`` values (or ``0.0`` where a number is always meaningful).

Kelly criterion
---------------
For decimal odds ``d`` and win probability ``p`` (with ``b = d - 1`` and
``q = 1 - p``), the full-Kelly fraction of bankroll to stake is::

    f* = (b * p - q) / b = (p * d - 1) / (d - 1)

A bet is +EV when ``p * d - 1 > 0`` (see ``datasets.sports_data.ev``).
Fractional Kelly (half, quarter) trades growth rate for lower variance;
``optimal_stake`` additionally caps the stake at ``max_bet_pct`` of
bankroll and estimates a simplified risk of ruin.

Contract
--------
* :func:`kelly_fraction` — full Kelly stake sizing with edge / EV / CI.
* :func:`kelly_half` — half-Kelly (conservative, ~75% of growth, ~half
  the variance).
* :func:`kelly_quarter` — quarter-Kelly (very conservative).
* :func:`optimal_stake` — full stake recommendation with cap + risk of ruin.
* :func:`clv_analysis` — closing line value analysis.
* :func:`bankroll_projection` — multi-day bankroll growth projection.
* :func:`variance_adjusted_kelly` — Kelly shrunk for probability uncertainty.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import math
from typing import Any

# Kelly fraction above this is almost certainly a bad input (e.g. p too
# high for the odds); we still return it but flag it via the cap logic.
_MAX_SANE_KELLY = 1.0


def _validate_inputs(win_prob: Any, decimal_odds: Any) -> tuple[float, float] | None:
    """Return validated (win_prob, decimal_odds) or ``None`` if unusable."""
    try:
        p = float(win_prob)
        d = float(decimal_odds)
    except (TypeError, ValueError):
        return None
    if not (0.0 < p < 1.0) or d <= 1.0 or not math.isfinite(p) or not math.isfinite(d):
        return None
    return p, d


def _kelly_core(win_prob: float, decimal_odds: float, kelly_pct: float) -> dict[str, Any]:
    """Shared Kelly math. ``kelly_pct`` is the fraction of full Kelly (0-1)."""
    validated = _validate_inputs(win_prob, decimal_odds)
    if validated is None:
        return {
            "kelly_pct": None,
            "edge": None,
            "expected_value": None,
            "confidence_interval": None,
            "valid": False,
        }
    p, d = validated
    b = d - 1.0
    q = 1.0 - p
    edge = p * d - 1.0  # EV per dollar staked
    full_kelly = edge / b if b > 0 else 0.0
    full_kelly = max(0.0, min(full_kelly, _MAX_SANE_KELLY))
    scaled = full_kelly * kelly_pct
    # Approximate 95% CI on the edge from binomial sampling noise:
    # se(edge) ~ sqrt(p*q)/sqrt(n) * d with n=100 reference bets.
    n_ref = 100.0
    se = math.sqrt(p * q / n_ref) * d
    ci = (max(0.0, edge - 1.96 * se), edge + 1.96 * se)
    return {
        "kelly_pct": round(scaled * 100.0, 4),  # % of bankroll to stake
        "full_kelly_pct": round(full_kelly * 100.0, 4),
        "kelly_fraction_used": kelly_pct,
        "edge": round(edge, 6),
        "edge_pct": round(edge * 100.0, 4),
        "expected_value": round(edge, 6),  # EV per $1 staked
        "confidence_interval": [round(ci[0], 6), round(ci[1], 6)],
        "win_prob": round(p, 6),
        "decimal_odds": round(d, 4),
        "valid": True,
    }


def kelly_fraction(win_prob: float, decimal_odds: float, kelly_pct: float = 1.0) -> dict[str, Any]:
    """Full Kelly stake sizing.

    Args:
        win_prob: Estimated true win probability, strictly between 0 and 1.
        decimal_odds: Decimal (European) odds, must be > 1.0.
        kelly_pct: Fraction of full Kelly to use (1.0 = full Kelly).

    Returns:
        Dict with ``kelly_pct`` (recommended % of bankroll), ``edge``,
        ``expected_value``, ``confidence_interval`` and metadata. Invalid
        inputs return a dict with ``None`` values and ``valid=False``.
    """
    try:
        frac = float(kelly_pct)
    except (TypeError, ValueError):
        frac = 1.0
    frac = max(0.0, min(frac, 1.0))
    return _kelly_core(win_prob, decimal_odds, frac)


def kelly_half(win_prob: float, decimal_odds: float) -> dict[str, Any]:
    """Half-Kelly: more conservative, roughly half the variance of full
    Kelly for ~75% of the growth rate."""
    return _kelly_core(win_prob, decimal_odds, 0.5)


def kelly_quarter(win_prob: float, decimal_odds: float) -> dict[str, Any]:
    """Quarter-Kelly: very conservative, minimal drawdowns at the cost of
    slower bankroll growth."""
    return _kelly_core(win_prob, decimal_odds, 0.25)


def _risk_of_ruin(edge: float, kelly_fraction_used: float, bets: int = 1000) -> float:
    """Simplified risk-of-ruin estimate.

    Uses a diffusion approximation for a fractional-Kelly bettor: ruin
    probability decays roughly exponentially in edge and in the Kelly
    fraction used. This is a heuristic, not an exact solution.
    """
    if edge <= 0.0:
        return 1.0
    # Growth-rate drag from betting a fraction f of full Kelly:
    # g(f) ~ f - f^2/2 (per unit edge). Ruin exponent ~ 2 * g * bets.
    f = max(0.0, min(kelly_fraction_used, 1.0))
    growth = f - (f * f) / 2.0
    exponent = 2.0 * growth * edge * bets
    return max(0.0, min(1.0, math.exp(-exponent)))


def optimal_stake(
    bankroll: float,
    win_prob: float,
    decimal_odds: float,
    kelly_pct: float = 0.5,
    max_bet_pct: float = 5.0,
) -> dict[str, Any]:
    """Full stake recommendation with a bankroll-percentage cap.

    Args:
        bankroll: Current bankroll (currency units, must be > 0).
        win_prob: Estimated true win probability (0-1 exclusive).
        decimal_odds: Decimal odds (> 1.0).
        kelly_pct: Fraction of full Kelly (default 0.5 = half-Kelly).
        max_bet_pct: Hard cap on stake as % of bankroll (default 5.0).

    Returns:
        Dict with ``stake_amount``, ``stake_pct``, ``kelly_raw``,
        ``kelly_capped``, ``edge``, ``ev_per_dollar`` and a simplified
        ``risk_of_ruin``. Invalid inputs return ``None`` fields.
    """
    try:
        br = float(bankroll)
        cap = float(max_bet_pct)
        frac = float(kelly_pct)
    except (TypeError, ValueError):
        br, cap, frac = 0.0, 5.0, 0.5
    if br <= 0.0 or not math.isfinite(br):
        return {
            "stake_amount": None,
            "stake_pct": None,
            "kelly_raw": None,
            "kelly_capped": None,
            "edge": None,
            "ev_per_dollar": None,
            "risk_of_ruin": None,
            "valid": False,
        }
    frac = max(0.0, min(frac, 1.0))
    cap = max(0.0, cap)
    core = _kelly_core(win_prob, decimal_odds, frac)
    if not core.get("valid"):
        return {
            "stake_amount": None,
            "stake_pct": None,
            "kelly_raw": None,
            "kelly_capped": None,
            "edge": None,
            "ev_per_dollar": None,
            "risk_of_ruin": None,
            "valid": False,
        }
    kelly_raw_pct = float(core["kelly_pct"])  # % of bankroll (already frac-scaled)
    capped_pct = min(kelly_raw_pct, cap)
    stake = br * capped_pct / 100.0
    edge = float(core["edge"])
    return {
        "stake_amount": round(stake, 2),
        "stake_pct": round(capped_pct, 4),
        "kelly_raw": round(kelly_raw_pct, 4),
        "kelly_capped": round(capped_pct, 4),
        "capped": kelly_raw_pct > cap,
        "edge": round(edge, 6),
        "ev_per_dollar": round(edge, 6),
        "ev_per_bet": round(stake * edge, 4),
        "risk_of_ruin": round(_risk_of_ruin(edge, frac), 6),
        "bankroll": round(br, 2),
        "kelly_fraction_used": frac,
        "max_bet_pct": cap,
        "valid": True,
    }


def clv_analysis(closing_odds: float, placed_odds: float, bet_count: int = 100) -> dict[str, Any]:
    """Closing Line Value (CLV) analysis.

    CLV measures how much better your price was than the closing line —
    the single best predictor of long-term betting profitability.

    Args:
        closing_odds: Decimal odds at kickoff/close (> 1.0).
        placed_odds: Decimal odds you actually got (> 1.0).
        bet_count: Number of bets to aggregate over (default 100).

    Returns:
        Dict with ``clv_pct`` (per-bet CLV in %), ``clv_per_bet``,
        ``beats_closing_rate`` (1.0 if you beat the close, 0.0 if not),
        ``expected_roi`` and ``unit_profit`` over ``bet_count`` 1-unit bets.
    """
    try:
        close = float(closing_odds)
        placed = float(placed_odds)
        n = max(1, int(bet_count))
    except (TypeError, ValueError):
        return {
            "clv_pct": None,
            "clv_per_bet": None,
            "beats_closing_rate": None,
            "expected_roi": None,
            "unit_profit": None,
            "valid": False,
        }
    if close <= 1.0 or placed <= 1.0 or not math.isfinite(close) or not math.isfinite(placed):
        return {
            "clv_pct": None,
            "clv_per_bet": None,
            "beats_closing_rate": None,
            "expected_roi": None,
            "unit_profit": None,
            "valid": False,
        }
    # CLV per bet: (placed / closing - 1) — positive means you beat the close.
    clv = placed / close - 1.0
    beats = 1.0 if placed > close else 0.0
    # Expected ROI: assume the closing line is fair; betting at better than
    # fair odds yields EV = placed/closing - 1 per unit staked.
    expected_roi = clv
    unit_profit = expected_roi * n
    return {
        "clv_pct": round(clv * 100.0, 4),
        "clv_per_bet": round(clv, 6),
        "beats_closing_rate": beats,
        "expected_roi": round(expected_roi, 6),
        "unit_profit": round(unit_profit, 4),
        "bet_count": n,
        "closing_odds": round(close, 4),
        "placed_odds": round(placed, 4),
        "valid": True,
    }


def bankroll_projection(
    starting_bankroll: float,
    avg_edge: float,
    bets_per_day: int = 10,
    days: int = 30,
    kelly_pct: float = 0.5,
) -> dict[str, Any]:
    """Project bankroll growth from an average edge.

    Uses the Kelly growth approximation ``g = f*edge - (f*edge)^2 / 2``
    per bet (log-growth of a fractional-Kelly bettor), compounded over
    ``bets_per_day * days`` bets.

    Args:
        starting_bankroll: Starting bankroll (> 0).
        avg_edge: Average edge per bet as a decimal (e.g. 0.03 = 3%).
        bets_per_day: Bets placed per day (default 10).
        days: Projection horizon in days (default 30).
        kelly_pct: Fraction of full Kelly (default 0.5).

    Returns:
        Dict with ``projected_bankroll``, ``growth_rate`` (per bet),
        ``max_drawdown_estimate`` (heuristic % of peak) and ``roi_estimate``
        (total return over the horizon).
    """
    try:
        start = float(starting_bankroll)
        edge = float(avg_edge)
        bpd = max(0, int(bets_per_day))
        d = max(0, int(days))
        frac = max(0.0, min(float(kelly_pct), 1.0))
    except (TypeError, ValueError):
        return {
            "projected_bankroll": None,
            "growth_rate": None,
            "max_drawdown_estimate": None,
            "roi_estimate": None,
            "valid": False,
        }
    if start <= 0.0 or not math.isfinite(start) or not math.isfinite(edge):
        return {
            "projected_bankroll": None,
            "growth_rate": None,
            "max_drawdown_estimate": None,
            "roi_estimate": None,
            "valid": False,
        }
    total_bets = bpd * d
    # Per-bet stake fraction of bankroll: fractional Kelly on the edge.
    # Full Kelly for edge e at even-ish odds ~ e; scaled by kelly_pct.
    f = max(0.0, min(edge * frac, 0.25))  # sanity cap at 25% of bankroll
    # Log-growth per bet for a fractional-Kelly bettor with edge e:
    # g = f*e - f^2/2 (win prob folded into the edge approximation).
    growth_per_bet = f * edge - (f * f) / 2.0
    growth_per_bet = max(growth_per_bet, 0.0)
    projected = start * math.exp(growth_per_bet * total_bets)
    # Heuristic max drawdown: fractional Kelly bettors see drawdowns of
    # roughly (1 - f) * 100% of peak in bad stretches; scale by horizon.
    dd = min(0.95, (1.0 - f) * 0.5 * (1.0 + math.log1p(total_bets) / 10.0))
    roi = projected / start - 1.0
    return {
        "projected_bankroll": round(projected, 2),
        "starting_bankroll": round(start, 2),
        "growth_rate": round(growth_per_bet, 8),
        "growth_rate_pct": round(growth_per_bet * 100.0, 4),
        "max_drawdown_estimate": round(dd * 100.0, 2),
        "roi_estimate": round(roi * 100.0, 2),
        "total_bets": total_bets,
        "bets_per_day": bpd,
        "days": d,
        "kelly_pct": frac,
        "avg_edge": round(edge, 6),
        "valid": True,
    }


def variance_adjusted_kelly(
    win_prob: float, decimal_odds: float, confidence: float = 0.95
) -> dict[str, Any]:
    """Kelly sizing shrunk for uncertainty in the win probability.

    Your probability estimate is noisy; betting full Kelly on an
    overestimated ``p`` is the classic bankroll killer. This shrinks the
    estimate toward 0.5 by a confidence-dependent factor before computing
    Kelly, then reports both raw and adjusted fractions.

    Args:
        win_prob: Estimated win probability (0-1 exclusive).
        decimal_odds: Decimal odds (> 1.0).
        confidence: Confidence in the estimate, 0-1 (default 0.95).
            Lower confidence = more shrinkage toward 0.5 = smaller stake.

    Returns:
        Dict with ``kelly_pct`` (variance-adjusted % of bankroll),
        ``kelly_raw_pct`` (unadjusted), ``adjusted_win_prob``, ``edge``
        and ``expected_value``.
    """
    validated = _validate_inputs(win_prob, decimal_odds)
    if validated is None:
        return {
            "kelly_pct": None,
            "kelly_raw_pct": None,
            "adjusted_win_prob": None,
            "edge": None,
            "expected_value": None,
            "valid": False,
        }
    try:
        conf = max(0.0, min(float(confidence), 1.0))
    except (TypeError, ValueError):
        conf = 0.95
    p, d = validated
    # Shrink toward 0.5: weight = confidence.
    p_adj = p * conf + 0.5 * (1.0 - conf)
    core = _kelly_core(p_adj, d, 1.0)
    raw = _kelly_core(p, d, 1.0)
    return {
        "kelly_pct": core.get("kelly_pct"),
        "kelly_raw_pct": raw.get("kelly_pct"),
        "adjusted_win_prob": round(p_adj, 6),
        "win_prob": round(p, 6),
        "edge": core.get("edge"),
        "expected_value": core.get("expected_value"),
        "confidence": conf,
        "decimal_odds": round(d, 4),
        "valid": True,
    }
