# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for the site capability catalog (assured-scrape registry).

Covers catalog integrity (unique site_ids, method vocabulary, confidence and
enum ranges, 12 data domains, size), ``SiteCatalog`` lookups
(``coverage()`` / ``get_site()`` / ``recommend_method()`` including the
generic fallback), and the /v1/coverage router (200 / 404 / 422 / 502).

No live network — the router is exercised via TestClient against a bare app.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from pry.api.routers.data.site_catalog import router as site_catalog_router
from pry.core.errors import PryError
from site_catalog import (
    ANTI_BOT_LEVELS,
    CATALOG,
    DATA_DOMAINS,
    GENERIC_FALLBACK,
    METHOD_VOCABULARY,
    ROBOTS_STATES,
    SiteCatalog,
)

REQUIRED_KEYS = (
    "site_id",
    "domain",
    "method",
    "confidence",
    "anti_bot",
    "robots",
    "latency_ms_estimate",
    "output_schema",
    "requires_key",
    "data_domain",
)


# ── catalog integrity ──────────────────────────────────────────────────


def test_catalog_size_within_target() -> None:
    assert 40 <= len(CATALOG) <= 60, f"catalog has {len(CATALOG)} entries (target 40-60)"


def test_site_ids_unique() -> None:
    ids = [e["site_id"] for e in CATALOG]
    assert len(ids) == len(set(ids)), "duplicate site_id in catalog"


def test_entries_have_all_required_keys() -> None:
    for entry in CATALOG:
        assert set(REQUIRED_KEYS) <= set(entry), f"missing keys in {entry.get('site_id')}"


def test_method_tokens_in_vocabulary() -> None:
    for entry in CATALOG:
        for token in entry["method"].split("+"):
            assert token in METHOD_VOCABULARY, (
                f"{entry['site_id']}: {token!r} not in {sorted(METHOD_VOCABULARY)}"
            )


def test_confidence_within_range() -> None:
    for entry in CATALOG:
        assert 0.0 <= entry["confidence"] <= 1.0, f"{entry['site_id']} confidence out of range"


def test_anti_bot_levels_valid() -> None:
    for entry in CATALOG:
        assert entry["anti_bot"] in ANTI_BOT_LEVELS, f"{entry['site_id']} bad anti_bot"


def test_robots_states_valid() -> None:
    for entry in CATALOG:
        assert entry["robots"] in ROBOTS_STATES, f"{entry['site_id']} bad robots"


def test_latency_non_negative() -> None:
    for entry in CATALOG:
        assert entry["latency_ms_estimate"] >= 0, f"{entry['site_id']} negative latency"


def test_requires_key_is_bool() -> None:
    for entry in CATALOG:
        assert isinstance(entry["requires_key"], bool), f"{entry['site_id']} requires_key not bool"


def test_output_schema_non_empty() -> None:
    for entry in CATALOG:
        assert entry["output_schema"], f"{entry['site_id']} empty output_schema"
        assert all(isinstance(k, str) for k in entry["output_schema"])


def test_all_data_domains_covered() -> None:
    covered = {e["data_domain"] for e in CATALOG}
    assert covered == set(DATA_DOMAINS), f"missing domains: {sorted(set(DATA_DOMAINS) - covered)}"


def test_catalog_constructs_without_error() -> None:
    catalog = SiteCatalog()
    assert len(catalog) == len(CATALOG)


# ── registry lookups ───────────────────────────────────────────────────


def test_coverage_matches_catalog() -> None:
    catalog = SiteCatalog()
    assert catalog.coverage() == CATALOG


def test_get_site_found() -> None:
    catalog = SiteCatalog()
    entry = catalog.get_site("zillow")
    assert entry is not None
    assert entry["method"] == "next_data"
    assert entry["data_domain"] == "real-estate"


def test_get_site_missing_returns_none() -> None:
    catalog = SiteCatalog()
    assert catalog.get_site("definitely-not-a-site") is None


