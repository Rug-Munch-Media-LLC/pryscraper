# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Fail-closed gate tests for x402 route classification.

Guarantees enforced here:
1. Every operation referenced by PAID_ENDPOINTS exists in X402_PRICING.
2. Every route registered on the real app is explicitly classified.
3. A paid prefix whose pricing entry is missing FAILS CLOSED (500),
   never silently serves the endpoint for free.
4. Wildcard free prefixes actually match (the old exact-match check made
   "/mcp/messages/*" dead config).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

import x402_middleware
from x402 import X402_PRICING
from x402_middleware import (
    DEFAULT_FREE_PATHS,
    DEFAULT_FREE_PREFIXES,
    PAID_ENDPOINTS,
    X402Middleware,
    _admin_prefix,
    audit_route_classification,
    classify_path,
    iter_app_route_paths,
    resolve_operation,
)

if TYPE_CHECKING:
    import pytest


def _make_app() -> FastAPI:
    """Minimal app with one free, one paid, one wildcard-free route."""
    a = FastAPI()

    @a.get("/health")
    async def health() -> dict[str, bool]:
        return {"ok": True}

    @a.get("/v1/scrape")
    async def scrape() -> dict[str, bool]:
        return {"ok": True}

    @a.get("/mcp/messages/session-123")
    async def mcp_messages() -> dict[str, bool]:
        return {"ok": True}

    a.add_middleware(X402Middleware)
    return a


# ── Static configuration invariants ──────────────────────────────────────────


class TestPaidEndpointConfig:
    def test_every_paid_operation_has_pricing(self) -> None:
        """A paid prefix without a pricing entry would fail closed at runtime;
        this test catches it at CI time instead."""
        ops = set(PAID_ENDPOINTS.values())
        missing = ops - set(X402_PRICING)
        assert not missing, f"PAID_ENDPOINTS ops missing from X402_PRICING: {sorted(missing)}"

    def test_paid_endpoints_nonempty(self) -> None:
        assert len(PAID_ENDPOINTS) >= 50

    def test_default_free_paths_include_payment_flow(self) -> None:
        """The x402 payment endpoints themselves must never be gated."""
        for p in (
            "/v1/x402/pay",
            "/v1/x402/pricing",
            "/v1/x402/payment",
            "/v1/x402/batch-payment",
        ):
            assert p in DEFAULT_FREE_PATHS

    def test_specific_prefixes_precede_broad(self) -> None:
        """/v1/scrape/methods ($0.002 registry read) must win over /v1/scrape."""
        eps = list(PAID_ENDPOINTS)
        assert eps.index("/v1/scrape/methods") < eps.index("/v1/scrape")


class TestClassifyPath:
    def test_infra_paths_free(self) -> None:
        for p in ("/health", "/live", "/ready", "/metrics", "/openapi.json"):
            assert classify_path(p) == "free", p

    def test_paid_path(self) -> None:
        assert classify_path("/v1/scrape") == "paid"
        assert classify_path("/v1/crawl/example.com") == "paid"
        assert classify_path("/v1/sports/odds") == "paid"

    def test_wildcard_free_prefix(self) -> None:
        assert classify_path("/mcp/messages/abc") == "free"
        assert classify_path("/mcp/messages/") == "free"

    def test_admin_prefix_free(self) -> None:
        prefix = _admin_prefix()
        assert prefix.startswith("/")
        assert classify_path(f"{prefix}/v1/admin/profits") == "free"

    def test_unmatched_path_is_misconfigured(self) -> None:
        """Not free-listed and not paid-gated => misconfigured (audit failure)."""
        assert classify_path("/v9/never-classified") == "misconfigured"


class TestResolveOperation:
    def test_scrape_methods_more_specific_than_scrape(self) -> None:
        assert resolve_operation("/v1/scrape/methods") == "scrape_methods"
        assert resolve_operation("/v1/scrape") == "scrape"

    def test_no_match_returns_none(self) -> None:
        assert resolve_operation("/health") is None


