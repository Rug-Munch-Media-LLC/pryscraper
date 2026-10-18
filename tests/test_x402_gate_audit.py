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

import pry.payments.x402_middleware as x402_middleware
from pry.payments.x402 import X402_PRICING
from pry.payments.x402_middleware import (
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
        # Exact size: a dropped paid prefix silently un-gates revenue paths.
        assert len(PAID_ENDPOINTS) == 54

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
        with TestClient(_make_app(), raise_server_exceptions=False) as client:
            r = client.get("/health")
            assert r.status_code == 200
            expected = {"ok": True}
            assert r.json() == expected

    def test_paid_route_without_payment_is_402(self) -> None:
        with TestClient(_make_app(), raise_server_exceptions=False) as client:
            r = client.get("/v1/scrape")
            assert r.status_code == 402
            assert "payment-required" in {k.lower() for k, _ in r.headers.items()}

    def test_wildcard_free_route_reaches_app(self) -> None:
        """Regression: '/mcp/messages/*' was dead config under exact matching."""
        with TestClient(_make_app(), raise_server_exceptions=False) as client:
            r = client.get("/mcp/messages/session-123")
            assert r.status_code == 200
            expected = {"ok": True}
            assert r.json() == expected

    def test_missing_pricing_fails_closed_500(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """THE money-leak regression test: paid prefix + missing pricing entry
        must return 500, never silently serve the endpoint free."""
        reduced = {k: v for k, v in X402_PRICING.items() if k != "scrape"}
        # Patch the AUTHORITATIVE table (config module) — classification reads
        # X402_PRICING through that namespace since the E41 module split.
        monkeypatch.setattr(x402_middleware.config, "X402_PRICING", reduced)
        with TestClient(_make_app(), raise_server_exceptions=False) as client:
            r = client.get("/v1/scrape")
            assert r.status_code == 500
            assert r.json()["error"] == "payment_gate_misconfigured"

    def test_options_preflight_never_gated(self) -> None:
        with TestClient(_make_app(), raise_server_exceptions=False) as client:
            r = client.options("/v1/scrape")
            assert r.status_code != 402


# ── Startup audit ────────────────────────────────────────────────────────────


class TestStartupAudit:
    def test_real_app_fully_classified(self) -> None:
        """Every route on the production app must be explicitly free or paid."""
        from pry.api.api import app as real_app

        # Positive control: 392 routes really are being walked.
        assert len(list(iter_app_route_paths(real_app))) >= 392
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

        expected = ["/v9/oops"]
        assert audit_route_classification(a) == expected

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
        expected = ("/pre/",)
        assert mw.free_prefixes == expected


class TestPrefixOrderingInvariant:
    """No PAID_ENDPOINTS prefix may be shadowed by an earlier broader one.

    First-match-wins means a broad prefix listed before a more specific one
    silently hijacks the specific route's operation. Harmless only while the
    ops are identical — a landmine the moment anyone gives the specific
    route its own price (e.g. adaptive crawling).
    """

    def test_no_prefix_shadows_a_later_more_specific_prefix(self) -> None:
        entries = list(PAID_ENDPOINTS.items())
        violations = []
        for i, (broad, _op_broad) in enumerate(entries):
            for specific, _op_specific in entries[i + 1 :]:
                if specific != broad and specific.startswith(broad):
                    violations.append(f"{broad} (earlier) shadows {specific}")
        assert not violations, (
            "Reorder PAID_ENDPOINTS so specific prefixes come first: " + "; ".join(violations)
        )


class TestX402Catalog:
    """The /v1/x402/catalog endpoint binds operations + engines + actors."""

    def test_catalog_is_free_and_complete(self, client: TestClient) -> None:
        r = client.get("/v1/x402/catalog")
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["actor_count"] >= 90, "all actor presets must be catalogued"
        assert len(data["operations"]) >= 60
        assert len(data["paid_endpoints"]) >= 50
        for actor in data["actors"][:5]:
            assert actor["mcp_tool"].startswith("pry_")
            assert actor["engine"]

    def test_every_actor_maps_to_an_mcp_tool(self, client: TestClient) -> None:
        data = client.get("/v1/x402/catalog").json()["data"]
        tools = {a["mcp_tool"] for a in data["actors"]}
        unknown = {t for t in tools if not t.startswith("pry_")}
        assert not unknown, f"non-pry tool names leaked into catalog: {unknown}"


class TestKeylessX402Flow:
    """x402's promise: no accounts, no API keys. A keyless agent must
    reach the 402 challenge (auth layer is INNER to the payment gate)."""

    def test_keyless_paid_request_gets_402_not_401(self) -> None:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from pry.core.middleware import PryHttpMiddleware
        from pry.payments.x402_middleware import X402Middleware

        app = FastAPI()

        @app.post("/v1/scrape")
        async def scrape():
            return {"ok": True}

        app.add_middleware(PryHttpMiddleware)
        app.add_middleware(X402Middleware)  # outermost
        c = TestClient(app, raise_server_exceptions=False)
        with c:
            r = c.post("/v1/scrape", json={"url": "https://example.com"})
            assert r.status_code == 402, f"expected 402 challenge, got {r.status_code}"
            assert "payment-required" in {k.lower() for k in r.headers}

    def test_pricing_and_catalog_are_keyless(self) -> None:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from pry.api.routers.commerce.x402 import router as x402_router
        from pry.core.middleware import PryHttpMiddleware

        app = FastAPI()
        app.include_router(x402_router)
        app.add_middleware(PryHttpMiddleware)
        c = TestClient(app)
        with c:
            for path in ("/v1/x402/pricing", "/v1/x402/catalog"):
                r = c.get(path)
                assert r.status_code == 200, f"{path} must be keyless-discoverable"
