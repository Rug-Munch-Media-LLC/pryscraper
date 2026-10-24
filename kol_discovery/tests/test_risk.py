"""Risk scoring: weighted, monotonic, explainable."""

from __future__ import annotations

from kol_discovery.risk import (
    WEIGHTS,
    RiskInputs,
    band,
    compute_signals,
    scan_summary,
    score_risk,
)


def test_weights_sum_to_one_hundred() -> None:
    assert sum(WEIGHTS.values()) == 100.0


def test_no_observations_scores_zero() -> None:
    score, signals, reasons = score_risk(RiskInputs())
    assert score == 0.0
    assert set(signals.values()) == {0.0}
    assert reasons == []


def test_all_signals_saturated_scores_one_hundred() -> None:
    inputs = RiskInputs(
        posts_sampled=10,
        promo_posts=10,
        posts_with_contract=10,
        promos_total=10,
        promos_lowcap=10,
        promos_flagged_rug=10,
        posts_deleted=10,
        followers=100_000,
        median_engagement=1.0,
        discloses_promos=False,
    )
    score, signals, reasons = score_risk(inputs)
    assert score == 100.0
    assert signals["shill_frequency"] == 1.0
    assert reasons[0].startswith("shill_frequency")


def test_disclosure_reduces_score_without_changing_other_signals() -> None:
    base = {"posts_sampled": 10, "promo_posts": 5, "promos_total": 5, "posts_with_contract": 2}
    loud, _, _ = score_risk(RiskInputs(**base, discloses_promos=False))
    quiet, signals, _ = score_risk(RiskInputs(**base, discloses_promos=True))
    assert quiet < loud
    assert signals["undisclosed_promo"] == 0.0
    assert signals["shill_frequency"] == 0.5


def test_score_is_monotonic_in_rugged_promos() -> None:
    def score(rugged: int) -> float:
        return score_risk(
            RiskInputs(posts_sampled=20, promo_posts=10, promos_total=10, promos_flagged_rug=rugged)
        )[0]

    assert score(0) < score(5) < score(10)


def test_engagement_anomaly_only_fires_past_the_norm() -> None:
    normal = compute_signals(RiskInputs(followers=10_000, median_engagement=100.0))
    skewed = compute_signals(RiskInputs(followers=100_000, median_engagement=1.0))
    assert normal["engagement_anomaly"] == 0.0
    assert skewed["engagement_anomaly"] > 0.9


def test_band_boundaries() -> None:
    assert [band(s) for s in (0, 24.9, 25, 49.9, 50, 74.9, 75, 100)] == [
        "low",
        "low",
        "medium",
        "medium",
        "high",
        "high",
        "critical",
        "critical",
    ]


def test_scan_summary_folds_rugmunch_rows() -> None:
    rows = [
        {"risk": "high", "market_cap_usd": 250_000},
        {"risk": "low", "market_cap_usd": 9_000_000},
        {"risk": "critical", "market_cap_usd": 40_000},
    ]
    assert scan_summary(rows) == {
        "promos_total": 3,
        "promos_flagged_rug": 2,
        "promos_lowcap": 2,
    }
