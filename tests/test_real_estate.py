# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
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

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
import respx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

import datasets.real_estate as real_estate
import pry.api.routers.data.real_estate as real_estate_router_mod
from datasets.real_estate import listings, property_records
from pry.api.routers.data.real_estate import router as real_estate_router
from pry.core.errors import PryError


@pytest.fixture(autouse=True)
def _hermetic_real_estate(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Zero retries/backoff + clear the per-host robots cache.

    respx auto-mocks unregistered URLs with an empty 200, so the only
    retryable failures in tests are the explicitly-registered 4xx/5xx
    responses; a zero-retry config keeps those paths instant.
    """
    from pry.engine.retry import RetryConfig

    zero = RetryConfig(
        max_retries=0,
        base_delay=0.0,
        max_delay=0.0,
        retryable_exceptions=(httpx.HTTPError,),
    )
    monkeypatch.setattr(listings, "_RETRY_CONFIG", zero)
    monkeypatch.setattr(property_records, "_RETRY_CONFIG", zero)
    listings.reset_robots_cache()
    yield
    listings.reset_robots_cache()


# ── Fixtures ──────────────────────────────────────────────────────────


def _page_with_next_data(payload: dict[str, Any]) -> str:
    return (
        "<!DOCTYPE html><html><head></head><body>"
        '<script id="__NEXT_DATA__" type="application/json">'
        + json.dumps(payload)
        + "</script></body></html>"
    )


def _zillow_listing_html() -> str:
    payload = {
        "props": {
            "pageProps": {
                "initialReduxState": {
                    "gdp": {
                        "homeInfo": {
                            "address": {
                                "streetAddress": "123 Main St",
                                "city": "Austin",
                                "state": "TX",
                                "zipcode": "78701",
                            },
                            "price": 450000,
                            "priceHistory": [
                                {"date": "2024-01-15", "event": "Sold", "price": 425000},
                                {"date": "2025-05-01", "event": "Listing removed", "price": 450000},
                            ],
                            "zestimate": 460123,
                            "bedrooms": 3,
                            "bathrooms": 2.5,
                            "livingArea": 2100,
                            "daysOnZillow": 12,
                            "hoa": 45.0,
                            "homeStatus": "FOR_SALE",
                        }
                    }
                }
            }
        }
    }
    return _page_with_next_data(payload)


def _zillow_search_html() -> str:
    payload = {
        "props": {
            "pageProps": {
                "searchPageState": {
                    "cat1": {
                        "searchResults": {
                            "listResults": [
                                {
                                    "zpid": 2064710001,
                                    "address": {
                                        "streetAddress": "456 Elm St",
                                        "city": "Austin",
                                        "state": "TX",
                                        "zipcode": "78702",
                                    },
                                    "price": 350000,
                                    "bedrooms": 2,
                                    "bathrooms": 1.5,
                                    "livingArea": 1200,
                                    "statusText": "For sale",
                                    "hdpData": {
                                        "homeInfo": {"zestimate": 355000, "daysOnZillow": 5}
                                    },
                                },
                                {
                                    "zpid": 2064710002,
                                    "address": {
                                        "streetAddress": "789 Oak Ave",
                                        "city": "Austin",
                                        "state": "TX",
                                        "zipcode": "78703",
                                    },
                                    "price": 520000,
                                    "bedrooms": 4,
                                    "bathrooms": 3.0,
                                    "livingArea": 2400,
                                    "statusText": "For sale",
                                    "hdpData": {"homeInfo": {"zestimate": 525000}},
                                },
                            ]
                        }
                    }
                }
            }
        }
    }
    return _page_with_next_data(payload)


def _redfin_gis_payload() -> dict[str, Any]:
    return {
        "payload": {
            "homes": [
                {
                    "url": "/WA/Seattle/732-11th-Ave-E-98102/home/52821",
                    "city": "Seattle",
                    "state": "WA",
                    "zip": "98102",
                    "price": 950000,
                    "beds": 3,
                    "baths": 2,
                    "sqFt": 1800,
                    "dom": 8,
                    "mlsStatus": "Active",
                    "hoa": {"value": 250},
                },
                {
                    "url": "/WA/Seattle/123-Pike-St-98101/home/51234",
                    "city": "Seattle",
                    "state": "WA",
                    "zip": "98101",
                    "price": 1200000,
                    "beds": 4,
                    "baths": 3.5,
                    "sqFt": 2500,
                    "dom": 15,
                },
            ]
        }
    }


def _redfin_detail_payload() -> dict[str, Any]:
    return {
        "payload": {
            "homeInfo": {
                "streetAddress": "500 Boren Ave N",
                "city": "Seattle",
                "state": "WA",
                "zip": "98109",
                "price": 1100000,
                "beds": 4,
                "baths": 3,
                "sqFt": 2200,
                "daysOnMarket": 22,
                "zestimate": 1115000,
                "hoa": 175,
                "status": "Active",
            }
        }
    }


def _apartments_search_html() -> str:
    """An Apartments.com SRP page with a ``__PRELOADED_STATE__`` blob."""
    payload = {
        "place": {
            "listings": [
                {
                    "id": "apt-1",
                    "name": "The Aster Apartments",
                    "address": {
                        "streetAddress": "100 Congress Ave",
                        "city": "Austin",
                        "state": "TX",
                        "postalCode": "78701",
                    },
                    "price": {"min": 1450, "max": 2200},
                    "beds": {"min": 1, "max": 2},
                    "baths": {"min": 1, "max": 2},
                    "sqft": {"min": 650, "max": 1100},
                    "detailUrl": "/austin-tx/the-aster-apartments/apt-1/",
                },
                {
                    "id": "apt-2",
                    "name": "Domain Lofts",
                    "address": {
                        "streetAddress": "500 Domain Dr",
                        "city": "Austin",
                        "state": "TX",
                        "postalCode": "78758",
                    },
                    "price": {"min": 1800},
                    "beds": {"min": 2},
                    "baths": {"min": 2},
                    "sqft": {"min": 900},
                    "detailUrl": "/austin-tx/domain-lofts/apt-2/",
                },
            ]
        }
    }
    return (
        "<!DOCTYPE html><html><head></head><body>"
        '<script type="application/json" id="__PRELOADED_STATE__">'
        + json.dumps(payload)
        + "</script></body></html>"
    )


def _zumper_search_html() -> str:
    """A Zumper rent-search page with a ``window.__NUXT__`` state blob."""
    payload = {
        "data": {
            "rentals": [
                {
                    "id": "z-1",
                    "title": "Charming Bungalow",
                    "address": "701 Rainey St",
                    "city": "Austin",
                    "state": "TX",
                    "price": {"min": 2100, "max": 2400},
                    "bedrooms": 2,
                    "bathrooms": 1.5,
                    "sqft": 950,
                    "url": "https://www.zumper.com/austin-tx/charming-bungalow/z-1",
                },
                {
                    "id": "z-2",
                    "title": "Skyline Condo",
                    "address": "300 E 6th St",
                    "city": "Austin",
                    "state": "TX",
                    "price": {"min": 2600},
                    "bedrooms": 1,
                    "bathrooms": 1,
                    "sqft": 700,
                    "url": "https://www.zumper.com/austin-tx/skyline-condo/z-2",
                },
            ]
        }
    }
    return (
        "<!DOCTYPE html><html><head></head><body>"
        "<script>window.__NUXT__ = " + json.dumps(payload) + ";</script>"
        "</body></html>"
    )


def _arcgis_payload() -> dict[str, Any]:
    return {
        "features": [
            {
                "attributes": {
                    "PIN_NUM": "0695327712",
                    "OWNER": "GURRAM, ANANDA PAPIREDDY, MURALIDHAR REDDY",
                    "TOTAL_VALUE_ASSD": 619967,
                    "TOTSALPRICE": 795000,
                    "SALE_DATE": 1734307200000,
                    "DEED_BOOK": "2024",
                    "DEED_PAGE": "12345",
                    "SITE_ADDRESS": "123 Main St",
                    "CITY": "Raleigh",
                    "YEAR_BUILT": 2005,
                    "HEATEDAREA": 2400,
                }
            }
        ]
    }


# ── Listings parsing unit tests ───────────────────────────────────────


def test_extract_next_data_parses() -> None:
    data = listings._extract_next_data(_zillow_listing_html())
    assert data is not None
    assert data["props"]["pageProps"]["initialReduxState"]["gdp"]["homeInfo"]["price"] == 450000


def test_extract_next_data_missing() -> None:
    assert listings._extract_next_data("<html><body><p>no json here</p></body></html>") is None
    assert listings._extract_next_data("<script>window.__NEXT_DATA__ = {}</script>") is None


def test_extract_preloaded_state_parses() -> None:
    data = listings._extract_preloaded_state(_apartments_search_html())
    assert data is not None
    assert data["place"]["listings"][0]["name"] == "The Aster Apartments"


def test_extract_preloaded_state_missing() -> None:
    assert listings._extract_preloaded_state("<html><body>no state</body></html>") is None
    assert (
        listings._extract_preloaded_state('<script id="__PRELOADED_STATE__">not json</script>')
        is None
    )


def test_extract_nuxt_state_parses() -> None:
    data = listings._extract_nuxt_state(_zumper_search_html())
    assert data is not None
    assert len(data["data"]["rentals"]) == 2
    assert data["data"]["rentals"][0]["id"] == "z-1"


def test_extract_nuxt_state_missing() -> None:
    assert listings._extract_nuxt_state("<html><body>no nuxt</body></html>") is None
    assert listings._extract_nuxt_state("window.__NUXT__ = {oops}") is None


def test_is_bot_page_detects_walls() -> None:
    assert listings._is_bot_page("<html>Just a moment... checking your browser</html>") is True
    assert (
        listings._is_bot_page('<html><div id="captcha">Verify you are human</div></html>') is True
    )
    assert listings._is_bot_page("<html><body>normal listings page</body></html>") is False
    assert listings._is_bot_page("") is False


def test_slugify() -> None:
    assert listings._slugify("Austin, TX") == "austin-tx"
    assert listings._slugify("  New   York City ") == "new-york-city"
    assert listings._slugify("") == ""
    assert listings._slugify("   ") == ""


def test_format_address_dict_and_str() -> None:
    raw = {"streetAddress": "1 Main", "city": "Austin", "state": "TX", "zipcode": "78701"}
    assert listings._format_address(raw) == "1 Main, Austin, TX 78701"
    assert listings._format_address("plain address") == "plain address"
    assert listings._format_address(None) == ""


def test_to_int_unwraps_wrapped_scalars() -> None:
    assert listings._to_int({"value": "450000"}) == 450000
    assert listings._to_int(450000) == 450000
    assert listings._to_int("450000.9") == 450000
    assert listings._to_int(None) is None
    assert listings._to_int("nope") is None


def test_normalize_price_history_skips_bad_entries() -> None:
    raw = [
        {"date": "2024-01-15", "event": "Sold", "price": 425000},
        "garbage",
        {"price": "junk"},
    ]
    out = listings._normalize_price_history(raw)
    assert out == [
        {"date": "2024-01-15", "price": 425000, "event": "Sold"},
        {"date": "", "price": None, "event": ""},
    ]


# ── get_listing async tests (mocked HTTP) ─────────────────────────────


@respx.mock(assert_all_mocked=False)
async def test_get_listing_zillow_success(respx_mock) -> None:
    respx_mock.get("https://www.zillow.com/homedetails/2064710495_zpid/").mock(
        return_value=httpx.Response(200, text=_zillow_listing_html())
    )
    result = await listings.get_listing("2064710495")
    assert result["address"] == "123 Main St, Austin, TX 78701"
    assert result["price"] == 450000
    assert result["price_history"] == [
        {"date": "2024-01-15", "price": 425000, "event": "Sold"},
        {"date": "2025-05-01", "price": 450000, "event": "Listing removed"},
    ]
    assert result["zestimate"] == 460123
    assert result["bed"] == 3
    assert result["bath"] == 2.5
    assert result["sqft"] == 2100
    assert result["days_on_market"] == 12
    assert result["hoa"] == 45.0
    assert result["url"] == "https://www.zillow.com/homedetails/2064710495_zpid/"
    assert result["source"] == "zillow"
    assert result["status"] == "FOR_SALE"


@respx.mock(assert_all_mocked=False)
async def test_get_listing_redfin_fallback_when_zillow_blocked(respx_mock) -> None:
    # Zillow page is unregistered -> auto-mocked empty page -> Redfin fallback.
    respx_mock.get(
        url__startswith="https://www.redfin.com/stingray/api/home/details/initialInfo"
    ).mock(return_value=httpx.Response(200, text=json.dumps(_redfin_detail_payload())))
    result = await listings.get_listing("52821")
    assert result["source"] == "redfin"
    assert result["price"] == 1100000
    assert result["bed"] == 4
    assert result["bath"] == 3
    assert result["sqft"] == 2200
    assert result["days_on_market"] == 22
    assert result["hoa"] == 175.0
    assert result["address"] == "500 Boren Ave N, Seattle, WA 98109"


@respx.mock(assert_all_mocked=False)
async def test_get_listing_falls_back_on_unparseable_page(respx_mock) -> None:
    respx_mock.get("https://www.zillow.com/homedetails/2064710495_zpid/").mock(
        return_value=httpx.Response(200, text="<html><body>bot wall</body></html>")
    )
    respx_mock.get(
        url__startswith="https://www.redfin.com/stingray/api/home/details/initialInfo"
    ).mock(return_value=httpx.Response(200, text=json.dumps(_redfin_detail_payload())))
    result = await listings.get_listing("2064710495")
    assert result["source"] == "redfin"
    assert result["price"] == 1100000


@respx.mock(assert_all_mocked=False)
async def test_get_listing_never_raises_when_everything_blocked(respx_mock) -> None:
    result = await listings.get_listing("2064710495")
    assert result == {}


@respx.mock(assert_all_mocked=False)
async def test_get_listing_http_500_never_raises(respx_mock) -> None:
    respx_mock.get("https://www.zillow.com/homedetails/2064710495_zpid/").mock(
        return_value=httpx.Response(500)
    )
    respx_mock.get(
        url__startswith="https://www.redfin.com/stingray/api/home/details/initialInfo"
    ).mock(return_value=httpx.Response(403))
    result = await listings.get_listing("2064710495")
    assert result == {}


@respx.mock(assert_all_mocked=False)
async def test_get_listing_apartments_fallback_when_zillow_redfin_fail(respx_mock) -> None:
    respx_mock.get(url__startswith="https://www.apartments.com/2064710495/").mock(
        return_value=httpx.Response(200, text=_apartments_search_html())
    )
    result = await listings.get_listing("2064710495")
    assert result["source"] == "apartments"
    assert result["price"] == 1450
    assert result["bed"] == 1
    assert result["status"] == "For rent"


@respx.mock(assert_all_mocked=False)
async def test_get_listing_zumper_fallback_last(respx_mock) -> None:
    respx_mock.get(url__startswith="https://www.apartments.com/2064710495/").mock(
        return_value=httpx.Response(200, text="<html><body>no data</body></html>")
    )
    respx_mock.get(url__startswith="https://www.zumper.com/rentals/2064710495").mock(
        return_value=httpx.Response(200, text=_zumper_search_html())
    )
    result = await listings.get_listing("2064710495")
    assert result["source"] == "zumper"
    assert result["price"] == 2100
    assert result["bed"] == 2


# ── search_listings async tests (mocked HTTP) ─────────────────────────


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


# ── search_listings: Apartments.com / Zumper rental fallbacks ─────────


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


@respx.mock(assert_all_mocked=False)
async def test_search_listings_bot_walls_all_sources_empty(respx_mock) -> None:
    respx_mock.get(url__startswith="https://www.apartments.com/austin-tx/").mock(
        return_value=httpx.Response(
            200, text="<html><body>Just a moment... (Cloudflare challenge)</body></html>"
        )
    )
    respx_mock.get(url__startswith="https://www.zumper.com/rent-search/austin-tx").mock(
        return_value=httpx.Response(
            200, text="<html><body>Access denied by PerimeterX</body></html>"
        )
    )
    result = await listings.search_listings("Austin, TX", status="for_rent")
    assert result == []


@respx.mock(assert_all_mocked=False)
async def test_search_listings_apartments_bot_wall_falls_to_zumper(respx_mock) -> None:
    respx_mock.get(url__startswith="https://www.apartments.com/austin-tx/").mock(
        return_value=httpx.Response(
            200, text='<html><div id="captcha">Verify you are human</div></html>'
        )
    )
    respx_mock.get(url__startswith="https://www.zumper.com/rent-search/austin-tx").mock(
        return_value=httpx.Response(200, text=_zumper_search_html())
    )
    result = await listings.search_listings("Austin, TX", status="for_rent")
    assert len(result) == 2
    assert result[0]["source"] == "zumper"


# ── robots.txt policy ─────────────────────────────────────────────────


@respx.mock(assert_all_mocked=False, assert_all_called=False)
async def test_get_listing_enforce_robots_blocks_fetch(
    respx_mock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PRY_REAL_ESTATE_ENFORCE_ROBOTS", "1")
    page_route = respx_mock.get("https://www.zillow.com/homedetails/2064710495_zpid/").mock(
        return_value=httpx.Response(200, text=_zillow_listing_html())
    )
    respx_mock.get("https://www.zillow.com/robots.txt").mock(
        return_value=httpx.Response(
            200, text="User-agent: *\nDisallow: /homedetails/\nCrawl-delay: 2\n"
        )
    )
    result = await listings.get_listing("2064710495")
    assert result == {}
    assert not page_route.called  # blocked before fetching


@respx.mock(assert_all_mocked=False)
async def test_get_listing_robots_advisory_still_fetches(respx_mock) -> None:
    page_route = respx_mock.get("https://www.zillow.com/homedetails/2064710495_zpid/").mock(
        return_value=httpx.Response(200, text=_zillow_listing_html())
    )
    respx_mock.get("https://www.zillow.com/robots.txt").mock(
        return_value=httpx.Response(
            200, text="User-agent: *\nDisallow: /homedetails/\nCrawl-delay: 0\n"
        )
    )
    result = await listings.get_listing("2064710495")
    assert page_route.called
    assert result["price"] == 450000


# ── property_records tests (mocked HTTP) ──────────────────────────────


def test_epoch_millis_to_iso() -> None:
    assert property_records._epoch_millis_to_iso(1734307200000) == "2024-12-16T00:00:00+00:00"
    assert property_records._epoch_millis_to_iso(0) is None
    assert property_records._epoch_millis_to_iso("junk") is None
    assert property_records._epoch_millis_to_iso(None) is None


@respx.mock(assert_all_mocked=False)
async def test_get_property_wake_nc_success(respx_mock) -> None:
    respx_mock.get(
        url__startswith="https://maps.wakegov.com/arcgis/rest/services/Property/Parcels/FeatureServer/0/query"
    ).mock(return_value=httpx.Response(200, json=_arcgis_payload()))
    result = await property_records.get_property("0695327712", "wake-nc")
    assert result["parcel_id"] == "0695327712"
    assert result["owner"] == "GURRAM, ANANDA PAPIREDDY, MURALIDHAR REDDY"
    assert result["assessed_value"] == 619967
    assert result["tax"] is None
    assert result["county"] == "Wake County, North Carolina"
    assert result["source"] == "arcgis"
    assert result["sale_history"] == [
        {
            "price": 795000,
            "sale_date": "2024-12-16T00:00:00+00:00",
            "deed_book": "2024",
            "deed_page": "12345",
            "source": "county_assessor",
        }
    ]
    assert result["details"]["site_address"] == "123 Main St"
    assert result["details"]["year_built"] == 2005


@respx.mock(assert_all_mocked=False)
async def test_get_property_accepts_county_name_variants(respx_mock) -> None:
    respx_mock.get(
        url__startswith="https://maps.wakegov.com/arcgis/rest/services/Property/Parcels/FeatureServer/0/query"
    ).mock(return_value=httpx.Response(200, json=_arcgis_payload()))
    result = await property_records.get_property("0695327712", "Wake, NC")
    assert result["parcel_id"] == "0695327712"
    assert result["assessed_value"] == 619967


async def test_get_property_unknown_county_returns_empty() -> None:
    result = await property_records.get_property("123", "no-such-county")
    assert result == {}


@respx.mock(assert_all_mocked=False)
async def test_get_property_parcel_not_found_returns_empty(respx_mock) -> None:
    respx_mock.get(
        url__startswith="https://maps.wakegov.com/arcgis/rest/services/Property/Parcels/FeatureServer/0/query"
    ).mock(return_value=httpx.Response(200, json={"features": []}))
    result = await property_records.get_property("0000000000", "wake-nc")
    assert result == {}


@respx.mock(assert_all_mocked=False)
async def test_get_property_never_raises_on_network_failure(respx_mock) -> None:
    respx_mock.get(
        url__startswith="https://maps.wakegov.com/arcgis/rest/services/Property/Parcels/FeatureServer/0/query"
    ).mock(return_value=httpx.Response(503))
    result = await property_records.get_property("0695327712", "wake-nc")
    assert result == {}


@respx.mock(assert_all_mocked=False)
async def test_get_property_env_registry_extra_county(
    respx_mock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(
        "PRY_REAL_ESTATE_ARCGIS_URLS",
        json.dumps(
            {
                "test-co": {
                    "url": "https://gis.example.gov/arcgis/rest/services/Parcels/FeatureServer/0",
                    "id_field": "PARCEL_ID",
                    "owner_field": "OWNER",
                    "assessed_value_field": "ASSESSED",
                    "sale_price_field": "SALE_PRICE",
                    "name": "Test County",
                }
            }
        ),
    )
    respx_mock.get(
        url__startswith="https://gis.example.gov/arcgis/rest/services/Parcels/FeatureServer/0/query"
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "features": [
                    {
                        "attributes": {
                            "PARCEL_ID": "P-42",
                            "OWNER": "Jane Doe",
                            "ASSESSED": 250000,
                            "SALE_PRICE": 240000,
                        }
                    }
                ]
            },
        )
    )
    result = await property_records.get_property("P-42", "test-co")
    assert result["parcel_id"] == "P-42"
    assert result["owner"] == "Jane Doe"
    assert result["assessed_value"] == 250000
    assert result["sale_history"][0]["price"] == 240000


# ── Router tests ──────────────────────────────────────────────────────


@pytest.fixture
def real_estate_app() -> FastAPI:
    app = FastAPI()

    @app.exception_handler(PryError)
    async def pry_error_handler(request: Request, exc: PryError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": str(exc)})

    app.include_router(real_estate_router)
    return app


def _client(app: FastAPI) -> TestClient:
    return TestClient(app)


def test_router_importable() -> None:
    import datasets.real_estate as re_pkg
    import pry.api.routers.data.real_estate as re_router

    assert re_pkg.__all__ == ["get_listing", "get_property", "search_listings"]
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
