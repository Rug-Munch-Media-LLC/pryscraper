"""Tests for the method-memory READ surface (method_memory_view + route).

Synthetic records only — no live scraping. The global resilience registry is
reset per test so the plan is derived purely from what each test records.
"""

from __future__ import annotations

from typing import Any

import pytest

from pry.engine.method_memory_view import (
    COLD_START_REASON,
    domain_method_plan,
)
from pry.engine.resilience import TierRecord, registry

DOMAIN = "example.com"

_TIER_KEYS = {
    "tier",
    "rank",
    "samples",
    "successes",
    "failures",
    "success_rate",
    "smoothed_success_rate",
    "latency_per_success_ms",
    "cost_usd",
    "cost_known",
    "last_block_kind",
    "last_success_at",
    "last_failure_at",
    "score",
}


@pytest.fixture(autouse=True)
def _clean_memory() -> Any:
    """Hermetic state per test: no persisted file writes, empty memory."""
    registry.disable_persistence()
    registry.domain_memory.data.clear()
    yield
    registry.domain_memory.data.clear()


def _record(
    domain: str,
    tier: str,
    successes: int,
    failures: int = 0,
    *,
    latency: float = 100.0,
    cost_usd: float = 0.0,
    block_kind: str = "",
) -> None:
    """Seed one tier's counters.

    Latency AND cost are charged on every attempt, including failures: a
    premium-proxy request that walks into a Cloudflare wall was still paid
    for, which is exactly the case the cost-aware ranking exists to catch.
    """
    for _ in range(successes):
        registry.domain_memory.record(domain, tier, True, latency, cost_usd=cost_usd)
    for _ in range(failures):
        registry.domain_memory.record(
            domain, tier, False, latency, cost_usd=cost_usd, block_kind=block_kind
        )


def _plan(domain: str = DOMAIN) -> dict[str, Any]:
    return domain_method_plan(domain)


class TestPlanShape:
    """The payload contract an agent reads."""

    def test_top_level_keys(self) -> None:
        _record(DOMAIN, "direct", 3)

        plan = _plan()
        expected = {
            "domain",
            "tiers",
            "top_pick",
            "reason",
            "cold_start",
            "generated_at",
        }
        assert set(plan) == expected
        assert plan["domain"] == DOMAIN
        assert plan["cold_start"] is False
        assert isinstance(plan["generated_at"], float)

    def test_tier_entry_shape(self) -> None:
        _record(DOMAIN, "playwright", 2, 1, latency=250.0, cost_usd=0.002, block_kind="cloudflare")

        plan = _plan()
        assert len(plan["tiers"]) == 1
        top = plan["tiers"][0]
        assert set(top) == _TIER_KEYS
        assert top["tier"] == "playwright"
        assert top["rank"] == 1
        assert top["samples"] == 3
        assert top["successes"] == 2
        assert top["failures"] == 1
        assert top["success_rate"] == pytest.approx(0.6667, abs=1e-4)
        # Raw rate is honest; the ranking's smoothed view is reported beside it.
        assert top["smoothed_success_rate"] == pytest.approx(0.5714, abs=1e-4)
        assert top["latency_per_success_ms"] == 375.0
        assert top["cost_usd"] == pytest.approx(0.006)
        assert top["cost_known"] is True
        assert top["last_block_kind"] == "cloudflare"
        assert top["last_success_at"] is not None
        assert top["last_failure_at"] is not None

    def test_ranks_are_dense_and_one_based(self) -> None:
        _record(DOMAIN, "direct", 5)
        _record(DOMAIN, "tor", 4)
        _record(DOMAIN, "playwright", 3)

        ranks = [entry["rank"] for entry in _plan()["tiers"]]
        expected = [1, 2, 3]
        assert ranks == expected

    def test_best_proven_tier_is_the_top_pick(self) -> None:
        _record(DOMAIN, "direct", 1, 9)
        _record(DOMAIN, "camoufox", 8, 0, latency=900.0)

        plan = _plan()
        assert plan["top_pick"] == "camoufox"
        assert plan["tiers"][0]["tier"] == "camoufox"

    def test_reason_is_plain_language_about_the_top_pick(self) -> None:
        _record(DOMAIN, "direct", 1, 4, block_kind="cloudflare")
        _record(DOMAIN, "cloudscraper", 6, 0, latency=120.0)

        reason = _plan()["reason"]
        assert reason.startswith(f"Try cloudscraper first for {DOMAIN}:")
        assert "6 samples" in reason
        assert "100.0% success" in reason
        assert "120ms average latency" in reason


class TestColdStart:
    """No history must not become a fabricated ordering."""

    def test_unknown_domain_fabricates_nothing(self) -> None:
        _record("other.example", "direct", 3)

        plan = _plan("never-seen.example")
        assert plan["domain"] == "never-seen.example"
        assert plan["tiers"] == []
        assert plan["top_pick"] is None
        assert plan["cold_start"] is True
        assert plan["reason"] == COLD_START_REASON

    def test_empty_domain_fabricates_nothing(self) -> None:
        plan = domain_method_plan("")
        assert plan["tiers"] == []
        assert plan["top_pick"] is None
        assert plan["cold_start"] is True
        assert plan["reason"] == COLD_START_REASON

    def test_tier_with_no_samples_reports_zeroes_not_a_rate(self) -> None:
        registry.domain_memory.data[DOMAIN]["direct"] = TierRecord()

        top = _plan()["tiers"][0]
        assert top["samples"] == 0
        assert top["success_rate"] == 0.0
        # Uninformative prior — reported as such, not as a real observation.
        assert top["smoothed_success_rate"] == 0.5
        assert top["latency_per_success_ms"] == 0.0
        assert top["cost_usd"] == 0.0
        assert top["last_block_kind"] is None
        assert top["last_success_at"] is None
        assert top["last_failure_at"] is None

    def test_all_failed_domain_still_reports_the_ladder_not_nothing(self) -> None:
        _record(DOMAIN, "direct", 0, 5, block_kind="access_denied")
        _record(DOMAIN, "tor", 0, 4)

        plan = _plan()
        assert plan["cold_start"] is False
        expected = {"direct", "tor"}
        assert {entry["tier"] for entry in plan["tiers"]} == expected
        assert all(entry["success_rate"] == 0.0 for entry in plan["tiers"])
