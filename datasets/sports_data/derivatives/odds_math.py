"""Odds conversion and parlay math for sports derivatives."""

from __future__ import annotations


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


def effective_decimal(max_win: float, stake: float) -> float:
    """Decimal odds implied by a max win on a given stake (1.0 when no win)."""
    if stake <= 0 or max_win <= 0:
        return 1.0
    return round(1.0 + max_win / stake, 6)
