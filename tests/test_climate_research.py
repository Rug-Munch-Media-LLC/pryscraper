# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for the climate_data + research_data packages.

Covers NOAA NWS weather forecast/alerts (location parsing, mapping,
never-raise degradation), USDA NASS crop prices (API-key gating, withheld
values), OpenAlex/Crossref scholarly search (mapping, Crossref fallback),
RDAP WHOIS + crt.sh certificate transparency (mapping, malformed payloads),
and the /v1/climate/* + /v1/research/* routers (200 + 502-degradation +
422 validation).

All HTTP is mocked with respx — no live network.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

import datasets.climate_data as climate_data
import datasets.climate_data.agri as agri
import datasets.climate_data.weather as weather
import datasets.research_data as research_data
import datasets.research_data.academic as academic
import datasets.research_data.domain as domain
import pry.api.routers.climate_data as climate_router_mod
import pry.api.routers.research_data as research_router_mod
from pry.api.routers.climate_data import router as climate_router
from pry.api.routers.research_data import router as research_router
from pry.core.errors import PryError
from pry.engine.retry import RetryConfig

_POINTS = "https://api.weather.gov/points/"
_FORECAST = "https://api.weather.gov/gridpoints/LWX/97,71/forecast"
_STATIONS = "https://api.weather.gov/stations/KIAD"
_OBS = "https://api.weather.gov/stations/KIAD/observations/latest"
_ALERTS = "https://api.weather.gov/alerts/active"
_NASS = "https://quickstats.nass.usda.gov/api/api_GET/"
_OPENALEX = "https://api.openalex.org"
_CROSSREF = "https://api.crossref.org"
_RDAP = "https://rdap.org/domain/"
_CRTSH = "https://crt.sh/"

_ZERO_RETRY = RetryConfig(
    max_retries=1, base_delay=0.0, max_delay=0.0, retryable_exceptions=(httpx.HTTPError,)
)


@pytest.fixture(autouse=True)
def _hermetic_climate_research(monkeypatch: pytest.MonkeyPatch) -> None:
    """Kill backoff delays and clear the NASS key so tests are deterministic."""
    monkeypatch.setattr(weather, "_RETRY_CONFIG", _ZERO_RETRY)
    monkeypatch.setattr(agri, "_RETRY_CONFIG", _ZERO_RETRY)
    monkeypatch.setattr(academic, "_RETRY_CONFIG", _ZERO_RETRY)
    monkeypatch.setattr(domain, "_RETRY_CONFIG", _ZERO_RETRY)
    monkeypatch.delenv("PRY_NASS_API_KEY", raising=False)


# ── Payload fixtures ───────────────────────────────────────────────────


def _points_payload() -> dict[str, Any]:
    return {
        "properties": {
            "forecast": _FORECAST,
            "forecastZone": "https://api.weather.gov/zones/forecast/DCZ001",
            "observationStations": _STATIONS,
            "relativeLocation": {
                "properties": {"city": "Washington", "state": "DC", "distance": {"value": 1}}
            },
        }
    }


def _forecast_payload() -> dict[str, Any]:
    return {
        "properties": {
            "periods": [
                {
                    "name": "This Afternoon",
                    "startTime": "2026-08-16T18:00:00-04:00",
                    "isDaytime": True,
                    "temperature": 92,
                    "temperatureUnit": "F",
                    "shortForecast": "Sunny",
                    "probabilityOfPrecipitation": {"value": 10},
                },
                {
                    "name": "Tonight",
                    "startTime": "2026-08-16T18:00:00-04:00",
                    "isDaytime": False,
                    "temperature": 72,
                    "temperatureUnit": "F",
                    "shortForecast": "Mostly Clear",
                    "probabilityOfPrecipitation": {"value": 5},
                },
                {
                    "name": "Monday",
                    "startTime": "2026-08-17T06:00:00-04:00",
                    "isDaytime": True,
                    "temperature": 90,
                    "temperatureUnit": "F",
                    "shortForecast": "Partly Sunny",
                    "probabilityOfPrecipitation": {"value": 20},
                },
                {
                    "name": "Monday Night",
                    "startTime": "2026-08-17T18:00:00-04:00",
                    "isDaytime": False,
                    "temperature": 70,
                    "temperatureUnit": "F",
                    "shortForecast": "Partly Cloudy",
                    "probabilityOfPrecipitation": {"value": 0},
                },
            ]
        }
    }


def _stations_payload() -> dict[str, Any]:
    return {"features": [{"id": "https://api.weather.gov/stations/KIAD"}]}


def _observation_payload() -> dict[str, Any]:
    return {
        "properties": {
            "timestamp": "2026-08-16T18:53:00+00:00",
            "textDescription": "Sunny",
            "temperature": {"value": 31.1, "unitCode": "wmoUnit:degC"},
            "windSpeed": {"value": 13.0, "unitCode": "wmoUnit:km_h-1"},
            "relativeHumidity": {"value": 45.0},
        }
    }


def _alerts_payload() -> dict[str, Any]:
    return {
        "features": [
            {
                "id": "https://api.weather.gov/alerts/0d3e-abc",
                "properties": {
                    "event": "Heat Advisory",
                    "severity": "Moderate",
                    "headline": "Heat Advisory issued August 16 at 2:00PM EDT",
                    "description": "Heat index values up to 105 expected.",
                    "effective": "2026-08-16T15:00:00-04:00",
                    "expires": "2026-08-17T20:00:00-04:00",
                    "areaDesc": "DC",
                },
            }
        ]
    }


def _nass_payload() -> dict[str, Any]:
    return {
        "data": [
            {
                "commodity_desc": "CORN",
                "state_name": "IOWA",
                "year": "2025",
                "Value": "4.32",
                "unit_desc": "$ / BU",
                "short_desc": "CORN - PRICE RECEIVED, MEASURED IN $ / BU",
            },
            {
                "commodity_desc": "CORN",
                "state_name": "IOWA",
                "year": "2024",
                "Value": "(D)",
                "unit_desc": "$ / BU",
                "short_desc": "CORN - PRICE RECEIVED, MEASURED IN $ / BU",
            },
        ]
    }


def _openalex_work() -> dict[str, Any]:
    return {
        "id": "https://openalex.org/W2741809807",
        "display_name": "Attention Is All You Need",
        "publication_year": 2017,
        "cited_by_count": 62342,
        "doi": "https://doi.org/10.48550/arXiv.1706.03762",
        "authorships": [
            {"author": {"display_name": "Ashish Vaswani"}, "raw_author_name": "Ashish Vaswani"},
            {"author": {"display_name": "Noam Shazeer"}, "raw_author_name": "Noam Shazeer"},
        ],
    }


def _openalex_search_payload() -> dict[str, Any]:
    return {"results": [_openalex_work()]}


def _crossref_item() -> dict[str, Any]:
    return {
        "DOI": "10.48550/arXiv.1706.03762",
        "URL": "https://doi.org/10.48550/arXiv.1706.03762",
        "title": ["Attention Is All You Need"],
        "author": [
            {"given": "Ashish", "family": "Vaswani"},
            {"given": "Noam", "family": "Shazeer"},
        ],
        "issued": {"date-parts": [[2017]]},
        "is-referenced-by-count": 62342,
    }


def _crossref_search_payload() -> dict[str, Any]:
    return {"message": {"items": [_crossref_item()]}}


def _rdap_payload() -> dict[str, Any]:
    return {
        "handle": "D105292898-COM",
        "ldhName": "EXAMPLE.COM",
        "status": ["client delete prohibited", "client transfer prohibited"],
        "events": [
            {"eventAction": "registration", "eventDate": "1992-01-01T00:00:00Z"},
            {"eventAction": "expiration", "eventDate": "2027-01-01T00:00:00Z"},
        ],
        "nameservers": [{"ldhName": "a.iana-servers.net"}, {"ldhName": "b.iana-servers.net"}],
        "entities": [
            {
                "roles": ["registrar"],
                "vcardArray": [
                    "vcard",
                    [
                        ["version", {}, "text", "4.0"],
                        ["fn", {}, "text", "RESERVED-Internet Assigned Numbers Authority"],
                    ],
                ],
            }
        ],
    }


def _crtsh_payload() -> list[dict[str, Any]]:
    return [
        {
            "issuer_name": "C=US, O=Let's Encrypt, CN=R11",
            "common_name": "example.com",
            "name_value": "example.com\nwww.example.com",
            "id": 1234567890,
            "not_before": "2026-01-01T00:00:00",
            "not_after": "2026-04-01T00:00:00",
        }
    ]


# ── weather: NOAA NWS forecast ─────────────────────────────────────────


@respx.mock
async def test_forecast_success() -> None:
    respx.get(url__startswith=_POINTS).mock(
        return_value=httpx.Response(200, json=_points_payload())
    )
    respx.get(url__startswith=_FORECAST).mock(
        return_value=httpx.Response(200, json=_forecast_payload())
    )
    respx.get(url__startswith=_OBS).mock(
        return_value=httpx.Response(200, json=_observation_payload())
    )
    respx.get(url__startswith=_STATIONS).mock(
        return_value=httpx.Response(200, json=_stations_payload())
    )
    respx.get(url__startswith=_ALERTS).mock(
        return_value=httpx.Response(200, json=_alerts_payload())
    )

    result = await weather.get_forecast("38.9072,-77.0369", days=7)
    assert result["location"]["city"] == "Washington"
    assert result["location"]["state"] == "DC"
    assert result["current"]["temp_f"] == 88.0
    assert result["current"]["condition"] == "Sunny"
    assert result["current"]["wind_mph"] == 8.1
    assert len(result["forecast"]) == 2
    day1 = result["forecast"][0]
    assert day1["date"] == "2026-08-16"
    assert day1["high_f"] == 92
    assert day1["low_f"] == 72
    assert day1["condition"] == "Sunny"
    assert day1["precip_pct"] == 10
    assert result["alerts"][0]["event"] == "Heat Advisory"
    assert result["alerts"][0]["source"] == "noaa_nws"


@respx.mock
async def test_forecast_days_respected() -> None:
    respx.get(url__startswith=_POINTS).mock(
        return_value=httpx.Response(200, json=_points_payload())
    )
    respx.get(url__startswith=_FORECAST).mock(
        return_value=httpx.Response(200, json=_forecast_payload())
    )
    respx.get(url__startswith=_OBS).mock(
        return_value=httpx.Response(200, json=_observation_payload())
    )
    respx.get(url__startswith=_STATIONS).mock(
        return_value=httpx.Response(200, json=_stations_payload())
    )
    respx.get(url__startswith=_ALERTS).mock(
        return_value=httpx.Response(200, json=_alerts_payload())
    )

    result = await weather.get_forecast("38.9072,-77.0369", days=1)
    assert len(result["forecast"]) == 1


async def test_forecast_bad_location_returns_empty() -> None:
    assert await weather.get_forecast("not-a-location") == {}
    assert await weather.get_forecast("") == {}
    assert await weather.get_forecast("91.0,-77.0") == {}


@respx.mock
async def test_forecast_http_error_returns_empty() -> None:
    respx.get(url__startswith=_POINTS).mock(return_value=httpx.Response(500, text="boom"))
    assert await weather.get_forecast("38.9072,-77.0369") == {}


@respx.mock
async def test_forecast_malformed_payload_returns_empty() -> None:
    respx.get(url__startswith=_POINTS).mock(return_value=httpx.Response(200, json={"nope": True}))
    assert await weather.get_forecast("38.9072,-77.0369") == {}


# ── weather: NOAA NWS alerts ───────────────────────────────────────────


@respx.mock
async def test_alerts_by_zone() -> None:
    respx.get(url__startswith=_ALERTS).mock(
        return_value=httpx.Response(200, json=_alerts_payload())
    )
    alerts = await weather.get_alerts("DCZ001")
    assert len(alerts) == 1
    assert alerts[0]["event"] == "Heat Advisory"
    assert alerts[0]["areas"] == "DC"


@respx.mock
async def test_alerts_by_state() -> None:
    respx.get(url__startswith=_ALERTS).mock(
        return_value=httpx.Response(200, json=_alerts_payload())
    )
    alerts = await weather.get_alerts("DC")
    assert len(alerts) == 1


@respx.mock
async def test_alerts_by_point() -> None:
    respx.get(url__startswith=_ALERTS).mock(
        return_value=httpx.Response(200, json=_alerts_payload())
    )
    alerts = await weather.get_alerts("38.9072,-77.0369")
    assert len(alerts) == 1


@respx.mock
async def test_alerts_http_error_returns_empty() -> None:
    respx.get(url__startswith=_ALERTS).mock(return_value=httpx.Response(503, text="down"))
    assert await weather.get_alerts("DCZ001") == []
    assert await weather.get_alerts("") == []


# ── agri: USDA NASS crop prices ────────────────────────────────────────


@respx.mock
async def test_crop_prices_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRY_NASS_API_KEY", "test-key")
    respx.get(url__startswith=_NASS).mock(return_value=httpx.Response(200, json=_nass_payload()))
    prices = await agri.get_crop_prices("corn", state="Iowa", limit=5)
    assert len(prices) == 2
    first = prices[0]
    assert first["commodity"] == "CORN"
    assert first["state"] == "IOWA"
    assert first["year"] == 2025
    assert first["price"] == 4.32
    assert first["unit"] == "$ / BU"
    assert first["source"] == "usda_nass"
    # Withheld "(D)" values map to None, never raise
    assert prices[1]["price"] is None


@respx.mock
async def test_crop_prices_state_all_omits_state_param(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRY_NASS_API_KEY", "test-key")
    respx.get(url__startswith=_NASS).mock(return_value=httpx.Response(200, json=_nass_payload()))
    prices = await agri.get_crop_prices("corn", state="all")
    assert len(prices) == 2
    assert prices[0]["state"] == "IOWA"


async def test_crop_prices_no_key_returns_empty() -> None:
    assert await agri.get_crop_prices("corn") == []


@respx.mock
async def test_crop_prices_http_error_returns_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRY_NASS_API_KEY", "test-key")
    respx.get(url__startswith=_NASS).mock(return_value=httpx.Response(500, text="boom"))
    assert await agri.get_crop_prices("corn") == []


async def test_crop_prices_blank_commodity_returns_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRY_NASS_API_KEY", "test-key")
    assert await agri.get_crop_prices("   ") == []


# ── academic: OpenAlex + Crossref ──────────────────────────────────────


@respx.mock
async def test_search_papers_openalex_success() -> None:
    respx.get(url__startswith=f"{_OPENALEX}/works?").mock(
        return_value=httpx.Response(200, json=_openalex_search_payload())
    )
    papers = await academic.search_papers("attention is all you need", limit=10)
    assert len(papers) == 1
    paper = papers[0]
    assert paper["id"] == "https://openalex.org/W2741809807"
    assert paper["title"] == "Attention Is All You Need"
    assert paper["authors"] == ["Ashish Vaswani", "Noam Shazeer"]
    assert paper["year"] == 2017
    assert paper["citations"] == 62342
    assert paper["doi"] == "10.48550/arXiv.1706.03762"
    assert paper["source"] == "openalex"


@respx.mock
async def test_search_papers_crossref_fallback() -> None:
    # OpenAlex fails → Crossref is used
    respx.get(url__startswith=f"{_OPENALEX}/works?").mock(return_value=httpx.Response(500))
    respx.get(url__startswith=f"{_CROSSREF}/works?").mock(
        return_value=httpx.Response(200, json=_crossref_search_payload())
    )
    papers = await academic.search_papers("attention is all you need", limit=10)
    assert len(papers) == 1
    assert papers[0]["source"] == "crossref"
    assert papers[0]["title"] == "Attention Is All You Need"
    assert papers[0]["authors"] == ["Ashish Vaswani", "Noam Shazeer"]
    assert papers[0]["year"] == 2017
    assert papers[0]["doi"] == "10.48550/arXiv.1706.03762"


@respx.mock
async def test_search_papers_both_fail_returns_empty() -> None:
    respx.get(url__startswith=f"{_OPENALEX}/works?").mock(return_value=httpx.Response(500))
    respx.get(url__startswith=f"{_CROSSREF}/works?").mock(return_value=httpx.Response(503))
    assert await academic.search_papers("anything") == []


@respx.mock
async def test_search_papers_blank_query_returns_empty() -> None:
    assert await academic.search_papers("  ") == []


@respx.mock
async def test_get_paper_success() -> None:
    work = _openalex_work()
    work["abstract_inverted_index"] = {"Hello": [0], "world": [1]}
    respx.get(url__startswith=f"{_OPENALEX}/works/").mock(
        return_value=httpx.Response(200, json=work)
    )
    paper = await academic.get_paper("W2741809807")
    assert paper["id"] == "https://openalex.org/W2741809807"
    assert paper["title"] == "Attention Is All You Need"
    assert paper["abstract"] == "Hello world"


@respx.mock
async def test_get_paper_unknown_returns_empty() -> None:
    respx.get(url__startswith=f"{_OPENALEX}/works/").mock(return_value=httpx.Response(404))
    assert await academic.get_paper("W9999999999") == {}
    assert await academic.get_paper("") == {}


# ── domain: RDAP whois ─────────────────────────────────────────────────


@respx.mock
async def test_whois_lookup_success() -> None:
    respx.get(url__startswith=_RDAP).mock(return_value=httpx.Response(200, json=_rdap_payload()))
    record = await domain.whois_lookup("example.com")
    assert record["domain"] == "EXAMPLE.COM"
    assert record["registrar"] == "RESERVED-Internet Assigned Numbers Authority"
    assert record["created"] == "1992-01-01T00:00:00Z"
    assert record["expires"] == "2027-01-01T00:00:00Z"
    assert record["status"] == ["client delete prohibited", "client transfer prohibited"]
    assert record["nameservers"] == ["a.iana-servers.net", "b.iana-servers.net"]
    assert record["source"] == "rdap"


async def test_whois_lookup_invalid_domain_returns_empty() -> None:
    assert await domain.whois_lookup("") == {}
    assert await domain.whois_lookup("not a domain") == {}
    assert await domain.whois_lookup("nodot") == {}


@respx.mock
async def test_whois_lookup_http_error_returns_empty() -> None:
    respx.get(url__startswith=_RDAP).mock(return_value=httpx.Response(404))
    assert await domain.whois_lookup("definitely-not-registered-xyz.com") == {}


# ── domain: crt.sh certificate transparency ────────────────────────────


@respx.mock
async def test_cert_transparency_success() -> None:
    respx.get(url__startswith=_CRTSH).mock(return_value=httpx.Response(200, json=_crtsh_payload()))
    certs = await domain.cert_transparency("example.com", limit=10)
    assert len(certs) == 1
    cert = certs[0]
    assert cert["domain"] == "example.com"
    assert cert["issuer"] == "C=US, O=Let's Encrypt, CN=R11"
    assert cert["not_before"] == "2026-01-01T00:00:00"
    assert cert["not_after"] == "2026-04-01T00:00:00"
    assert cert["source"] == "crt_sh"


@respx.mock
async def test_cert_transparency_limit_respected() -> None:
    payload = _crtsh_payload() + _crtsh_payload()
    respx.get(url__startswith=_CRTSH).mock(return_value=httpx.Response(200, json=payload))
    certs = await domain.cert_transparency("example.com", limit=1)
    assert len(certs) == 1


@respx.mock
async def test_cert_transparency_malformed_payload_returns_empty() -> None:
    # crt.sh occasionally returns an HTML error page with a 200 status
    respx.get(url__startswith=_CRTSH).mock(
        return_value=httpx.Response(200, text="<html>error</html>")
    )
    assert await domain.cert_transparency("example.com") == []


@respx.mock
async def test_cert_transparency_http_error_returns_empty() -> None:
    respx.get(url__startswith=_CRTSH).mock(return_value=httpx.Response(500))
    assert await domain.cert_transparency("example.com") == []
    assert await domain.cert_transparency("") == []


# ── routers ────────────────────────────────────────────────────────────


@pytest.fixture
def climate_app() -> FastAPI:
    app = FastAPI()

    @app.exception_handler(PryError)
    async def pry_error_handler(request: Request, exc: PryError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": str(exc)})

    app.include_router(climate_router)
    return app


@pytest.fixture
def research_app() -> FastAPI:
    app = FastAPI()

    @app.exception_handler(PryError)
    async def pry_error_handler(request: Request, exc: PryError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": str(exc)})

    app.include_router(research_router)
    return app


def _client(app: FastAPI) -> TestClient:
    return TestClient(app)


def test_packages_importable() -> None:
    assert hasattr(climate_data, "get_forecast")
    assert hasattr(climate_data, "get_alerts")
    assert hasattr(climate_data, "get_crop_prices")
    assert hasattr(research_data, "search_papers")
    assert hasattr(research_data, "get_paper")
    assert hasattr(research_data, "whois_lookup")
    assert hasattr(research_data, "cert_transparency")
    assert hasattr(climate_router_mod, "router")
    assert hasattr(research_router_mod, "router")


def test_climate_router_forecast_success(
    climate_app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake(location: str, days: int = 7) -> dict[str, Any]:
        return {
            "location": {"lat": 38.9072, "lon": -77.0369, "city": "Washington", "state": "DC"},
            "current": {},
            "forecast": [{"date": "2026-08-16", "high_f": 92, "low_f": 72, "condition": "Sunny"}],
            "alerts": [],
        }

    monkeypatch.setattr(weather, "get_forecast", fake)
    resp = _client(climate_app).get(
        "/v1/climate/forecast", params={"location": "38.9072,-77.0369", "days": 3}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["location"] == "38.9072,-77.0369"
    assert body["data"]["forecast"][0]["high_f"] == 92


def test_climate_router_agri_success(climate_app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake(commodity: str, state: str = "all", limit: int = 20) -> list[dict[str, Any]]:
        return [
            {"commodity": "CORN", "state": state, "year": 2025, "price": 4.32, "unit": "$ / BU"}
        ]

    monkeypatch.setattr(agri, "get_crop_prices", fake)
    resp = _client(climate_app).get(
        "/v1/climate/agri", params={"commodity": "corn", "state": "Iowa", "limit": 5}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["commodity"] == "corn"
    assert body["data"][0]["price"] == 4.32


def test_research_router_papers_success(
    research_app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake(query: str, limit: int = 20) -> list[dict[str, Any]]:
        return [{"id": "https://openalex.org/W2741809807", "title": query, "source": "openalex"}]

    monkeypatch.setattr(academic, "search_papers", fake)
    resp = _client(research_app).get(
        "/v1/research/papers", params={"query": "attention", "limit": 5}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["query"] == "attention"
    assert body["data"][0]["id"] == "https://openalex.org/W2741809807"


def test_research_router_domain_success(
    research_app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake(domain: str) -> dict[str, Any]:
        return {"domain": domain, "registrar": "RESERVED-Internet Assigned Numbers Authority"}

    monkeypatch.setattr(domain, "whois_lookup", fake)
    resp = _client(research_app).get("/v1/research/domain/example.com")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["domain"] == "example.com"
    assert body["data"]["registrar"].startswith("RESERVED-")


def test_climate_router_502_when_module_absent(
    climate_app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(climate_router_mod, "_climate_module", lambda name: None)
    assert (
        _client(climate_app)
        .get("/v1/climate/forecast", params={"location": "38.9072,-77.0369"})
        .status_code
        == 502
    )
    assert (
        _client(climate_app).get("/v1/climate/agri", params={"commodity": "corn"}).status_code
        == 502
    )


def test_research_router_502_when_module_absent(
    research_app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(research_router_mod, "_research_module", lambda name: None)
    assert (
        _client(research_app).get("/v1/research/papers", params={"query": "attention"}).status_code
        == 502
    )
    assert _client(research_app).get("/v1/research/domain/example.com").status_code == 502


def test_climate_router_validation_422(climate_app: FastAPI) -> None:
    assert _client(climate_app).get("/v1/climate/forecast").status_code == 422
    assert (
        _client(climate_app).get("/v1/climate/forecast", params={"location": "x"}).status_code
        == 422
    )
    assert (
        _client(climate_app)
        .get("/v1/climate/forecast", params={"location": "38.9,-77.0", "days": 0})
        .status_code
        == 422
    )
    assert (
        _client(climate_app)
        .get("/v1/climate/forecast", params={"location": "38.9,-77.0", "days": 15})
        .status_code
        == 422
    )
    assert _client(climate_app).get("/v1/climate/agri").status_code == 422
    assert (
        _client(climate_app)
        .get("/v1/climate/agri", params={"commodity": "corn", "limit": 0})
        .status_code
        == 422
    )


def test_research_router_validation_422(research_app: FastAPI) -> None:
    assert _client(research_app).get("/v1/research/papers").status_code == 422
    assert (
        _client(research_app)
        .get("/v1/research/papers", params={"query": "x", "limit": 0})
        .status_code
        == 422
    )
    assert (
        _client(research_app)
        .get("/v1/research/papers", params={"query": "x", "limit": 101})
        .status_code
        == 422
    )
    assert _client(research_app).get("/v1/research/domain/nodot").status_code == 400
