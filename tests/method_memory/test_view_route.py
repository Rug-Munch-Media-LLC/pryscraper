"""Route + explain tests for the method-memory read surface.

Synthetic records only — no live scraping.
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
from pry.engine.resilience import registry
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