# ── Runtime fail-closed behavior ─────────────────────────────────────────────


class TestRuntimeGate:
    def test_free_route_passes_through(self) -> None:
        client = TestClient(_make_app(), raise_server_exceptions=False)
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json() == {"ok": True}

    def test_paid_route_without_payment_is_402(self) -> None:
        client = TestClient(_make_app(), raise_server_exceptions=False)
        r = client.get("/v1/scrape")
        assert r.status_code == 402
        assert "payment-required" in {k.lower() for k, _ in r.headers.items()}

    def test_wildcard_free_route_reaches_app(self) -> None:
        """Regression: '/mcp/messages/*' was dead config under exact matching."""
        client = TestClient(_make_app(), raise_server_exceptions=False)
        r = client.get("/mcp/messages/session-123")
        assert r.status_code == 200
        assert r.json() == {"ok": True}

    def test_missing_pricing_fails_closed_500(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """THE money-leak regression test: paid prefix + missing pricing entry
        must return 500, never silently serve the endpoint free."""
        reduced = {k: v for k, v in X402_PRICING.items() if k != "scrape"}
        monkeypatch.setattr(x402_middleware, "X402_PRICING", reduced)
        client = TestClient(_make_app(), raise_server_exceptions=False)
        r = client.get("/v1/scrape")
        assert r.status_code == 500
        assert r.json()["error"] == "payment_gate_misconfigured"

    def test_options_preflight_never_gated(self) -> None:
        client = TestClient(_make_app(), raise_server_exceptions=False)
        r = client.options("/v1/scrape")
        assert r.status_code != 402


# ── Startup audit ────────────────────────────────────────────────────────────


class TestStartupAudit:
    def test_real_app_fully_classified(self) -> None:
        """Every route on the production app must be explicitly free or paid."""
        from api import app as real_app

        unclassified = audit_route_classification(real_app)
        assert unclassified == [], (
            f"Unclassified routes (add to DEFAULT_FREE_PATHS or PAID_ENDPOINTS): "
            f"{unclassified[:20]}"
        )

    def test_audit_detects_unclassified_synthetic_route(self) -> None:
        a = FastAPI()

        @a.get("/v9/oops")
        async def oops() -> dict[str, bool]:
            return {"ok": True}

        assert audit_route_classification(a) == ["/v9/oops"]

    def test_iter_app_route_paths_enumerates_included_routers(self) -> None:
        """FastAPI's lazy _IncludedRouter wrappers must not hide routes."""
        a = FastAPI()
        sub = FastAPI()

        @sub.get("/v9/hidden")
        async def hidden() -> dict[str, bool]:
            return {"ok": True}

        a.mount("/sub", sub)
        paths = set(iter_app_route_paths(a))
        assert any(p.startswith("/sub") for p in paths)

    def test_audit_clean_on_minimal_classified_app(self) -> None:
        paths = set(iter_app_route_paths(_make_app()))
        bad = {
            p
            for p in paths
            if p not in DEFAULT_FREE_PATHS
            and not any(p.startswith(x) for x in DEFAULT_FREE_PREFIXES)
            and resolve_operation(p) is None
        }
        # /v1/scrape resolves to a paid op; everything else is free-listed.
        assert bad == set()


# ── Middleware construction back-compat ──────────────────────────────────────


class TestConstruction:
    def test_defaults_use_module_constants(self) -> None:
        mw = X402Middleware(app=Any)
        assert mw.free_paths == DEFAULT_FREE_PATHS
        assert mw.free_prefixes == DEFAULT_FREE_PREFIXES

    def test_explicit_overrides_respected(self) -> None:
        mw = X402Middleware(app=Any, free_paths=["/only"], free_prefixes=["/pre/"])
        assert mw.free_paths == frozenset({"/only"})
        assert mw.free_prefixes == ("/pre/",)
