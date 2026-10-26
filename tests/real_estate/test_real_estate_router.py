"""Tests for the real_estate package (listings + property records).

Covers Zillow ``__NEXT_DATA__`` listing-page parsing, Zillow SRP search
parsing, the Redfin GIS search fallback and Redfin home-detail fallback,
county ArcGIS property-record queries, the never-raise contract (HTTP
errors / rate limits / bad HTML / bad JSON all degrade to ``{}`` / ``[]``),
robots.txt policy (advisory vs ``PRY_REAL_ESTATE_ENFORCE_ROBOTS=1``), and
the /v1/realestate/* router (200 + 502-degradation + query validation).

All HTTP is mocked with respx (local-router ``respx_mock`` — the version
of this venv attaches routes to the local router only) — no live network.
"""

from typing import Any

import pytest
from fastapi import FastAPI

import datasets.real_estate as real_estate
import pry.api.routers.data.real_estate as real_estate_router_mod
from tests.real_estate._real_estate_support import _hermetic_real_estate  # noqa: F401
from tests.real_estate._real_estate_support2 import _client


def test_router_importable() -> None:
    import datasets.real_estate as re_pkg
    import pry.api.routers.data.real_estate as re_router

    expected = ["get_listing", "get_property", "search_listings"]
    assert re_pkg.__all__ == expected
    assert hasattr(re_router, "router")


def test_router_listing_success(real_estate_app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_get_listing(zillow_id: str) -> dict[str, Any]:
        return {"address": "123 Main St", "price": 450000, "zillow_id": zillow_id}

    monkeypatch.setattr(real_estate, "get_listing", fake_get_listing)
    resp = _client(real_estate_app).get("/v1/realestate/listing/2064710495")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["data"]["price"] == 450000
    assert body["data"]["zillow_id"] == "2064710495"


def test_router_listing_empty_data_success_false(
    real_estate_app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_get_listing(zillow_id: str) -> dict[str, Any]:
        return {}

    monkeypatch.setattr(real_estate, "get_listing", fake_get_listing)
    resp = _client(real_estate_app).get("/v1/realestate/listing/999999")
    assert resp.status_code == 200
    assert resp.json()["success"] is False
    assert resp.json()["data"] == {}


def test_router_search_success(real_estate_app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_search(
        location: str, status: str = "for_sale", limit: int = 20
    ) -> list[dict[str, Any]]:
        return [{"address": f"1 {location}", "price": 100}]

    monkeypatch.setattr(real_estate, "search_listings", fake_search)
    resp = _client(real_estate_app).get(
        "/v1/realestate/search", params={"location": "Austin, TX", "status": "for_sale", "limit": 5}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["count"] == 1
    assert body["location"] == "Austin, TX"
    assert body["data"][0]["address"] == "1 Austin, TX"


def test_router_property_success(real_estate_app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_property(parcel_id: str, county: str) -> dict[str, Any]:
        return {"parcel_id": parcel_id, "county": county, "assessed_value": 619967}

    monkeypatch.setattr(real_estate, "get_property", fake_property)
    resp = _client(real_estate_app).get("/v1/realestate/property/wake-nc/0695327712")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["data"]["parcel_id"] == "0695327712"
    assert body["data"]["county"] == "wake-nc"


def test_router_502_when_module_absent(
    real_estate_app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(real_estate_router_mod, "_real_estate_module", lambda: None)
    client = _client(real_estate_app)
    assert client.get("/v1/realestate/listing/2064710495").status_code == 502
    assert client.get("/v1/realestate/search", params={"location": "Austin"}).status_code == 502
    assert client.get("/v1/realestate/property/wake-nc/0695327712").status_code == 502


def test_router_validation_422(real_estate_app: FastAPI) -> None:
    client = _client(real_estate_app)
    # location is required
    assert client.get("/v1/realestate/search").status_code == 422
    # limit must be >= 1
    resp = client.get("/v1/realestate/search", params={"location": "Austin", "limit": 0})
    assert resp.status_code == 422
