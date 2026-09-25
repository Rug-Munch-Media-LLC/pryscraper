"""Leg normalization helpers for sports derivatives."""

from __future__ import annotations

from typing import Any

from .odds_math import american_to_decimal, decimal_to_american

_ADJUSTABLE = frozenset(
    {"spread", "spreads", "total", "totals", "ou", "alternate_spread", "alternate_total"}
)


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
    normalized = {
        "index": index,
        "selection": selection,
        "type": leg_type,
        "odds": american,
        "decimal_odds": decimal,
        "implied_prob": round(1.0 / decimal, 6),
        "adjustable": leg_type in _ADJUSTABLE,
    }
    if leg.get("line") is not None:
        normalized["line"] = leg["line"]
    return normalized


def _normalize_legs(legs: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Normalize a leg list, dropping invalid entries."""
    normalized: list[dict[str, Any]] = []
    for index, leg in enumerate(legs or []):
        norm = _normalize_leg(leg, index)
        if norm is not None:
            normalized.append(norm)
    return normalized