@pytest.mark.parametrize(
    ("target", "expected_id", "expected_method"),
    [
        ("https://www.amazon.com/dp/B0TEST123", "amazon", "stealth+next_data"),
        ("zillow.com", "zillow", "next_data"),
        ("https://boards-api.greenhouse.io", "greenhouse", "api"),
        ("https://www.google.com/travel/flights?hl=en", "google_flights", "embedded_json"),
        ("www.courtlistener.com", "courtlistener", "api"),
        ("https://api.sam.gov/opportunities/v2/search", "sam_gov", "api"),
        ("https://www.google.com/maps/search/coffee", "google_maps", "embedded_json"),
        ("api.gopluslabs.io", "goplus", "api"),
        ("https://www.tiktok.com/shop/pdp/render/123", "tiktok_shop", "embedded_json+signed"),
    ],
)
def test_recommend_known_domain(target: str, expected_id: str, expected_method: str) -> None:
    catalog = SiteCatalog()
    rec = catalog.recommend_method(target)
    assert rec["site_id"] == expected_id
    assert rec["method"] == expected_method
    assert 0.0 <= rec["confidence"] <= 1.0


def test_recommend_unknown_domain_returns_generic() -> None:
    catalog = SiteCatalog()
    rec = catalog.recommend_method("https://unknown-site.example.com/page")
    assert rec == GENERIC_FALLBACK


def test_recommend_empty_target_returns_generic() -> None:
    catalog = SiteCatalog()
    assert catalog.recommend_method("") == GENERIC_FALLBACK
    assert catalog.recommend_method("   ") == GENERIC_FALLBACK


def test_recommend_by_site_id() -> None:
    catalog = SiteCatalog()
    rec = catalog.recommend_method("sam_gov")
    assert rec["site_id"] == "sam_gov"
    assert rec["requires_key"] is True


# ── router ─────────────────────────────────────────────────────────────


@pytest.fixture
def catalog_app() -> FastAPI:
    app = FastAPI()

    @app.exception_handler(PryError)
    async def pry_error_handler(request: Request, exc: PryError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": str(exc)})

    app.include_router(site_catalog_router)
    return app


def _client(app: FastAPI) -> TestClient:
    return TestClient(app)


def test_router_importable() -> None:
    from pry.api.routers import site_catalog as site_catalog_mod

    assert hasattr(site_catalog_mod, "router")
    assert site_catalog_mod.router is site_catalog_router


def test_router_coverage_endpoint(catalog_app: FastAPI) -> None:
    resp = _client(catalog_app).get("/v1/coverage")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["total"] == len(CATALOG)
    assert len(body["data"]) == len(CATALOG)
    methods = {e["method"] for e in body["data"]}
    assert "api" in methods
    assert "next_data" in methods
    assert "embedded_json" in methods


def test_router_get_site_endpoint(catalog_app: FastAPI) -> None:
    resp = _client(catalog_app).get("/v1/coverage/zillow")
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["method"] == "next_data"
    assert body["data"]["confidence"] == 0.6
    assert "output_schema" in body["data"]
    assert body["data"]["data_domain"] == "real-estate"


def test_router_get_site_endpoint_missing(catalog_app: FastAPI) -> None:
    resp = _client(catalog_app).get("/v1/coverage/not-a-real-site")
    assert resp.status_code == 404


def test_router_recommend_endpoint_known(catalog_app: FastAPI) -> None:
    resp = _client(catalog_app).get(
        "/v1/coverage/recommend", params={"url": "https://www.zillow.com/homedetails/123"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["method"] == "next_data"
    assert body["data"]["confidence"] == 0.6


def test_router_recommend_endpoint_unknown(catalog_app: FastAPI) -> None:
    resp = _client(catalog_app).get(
        "/v1/coverage/recommend", params={"url": "https://mystery.example.com"}
    )
    assert resp.status_code == 200
    assert resp.json()["data"] == GENERIC_FALLBACK


def test_router_recommend_missing_url_422(catalog_app: FastAPI) -> None:
    resp = _client(catalog_app).get("/v1/coverage/recommend")
    assert resp.status_code == 422


def test_router_502_when_catalog_unavailable(
    catalog_app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("pry.api.routers.data.site_catalog._catalog", lambda: None)
    resp = _client(catalog_app).get("/v1/coverage")
    assert resp.status_code == 502
