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

from datasets.real_estate import property_records
from tests.real_estate._real_estate_support import _hermetic_real_estate  # noqa: F401
from tests.real_estate._real_estate_support2 import (
    _arcgis_payload,
    real_estate_app,  # noqa: F401
)


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
    expected = [
        {
            "price": 795000,
            "sale_date": "2024-12-16T00:00:00+00:00",
            "deed_book": "2024",
            "deed_page": "12345",
            "source": "county_assessor",
        }
    ]
    assert result["sale_history"] == expected
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
