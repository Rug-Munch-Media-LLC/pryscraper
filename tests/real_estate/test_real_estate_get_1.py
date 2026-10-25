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

import httpx
import pytest
import respx

from datasets.real_estate import listings
from tests.real_estate._real_estate_support import _redfin_detail_payload, _zillow_listing_html
from tests.real_estate._real_estate_support2 import _apartments_search_html, _zumper_search_html


@respx.mock(assert_all_mocked=False)
async def test_get_listing_zillow_success(respx_mock) -> None:
    respx_mock.get("https://www.zillow.com/homedetails/2064710495_zpid/").mock(
        return_value=httpx.Response(200, text=_zillow_listing_html())
    )
    result = await listings.get_listing("2064710495")
    assert result["address"] == "123 Main St, Austin, TX 78701"
    assert result["price"] == 450000
    expected = [
        {"date": "2024-01-15", "price": 425000, "event": "Sold"},
        {"date": "2025-05-01", "price": 450000, "event": "Listing removed"},
    ]
    assert result["price_history"] == expected
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
