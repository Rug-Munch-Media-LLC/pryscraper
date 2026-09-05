"""Exotic bet derivative math — teasers, pleasers, if-bets, reverses, round robins.

Pure-math pricing for exotic bet types. No network involved — the legs the
caller passes are the legs that get priced. All functions are synchronous and
deterministic.

Odds conventions
----------------
Leg ``odds`` values are auto-detected: values ``<= 100`` are treated as
decimal odds (e.g. ``1.91``), values ``> 100`` (or negative) as American odds
(e.g. ``-110``, ``+150``). All internal math is decimal; American odds are
converted on the way in and reported alongside.

Teaser/pleaser adjustment model
-------------------------------
Each point of adjustment shifts a leg's implied probability by a fixed
``_PROB_PER_POINT`` (2.5%) — a reasonable flat approximation for spread and
total markets near the key numbers. Teasers shift *toward* the bettor
(higher win probability, lower payout); pleasers shift *away* (lower
probability, much higher payout). Moneyline (``h2h``) legs are not
adjustable and are priced at their original odds in both directions.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import contextlib
import itertools
import logging
from typing import Any

logger = logging.getLogger(__name__)

_PROB_PER_POINT = 0.025  # implied-probability shift per adjustment point
_ADJUSTABLE = frozenset(
    {"spread", "spreads", "total", "totals", "ou", "alternate_spread", "alternate_total"}
)


# ── Odds conversion ────────────────────────────────────────────────────
def american_to_decimal(odds: int) -> float:
    """Convert American odds (e.g. -110, +150) to decimal odds."""
    try:
        value = int(odds)
    except (TypeError, ValueError):
        return 1.0
    if value == 0:
        return 1.0
    if value > 0:
        return round(1.0 + value / 100.0, 6)
    return round(1.0 + 100.0 / abs(value), 6)


def decimal_to_american(decimal: float) -> int:
    """Convert decimal odds (e.g. 1.91) to American odds (e.g. -110)."""
    try:
        value = float(decimal)
    except (TypeError, ValueError):
        return 0
    if value <= 1.0:
        return 0
    if value >= 2.0:
        return round((value - 1.0) * 100.0)
    return round(-100.0 / (value - 1.0))


def parlay_decimal(odds_list: list[float]) -> float:
    """Combined decimal odds for a parlay of decimal-odds legs."""
    combined = 1.0
    for odds in odds_list or []:
        try:
            value = float(odds)
        except (TypeError, ValueError):
            continue
        if value > 1.0:
            combined *= value
    return round(combined, 6)


# ── Leg normalization ──────────────────────────────────────────────────
def _leg_decimal(leg: dict[str, Any]) -> float:
    """Coerce a leg's ``odds`` to decimal (auto-detect American vs decimal)."""
    raw = leg.get("odds")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return 0.0
    if value < 0 or value > 100.0:  # American-style (e.g. -110, +150)
        return american_to_decimal(int(value))
    if value <= 1.0:
        return 0.0
    return value  # decimal


def _normalize_leg(leg: Any, index: int) -> dict[str, Any] | None:
    """Validate/coerce one caller-supplied leg into the canonical shape."""
    if not isinstance(leg, dict):
        return None
    decimal = _leg_decimal(leg)
    if decimal <= 1.0:
        return None
    selection = str(leg.get("selection") or leg.get("side") or leg.get("label") or "").strip()
    if not selection:
        return None
    leg_type = str(leg.get("type") or leg.get("market") or "h2h").strip().lower()
    american = decimal_to_american(decimal)
    return {
        "index": index,
        "selection": selection,
        "type": leg_type,
        "odds": american,
        "decimal_odds": decimal,
        "implied_prob": round(1.0 / decimal, 6),
        "adjustable": leg_type in _ADJUSTABLE,
    }


