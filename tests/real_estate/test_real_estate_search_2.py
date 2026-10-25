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
import httpx
import respx

from datasets.real_estate import listings
from tests.real_estate._real_estate_support2 import _zumper_search_html


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
