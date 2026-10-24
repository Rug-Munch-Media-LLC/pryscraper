"""Risk scoring for KOL accounts — weighted, monotonic, explainable.

Every component is a 0..1 rate; the score is ``sum(weight * rate)`` clamped to
100. Weights are declared in :data:`WEIGHTS` so a reviewer can audit the model
instead of reverse-engineering it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable

WEIGHTS: dict[str, float] = {
    "shill_frequency": 20.0,  # share of sampled posts that are promo
    "contract_share": 20.0,  # share of posts carrying a token contract
    "lowcap_concentration": 15.0,  # share of promos with mcap below threshold
    "undisclosed_promo": 15.0,  # promo without #ad / sponsored marker
    "rugged_promo_rate": 15.0,  # promoted tokens that failed our scan
    "deleted_post_rate": 10.0,  # posts that vanished after promotion
    "engagement_anomaly": 5.0,  # follower:engagement ratio off the norm
}

LOWCAP_USD = 1_000_000.0


@dataclass
class RiskInputs:
    posts_sampled: int = 0
    promo_posts: int = 0
    posts_with_contract: int = 0
    promos_lowcap: int = 0
    promos_total: int = 0
    promos_flagged_rug: int = 0
    posts_deleted: int = 0
    followers: int = 0
    median_engagement: float = 0.0
    discloses_promos: bool = False


def _rate(numerator: float, denominator: float) -> float:
    if denominator <= 0 or numerator <= 0:
        return 0.0
    return min(1.0, float(numerator) / float(denominator))


def _engagement_anomaly(inputs: RiskInputs) -> float:
    """Follow-to-engagement ratio far outside the ~1:100 norm scores high."""
    if inputs.followers <= 0 or inputs.median_engagement <= 0:
        return 0.0
    ratio = inputs.followers / inputs.median_engagement
    if ratio <= 100:
        return 0.0
    return min(1.0, (ratio - 100) / 1900)  # 1:2000+ saturates


def compute_signals(inputs: RiskInputs) -> dict[str, float]:
    """Raw 0..1 components, before weighting."""
    promo_share = _rate(inputs.promo_posts, inputs.posts_sampled)
    undisclosed = promo_share if (promo_share and not inputs.discloses_promos) else 0.0
    return {
        "shill_frequency": promo_share,
        "contract_share": _rate(inputs.posts_with_contract, inputs.posts_sampled),
        "lowcap_concentration": _rate(inputs.promos_lowcap, inputs.promos_total),
        "undisclosed_promo": undisclosed,
        "rugged_promo_rate": _rate(inputs.promos_flagged_rug, max(inputs.promos_total, 1)),
        "deleted_post_rate": _rate(inputs.posts_deleted, inputs.posts_sampled),
        "engagement_anomaly": _engagement_anomaly(inputs),
    }


def score_risk(inputs: RiskInputs) -> tuple[float, dict[str, float], list[str]]:
    """Return ``(score, signals, reasons)`` where reasons explain the top drivers."""
    signals = compute_signals(inputs)
    score = min(100.0, sum(WEIGHTS[name] * value for name, value in signals.items()))
    reasons = [
        f"{name}={value:.2f} -> {WEIGHTS[name] * value:.1f}pts"
        for name, value in sorted(
            signals.items(), key=lambda kv: kv[1] * WEIGHTS[kv[0]], reverse=True
        )
        if value > 0
    ]
    return round(score, 2), signals, reasons


def band(score: float) -> str:
    """Coarse label used by the report."""
    if score >= 75:
        return "critical"
    if score >= 50:
        return "high"
    if score >= 25:
        return "medium"
    return "low"


def scan_summary(scan_results: Iterable[dict[str, Any]]) -> dict[str, int]:
    """Fold ``rugmunch-data``-style scan rows into promo counters."""
    rows = list(scan_results)
    rugged = sum(
        1 for row in rows if str(row.get("risk", "")).lower() in {"high", "critical", "rug"}
    )
    lowcap = sum(1 for row in rows if float(row.get("market_cap_usd") or 0) < LOWCAP_USD)
    return {"promos_total": len(rows), "promos_flagged_rug": rugged, "promos_lowcap": lowcap}
