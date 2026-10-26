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
from datasets.real_estate import listings
from tests.real_estate._real_estate_support import (
    _hermetic_real_estate,  # noqa: F401
    _zillow_listing_html,
)
from tests.real_estate._real_estate_support2 import (
    _apartments_search_html,
    _zumper_search_html,
    real_estate_app,  # noqa: F401
)


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
