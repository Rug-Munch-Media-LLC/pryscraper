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
import json
from typing import Any

import httpx
import pytest
import respx

from datasets.real_estate import listings
from tests.real_estate._real_estate_support import (
    _hermetic_real_estate,  # noqa: F401
    _redfin_gis_payload,
    _zillow_search_html,
)
from tests.real_estate._real_estate_support2 import (
    _apartments_search_html,
    _zumper_search_html,
    real_estate_app,  # noqa: F401
)


@respx.mock(assert_all_mocked=False)
async def test_search_listings_zillow_success(respx_mock) -> None:
    respx_mock.get(url__startswith="https://www.zillow.com/homes/for_sale/austin-tx/").mock(
        return_value=httpx.Response(200, text=_zillow_search_html())
    )
    result = await listings.search_listings("Austin, TX", limit=20)
    assert len(result) == 2
    assert result[0]["address"] == "456 Elm St, Austin, TX 78702"
    assert result[0]["price"] == 350000
    assert result[0]["zestimate"] == 355000
    assert result[0]["bed"] == 2
    assert result[0]["bath"] == 1.5
    assert result[0]["sqft"] == 1200
    assert result[0]["days_on_market"] == 5
    assert result[0]["status"] == "For sale"
    assert result[1]["price"] == 520000
@respx.mock(assert_all_mocked=False)
async def test_search_listings_redfin_fallback_when_zillow_fails(respx_mock) -> None:
    respx_mock.get(url__startswith="https://www.redfin.com/stingray/api/gis").mock(
        return_value=httpx.Response(200, text="{}&&" + json.dumps(_redfin_gis_payload()))
    )
    result = await listings.search_listings("seattle", status="for_sale", limit=10)
    assert len(result) == 2
    first = result[0]
    assert first["source"] == "redfin"
    assert first["price"] == 950000
    assert first["bed"] == 3
    assert first["bath"] == 2
    assert first["sqft"] == 1800
    assert first["days_on_market"] == 8
    assert first["hoa"] == 250.0
    assert first["status"] == "Active"
    assert "732 11th Ave E" in first["address"]
    assert first["url"].startswith("https://www.redfin.com")
@respx.mock(assert_all_mocked=False)
async def test_search_listings_never_raises_when_everything_blocked(respx_mock) -> None:
    result = await listings.search_listings("Nowhere, XX")
    assert result == []
@respx.mock(assert_all_mocked=False, assert_all_called=False)
async def test_search_listings_unresolved_region_skips_redfin(respx_mock) -> None:
    route = respx_mock.get(url__startswith="https://www.redfin.com/stingray/api/gis").mock(
        return_value=httpx.Response(200, text="{}&&{}")
    )
    result = await listings.search_listings("Atlantis")
    assert result == []
    assert not route.called
@respx.mock(assert_all_mocked=False)
async def test_search_listings_unknown_status_defaults_to_for_sale(respx_mock) -> None:
    respx_mock.get(url__startswith="https://www.zillow.com/homes/for_sale/austin-tx/").mock(
        return_value=httpx.Response(200, text=_zillow_search_html())
    )
    result = await listings.search_listings("Austin, TX", status="totally-bogus")
    assert len(result) == 2
async def test_search_listings_clamps_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, int] = {}

    async def fake_zillow(location: str, status: str, limit: int) -> list[dict[str, Any]]:
        captured["limit"] = limit
        return [{"address": location}]

    monkeypatch.setattr(listings, "_search_zillow", fake_zillow)
    await listings.search_listings("Austin", limit=999)
    assert captured["limit"] == 50
    await listings.search_listings("Austin", limit=0)
    assert captured["limit"] == 1
@respx.mock(assert_all_mocked=False)
async def test_search_listings_apartments_fallback_for_rent(respx_mock) -> None:
    respx_mock.get(url__startswith="https://www.apartments.com/austin-tx/").mock(
        return_value=httpx.Response(200, text=_apartments_search_html())
    )
    result = await listings.search_listings("Austin, TX", status="for_rent", limit=10)
    assert len(result) == 2
    first = result[0]
    assert first["source"] == "apartments"
    assert first["price"] == 1450
    assert first["bed"] == 1
    assert first["bath"] == 1
    assert first["sqft"] == 650
    assert first["status"] == "For rent"
    assert first["address"] == "The Aster Apartments, 100 Congress Ave, Austin, TX 78701"
    assert first["url"].startswith("https://www.apartments.com")
    assert result[1]["price"] == 1800
@respx.mock(assert_all_mocked=False)
async def test_search_listings_zumper_fallback_after_apartments_fail(respx_mock) -> None:
    respx_mock.get(url__startswith="https://www.apartments.com/austin-tx/").mock(
        return_value=httpx.Response(200, text="<html><body>no listings</body></html>")
    )
    respx_mock.get(url__startswith="https://www.zumper.com/rent-search/austin-tx").mock(
        return_value=httpx.Response(200, text=_zumper_search_html())
    )
    result = await listings.search_listings("Austin, TX", status="for_rent", limit=10)
    assert len(result) == 2
    first = result[0]
    assert first["source"] == "zumper"
    assert first["price"] == 2100
    assert first["bed"] == 2
    assert first["bath"] == 1.5
    assert first["sqft"] == 950
    assert first["status"] == "For rent"
    assert first["address"] == "Charming Bungalow, 701 Rainey St"
    assert first["url"].startswith("https://www.zumper.com")
    assert result[1]["price"] == 2600
@respx.mock(assert_all_mocked=False, assert_all_called=False)
async def test_search_listings_for_sale_skips_rental_sources(respx_mock) -> None:
    apt_route = respx_mock.get(url__startswith="https://www.apartments.com/").mock(
        return_value=httpx.Response(200, text=_apartments_search_html())
    )
    z_route = respx_mock.get(url__startswith="https://www.zumper.com/").mock(
        return_value=httpx.Response(200, text=_zumper_search_html())
    )
    result = await listings.search_listings("Nowhere, XX", status="for_sale")
    assert result == []
    assert not apt_route.called
    assert not z_route.called
