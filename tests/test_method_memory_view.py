"""Tests for the method-memory READ surface (method_memory_view + route).

Synthetic records only — no live scraping. The global resilience registry is
reset per test so the plan is derived purely from what each test records.
"""

from __future__ import annotations

import time
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from pry.api.routers.core.diagnostics import router as diagnostics_router
from pry.engine.method_memory_view import (
    COLD_START_REASON,
    domain_method_plan,
    explain_top_pick,
)
from pry.engine.resilience import TierRecord, registry
from pry.payments.x402_middleware.classification import classify_path

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
        assert set(plan) == {
            "domain",
            "tiers",
            "top_pick",
            "reason",
            "cold_start",
            "generated_at",
        }
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
        assert ranks == [1, 2, 3]

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
        assert {entry["tier"] for entry in plan["tiers"]} == {"direct", "tor"}
        assert all(entry["success_rate"] == 0.0 for entry in plan["tiers"])


class TestExplainTopPick:
    """The reason helper in isolation."""

    def test_none_for_no_tiers(self) -> None:
        assert explain_top_pick(DOMAIN, []) == COLD_START_REASON

    def test_unknown_cost_is_flagged_not_priced(self) -> None:
        entry = {
            "tier": "premium_proxy",
            "samples": 2,
            "success_rate": 1.0,
            "latency_per_success_ms": 1500.0,
            "cost_usd": 0.0,
            "cost_known": False,
            "last_block_kind": None,
        }
        reason = explain_top_pick(DOMAIN, [entry])
        assert "unconfigured" in reason
        assert "No recorded block" in reason
        # The passed entry is not mutated by explanation.
        assert entry == {
            "tier": "premium_proxy",
            "samples": 2,
            "success_rate": 1.0,
            "latency_per_success_ms": 1500.0,
            "cost_usd": 0.0,
            "cost_known": False,
            "last_block_kind": None,
        }


class TestRoute:
    """The HTTP surface: registered, free, and returning the plan."""

    def test_route_registered_on_the_router(self) -> None:
        paths = {
            getattr(route, "path", None): getattr(route, "methods", None)
            for route in diagnostics_router.routes
        }
        assert paths["/v1/diagnostics/method-plan"] == {"GET"}

    def test_classified_free_not_x402_paid(self) -> None:
        assert classify_path("/v1/diagnostics/method-plan") == "free"

    def test_endpoint_returns_the_plan(self) -> None:
        _record(DOMAIN, "flaresolverr", 3, 0, latency=400.0)

        app = FastAPI()
        app.include_router(diagnostics_router)
        with TestClient(app) as client:
            response = client.get("/v1/diagnostics/method-plan", params={"domain": DOMAIN})

        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        assert body["data"]["top_pick"] == "flaresolverr"
        assert body["data"]["tiers"][0]["samples"] == 3

    def test_endpoint_cold_start_is_not_an_error(self) -> None:
        app = FastAPI()
        app.include_router(diagnostics_router)
        with TestClient(app) as client:
            response = client.get(
                "/v1/diagnostics/method-plan", params={"domain": "unknown.example"}
            )

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["tiers"] == []
        assert data["top_pick"] is None
        assert data["cold_start"] is True

    def test_domain_is_required(self) -> None:
        app = FastAPI()
        app.include_router(diagnostics_router)
        with TestClient(app) as client:
            assert client.get("/v1/diagnostics/method-plan").status_code == 422

    def test_generated_at_uses_the_supplied_clock(self) -> None:
        _record(DOMAIN, "direct", 1)
        assert domain_method_plan(DOMAIN, now=1234.0)["generated_at"] == 1234.0
        assert domain_method_plan(DOMAIN)["generated_at"] <= time.time()