def _normalize_legs(legs: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Normalize a leg list, dropping invalid entries."""
    normalized: list[dict[str, Any]] = []
    for index, leg in enumerate(legs or []):
        norm = _normalize_leg(leg, index)
        if norm is not None:
            normalized.append(norm)
    return normalized


def _shift_prob(prob: float, points: float, toward_bettor: bool) -> float:
    """Shift an implied probability by ``points`` (2.5%/point heuristic)."""
    delta = _PROB_PER_POINT * points
    shifted = prob + delta if toward_bettor else prob - delta
    return min(0.99, max(0.01, shifted))


def _adjusted_leg(leg: dict[str, Any], adjustment: int, toward_bettor: bool) -> dict[str, Any]:
    """Return the leg with its line/odds adjusted for a teaser or pleaser."""
    out = dict(leg)
    if not leg["adjustable"] or adjustment <= 0:
        out["adjusted_odds"] = leg["odds"]
        out["adjusted_decimal"] = leg["decimal_odds"]
        out["adjusted_prob"] = leg["implied_prob"]
        return out
    sign = -1 if toward_bettor else 1  # teaser moves line in bettor's favor
    base_line = leg.get("line")
    if base_line is not None:
        with contextlib.suppress(TypeError, ValueError):
            out["adjusted_line"] = round(float(base_line) + sign * adjustment, 2)
    prob = _shift_prob(leg["implied_prob"], adjustment, toward_bettor)
    decimal = round(1.0 / prob, 6)
    out["adjusted_prob"] = round(prob, 6)
    out["adjusted_decimal"] = decimal
    out["adjusted_odds"] = decimal_to_american(decimal)
    return out


# ── Teaser / pleaser ───────────────────────────────────────────────────
def price_teaser(
    legs: list[dict[str, Any]], adjustment: int = 6, direction: str = "teaser"
) -> dict[str, Any]:
    """Price a teaser (points in your favor) or pleaser (points against you).

    Args:
        legs: Leg dicts with ``selection``, ``odds`` and ``type`` (spread /
            total legs are adjustable; h2h legs price at their original odds).
        adjustment: Points of adjustment per leg (default 6).
        direction: ``"teaser"`` (favorable) or ``"pleaser"`` (against you).

    Returns:
        Dict with ``adjusted_lines``, ``combined_odds`` (decimal + American),
        ``implied_prob``, ``payout`` on a 100 stake, and ``breakeven`` — or
        ``{}`` when fewer than two valid legs remain. Never raises.
    """
    try:
        return _price_teaser(legs, adjustment, direction)
    except Exception:
        logger.exception("sports_teaser_price_crashed")
        return {}


def _price_teaser(legs: list[dict[str, Any]], adjustment: int, direction: str) -> dict[str, Any]:
    normalized = _normalize_legs(legs)
    if len(normalized) < 2:
        return {}
    toward = str(direction or "teaser").strip().lower() != "pleaser"
    adjusted = [_adjusted_leg(leg, max(0, int(adjustment or 0)), toward) for leg in normalized]
    combined = 1.0
    implied = 1.0
    for leg in adjusted:
        combined *= float(leg["adjusted_decimal"])
        implied *= float(leg["adjusted_prob"])
    combined = round(combined, 6)
    stake = 100.0
    return {
        "direction": "pleaser" if not toward else "teaser",
        "adjustment": int(adjustment or 0),
        "adjusted_lines": adjusted,
        "combined_odds": {
            "decimal": combined,
            "american": decimal_to_american(combined),
        },
        "implied_prob": round(implied, 6),
        "payout": {
            "stake": stake,
            "profit": round(stake * (combined - 1.0), 2),
            "total_return": round(stake * combined, 2),
        },
        "breakeven": round(1.0 / combined, 6),
        "source": "sports_derivatives",
    }


# ── If-bet ─────────────────────────────────────────────────────────────
def _if_bet_scenarios(normalized: list[dict[str, Any]], stake: float) -> list[dict[str, Any]]:
    """Enumerate win/loss scenarios for a sequential if-bet chain.

    Leg ``i+1`` is only placed (risking ``stake``) if every earlier leg won.
    Returns one record per outcome path with the legs placed and net result.
    """
    scenarios: list[dict[str, Any]] = []
    count = len(normalized)
    for bits in itertools.product((True, False), repeat=count):
        placed: list[str] = []
        net = 0.0
        for index, won in enumerate(bits):
            if not won:
                # The leg was placed (all earlier legs won) and lost its stake.
                net -= stake
                break
            leg = normalized[index]
            placed.append(str(leg["selection"]))
            net += stake * (float(leg["decimal_odds"]) - 1.0)  # win: profit, stake returns
        scenarios.append(
            {
                "outcomes": ["win" if b else "loss" for b in bits],
                "legs_placed": placed,
                "net": round(net, 2),
            }
        )
    return scenarios


def price_if_bet(legs: list[dict[str, Any]], max_risk: float = 100) -> dict[str, Any]:
    """Price an if-bet (conditional chain: leg 2 only runs if leg 1 wins).

    Args:
        legs: Ordered leg dicts; later legs are conditional on earlier wins.
        max_risk: Stake risked on each placed leg (default 100).

    Returns:
        Dict with ``scenarios``, ``max_win``, ``max_loss`` and
        ``effective_odds`` — or ``{}`` when fewer than two valid legs remain.
        Never raises.
    """
    try:
        return _price_if_bet(legs, max_risk)
    except Exception:
        logger.exception("sports_if_bet_price_crashed")
        return {}


def _price_if_bet(legs: list[dict[str, Any]], max_risk: float) -> dict[str, Any]:
    normalized = _normalize_legs(legs)
    if len(normalized) < 2:
        return {}
    stake = max(0.0, float(max_risk or 100))
    scenarios = _if_bet_scenarios(normalized, stake)
    nets = [float(s["net"]) for s in scenarios]
    max_win = max(nets)
    max_loss = min(nets)
    decimal = effective_decimal(max_win, stake)
    return {
        "bet_type": "if_bet",
        "leg_count": len(normalized),
        "stake_per_leg": round(stake, 2),
        "scenarios": scenarios,
        "max_win": round(max_win, 2),
        "max_loss": round(max_loss, 2),
        "effective_odds": {
            "decimal": decimal,
            "american": decimal_to_american(decimal),
        },
        "source": "sports_derivatives",
    }


def effective_decimal(max_win: float, stake: float) -> float:
    """Decimal odds implied by a max win on a given stake (1.0 when no win)."""
    if stake <= 0 or max_win <= 0:
        return 1.0
    return round(1.0 + max_win / stake, 6)


# ── Reverse bet ────────────────────────────────────────────────────────
def price_reverse_bet(legs: list[dict[str, Any]], max_risk: float = 100) -> dict[str, Any]:
    """Price a reverse bet (two if-bets: A→B and B→A).

    Args:
        legs: Leg dicts (exactly the two directions are priced).
        max_risk: Stake risked per if-bet chain (default 100).

    Returns:
        Dict with ``scenarios`` (per chain), ``max_win`` and ``max_loss``
        across both directions — or ``{}`` when fewer than two valid legs
        remain. Never raises.
    """
    try:
        return _price_reverse_bet(legs, max_risk)
    except Exception:
        logger.exception("sports_reverse_price_crashed")
        return {}


def _price_reverse_bet(legs: list[dict[str, Any]], max_risk: float) -> dict[str, Any]:
    normalized = _normalize_legs(legs)
    if len(normalized) < 2:
        return {}
    stake = max(0.0, float(max_risk or 100))
    chains = []
    combined_nets: list[float] = []
    for order in ((0, 1), (1, 0)):
        pair = [normalized[order[0]], normalized[order[1]]]
        chain_scenarios = _if_bet_scenarios(pair, stake)
        chain_nets = [float(s["net"]) for s in chain_scenarios]
        chains.append(
            {
                "direction": f"{pair[0]['selection']} → {pair[1]['selection']}",
                "scenarios": chain_scenarios,
                "max_win": round(max(chain_nets), 2),
                "max_loss": round(min(chain_nets), 2),
            }
        )
    # Combined result per outcome path: both chains settle on the same
    # leg outcomes, so net = chain A→B net + chain B→A net per scenario.
    if len(chains) == 2 and len(chains[0]["scenarios"]) == len(chains[1]["scenarios"]):
        combined_nets = [
            float(a["net"]) + float(b["net"])
            for a, b in zip(chains[0]["scenarios"], chains[1]["scenarios"], strict=True)
        ]
    else:  # pragma: no cover - defensive
        combined_nets = [float(s["net"]) for chain in chains for s in chain["scenarios"]]
    return {
        "bet_type": "reverse",
        "leg_count": len(normalized),
        "stake_per_chain": round(stake, 2),
        "total_risk": round(stake * 2, 2),
        "chains": chains,
        "scenarios": chains,
        "max_win": round(max(combined_nets), 2),
        "max_loss": round(min(combined_nets), 2),
        "source": "sports_derivatives",
    }


# ── Round robin ────────────────────────────────────────────────────────
def price_round_robin(
    legs: list[dict[str, Any]], parlay_size: int = 2, max_risk: float = 100
) -> dict[str, Any]:
    """Price a round robin (all combinations of N legs from the selection).

    Args:
        legs: Leg dicts; every combination of ``parlay_size`` legs is priced.
        parlay_size: Legs per parlay (default 2).
        max_risk: Total budget, split equally across the parlays (default 100).

    Returns:
        Dict with ``num_parlays``, ``total_risk``, ``max_win``, ``min_win``
        and ``all_combinations`` — or ``{}`` when fewer than ``parlay_size``
        valid legs remain. Never raises.
    """
    try:
        return _price_round_robin(legs, parlay_size, max_risk)
    except Exception:
        logger.exception("sports_round_robin_price_crashed")
        return {}


def _price_round_robin(
    legs: list[dict[str, Any]], parlay_size: int, max_risk: float
) -> dict[str, Any]:
    normalized = _normalize_legs(legs)
    size = max(2, int(parlay_size or 2))
    if len(normalized) < size:
        return {}
    combos = list(itertools.combinations(normalized, size))
    num_parlays = len(combos)
    budget = max(0.0, float(max_risk or 100))
    stake = round(budget / num_parlays, 2) if num_parlays else 0.0
    combinations: list[dict[str, Any]] = []
    profits: list[float] = []
    for combo in combos:
        decimal = parlay_decimal([float(leg["decimal_odds"]) for leg in combo])
        profit = round(stake * (decimal - 1.0), 2)
        profits.append(profit)
        combinations.append(
            {
                "legs": [str(leg["selection"]) for leg in combo],
                "combined_odds": {"decimal": decimal, "american": decimal_to_american(decimal)},
                "stake": stake,
                "profit": profit,
            }
        )
    # min_win = profit if exactly the worst single parlay wins (all others lose)
    min_win = min(profits) if profits else 0.0
    return {
        "bet_type": "round_robin",
        "parlay_size": size,
        "leg_count": len(normalized),
        "num_parlays": num_parlays,
        "stake_per_parlay": stake,
        "total_risk": round(stake * num_parlays, 2),
        "max_win": round(sum(profits), 2),
        "min_win": round(min_win, 2),
        "all_combinations": combinations,
        "source": "sports_derivatives",
    }
