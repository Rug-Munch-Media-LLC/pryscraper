# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for the freight_data package.

Covers container rate retrieval (Freightos FBX embedded JSON with Drewry WCI
Infogram fallback — mapping, route filtering, money/date parsing, never-raise
degradation), FMC Agreement Library parsing (HTML table mapping, query
filtering, carrier/trade-lane extraction, status heuristics), and the
/v1/freight/* routers (200 + 502-degradation + 422 validation + 400 blank).

All HTTP is mocked with respx — no live network.
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

import freight_data
import freight_data.rates as rates
import routers.freight_data as freight_router_mod
from errors import PryError
from retry import RetryConfig
from routers.freight_data import router as freight_router

_FBX_PAGE = "https://www.freightos.com/enterprise/terminal/freightos-baltic-index-global-container-pricing-index/"
_FMC_INDEX = "https://www2.fmc.gov/eagreementssp/public/index"
_DREWRY_INFOGRAM = "https://infogram.com/world-container-index-1h17493095xl4zj"

_ZERO_RETRY = RetryConfig(
    max_retries=1, base_delay=0.0, max_delay=0.0, retryable_exceptions=(httpx.HTTPError,)
)


@pytest.fixture(autouse=True)
def _hermetic_freight(monkeypatch: pytest.MonkeyPatch) -> None:
    """Kill backoff delays so tests are deterministic and fast."""
    monkeypatch.setattr(rates, "_RETRY_CONFIG", _ZERO_RETRY)


# ── Payload fixtures ───────────────────────────────────────────────────


def _fbx_ticker_payload() -> list[dict[str, Any]]:
    return [
        {"label": "FBX", "value": "$3,690", "change": "+2.3%", "positive": True},
        {"label": "FBX01", "value": "$7,422", "change": "+8.72%", "positive": True},
        {"label": "FBX02", "value": "$4,353", "change": "-5.67%", "positive": False},
        {"label": "FBX03", "value": "$9,422", "change": "+3.04%", "positive": True},
        {"label": "FBX04", "value": "$5,523", "change": "+7.56%", "positive": True},
    ]


def _fbx_chart_payload() -> list[dict[str, Any]]:
    return [
        {"ticker": "FBX", "indexDate": "2026-05-22", "value": 2196.6},
        {"ticker": "FBX", "indexDate": "2026-05-29", "value": 2234.75},
        {"ticker": "FBX01", "indexDate": "2026-05-29", "value": 4100.0},
    ]


def _fbx_page_html() -> str:
    ticker = json.dumps(_fbx_ticker_payload())
    chart = json.dumps(_fbx_chart_payload())
    return (
        "<html><body><script>"
        f"window.frProductIntroTickerData['fr-product-intro-abc'] = {ticker};"
        f"window.frProductIntroChartData['fr-product-intro-abc'] = {chart};"
        "</script></body></html>"
    )


def _drewry_infogram_html() -> str:
    payload = {
        "id": 1,
        "elements": {
            "content": {
                "content": {
                    "entities": {
                        "chart-1": {
                            "data": [
                                [None, {"value": "Composite"}],
                                [{"value": "10-Mar-16"}, {"value": "700.57"}],
                                [{"value": "17-Mar-16"}, {"value": "674.41"}],
                            ]
                        },
                        "chart-2": {
                            "data": [
                                [None, {"value": "Shanghai\u2013Rotterdam"}],
                                [{"value": "10-Mar-16"}, {"value": "827.0"}],
                                [{"value": "17-Mar-16"}, {"value": "812.0"}],
                            ]
                        },
                        "chart-3": {
                            "data": [
                                {"not_a_row": True},
                                {"also": "ignored"},
                            ]
                        },
                    }
                }
            }
        },
    }
    return f"<html><script>window.infographicData = {json.dumps(payload)};</script></html>"


def _fmc_html() -> str:
    return """<!DOCTYPE html><html><head><title>FMC Agreement Library</title></head>
<body>
<form action="/eAgreementsSP/Public/Index" method="get">
<input type="search" placeholder="Filter by Agreement" />
</form>
<table class="table table-striped">
<thead><tr>
<th>Number</th><th>Agreement Type</th><th>Agreement Name</th>
<th>Original Effective Date</th><th>Date of Last Amendment</th>
</tr></thead>
<tbody>
<tr>
<td><a href="/eAgreementsSP/Public/AgreementHistory/39502">201353-003</a></td>
<td>Vessel Sharing Agreement</td>
<td><a href="/eAgreementsSP/Public/AgreementHistory/39502">THE Alliance/Evergreen Vessel Sharing Agreement</a></td>
<td>3/15/2021</td><td>8/13/2026</td>
</tr>
<tr>
<td><a href="/eAgreementsSP/Public/AgreementHistory/91649">201464-001</a></td>
<td>Space Charter Agreement</td>
<td><a href="/eAgreementsSP/Public/AgreementHistory/91649">CMA CGM / NEOLINE North Europe \u2013 USEC Service Space Charter Agreement</a></td>
<td>4/20/2026</td><td>8/4/2026</td>
</tr>
<tr>
<td><a href="/eAgreementsSP/Public/AgreementHistory/999">000001-001</a></td>
<td>Discussion Agreement</td>
<td><a href="/eAgreementsSP/Public/AgreementHistory/999">Old Test Agreement</a></td>
<td>1/1/2000</td><td>2/2/2001</td>
</tr>
</tbody>
</table>
</body></html>"""


# ── container rates: Freightos FBX ─────────────────────────────────────


@respx.mock
async def test_fbx_rates_success() -> None:
    respx.get(url__startswith=_FBX_PAGE).mock(
        return_value=httpx.Response(200, text=_fbx_page_html())
    )
    records = await rates.get_container_rates(limit=20)
    assert len(records) == 5
    by_route = {rec["route"]: rec for rec in records}
    fbx01 = by_route["china-us-west-coast"]
    assert fbx01["origin"] == "China"
    assert fbx01["destination"] == "US West Coast"
    assert fbx01["rate_40ft_usd"] == 4100.0  # chart data preferred over ticker "$7,422"
    assert fbx01["index_source"] == "freightos_fbx"
    assert fbx01["date"] == "2026-05-29"
    # Ticker-only lane uses the "$" value with today's date.
    fbx04 = by_route["china-mediterranean"]
    assert fbx04["rate_40ft_usd"] == 5523.0
    assert fbx04["origin"] == "China"
    assert fbx04["destination"] == "Mediterranean"
    # Composite chart value (latest of the two dates).
    composite = by_route["fbx-composite"]
    assert composite["rate_40ft_usd"] == 2234.75
    assert composite["date"] == "2026-05-29"


@respx.mock
async def test_fbx_rates_route_filters() -> None:
    respx.get(url__startswith=_FBX_PAGE).mock(
        return_value=httpx.Response(200, text=_fbx_page_html())
    )
    assert [r["route"] for r in await rates.get_container_rates(route="china-us-west-coast")] == [
        "china-us-west-coast"
    ]
    assert [r["route"] for r in await rates.get_container_rates(route="FBX01")] == [
        "china-us-west-coast"
    ]
    transpacific = await rates.get_container_rates(route="transpacific")
    assert sorted(r["route"] for r in transpacific) == [
        "china-us-east-coast",
        "china-us-west-coast",
    ]


@respx.mock
async def test_fbx_rates_limit_respected() -> None:
    respx.get(url__startswith=_FBX_PAGE).mock(
        return_value=httpx.Response(200, text=_fbx_page_html())
    )
    assert len(await rates.get_container_rates(limit=2)) == 2


@respx.mock
async def test_fbx_rates_http_error_falls_back_to_drewry() -> None:
    respx.get(url__startswith=_FBX_PAGE).mock(return_value=httpx.Response(500, text="boom"))
    respx.get(url__startswith=_DREWRY_INFOGRAM).mock(
        return_value=httpx.Response(200, text=_drewry_infogram_html())
    )
    records = await rates.get_container_rates(limit=20)
    assert len(records) == 2
    composite = next(r for r in records if r["route"] == "wci-composite")
    assert composite["rate_40ft_usd"] == 674.41  # latest point
    assert composite["date"] == "2016-03-17"
    assert composite["index_source"] == "drewry_wci"
    shanghai = next(r for r in records if r["route"] == "shanghai-rotterdam")
    assert shanghai["origin"] == "Shanghai"
    assert shanghai["destination"] == "Rotterdam"
    assert shanghai["rate_40ft_usd"] == 812.0


@respx.mock
async def test_container_rates_both_sources_fail_returns_empty() -> None:
    respx.get(url__startswith=_FBX_PAGE).mock(return_value=httpx.Response(503, text="down"))
    respx.get(url__startswith=_DREWRY_INFOGRAM).mock(return_value=httpx.Response(500, text="down"))
    assert await rates.get_container_rates() == []


@respx.mock
async def test_container_rates_malformed_payload_returns_empty() -> None:
    respx.get(url__startswith=_FBX_PAGE).mock(
        return_value=httpx.Response(200, text="<html>no embedded data</html>")
    )
    respx.get(url__startswith=_DREWRY_INFOGRAM).mock(
        return_value=httpx.Response(200, text="<html>no embedded data</html>")
    )
    assert await rates.get_container_rates() == []


@respx.mock
async def test_fbx_money_parsing_handles_unknown() -> None:
    respx.get(url__startswith=_FBX_PAGE).mock(
        return_value=httpx.Response(
            200,
            text="<script>window.frProductIntroTickerData['x'] = "
            '[{"label": "FBX99", "value": "n/a"}];</script>',
        )
    )
    records = await rates.get_container_rates()
    assert len(records) == 1
    assert records[0]["rate_40ft_usd"] is None
    assert records[0]["route"] == "fbx-fbx99"
    assert records[0]["origin"] is None


# ── FMC contracts ──────────────────────────────────────────────────────


@respx.mock
async def test_fmc_contracts_success() -> None:
    respx.get(url__startswith=_FMC_INDEX).mock(return_value=httpx.Response(200, text=_fmc_html()))
    contracts = await rates.get_fmc_contracts("evergreen", limit=20)
    assert len(contracts) == 1
    first = contracts[0]
    assert first["id"] == "201353-003"
    assert first["carrier"] == "THE Alliance / Evergreen"
    assert first["shipper"] is None
    assert first["commodity"] is None
    assert first["status"] == "Active"
    assert first["effective_date"] == "2021-03-15"


@respx.mock
async def test_fmc_contracts_trade_lanes_and_status() -> None:
    respx.get(url__startswith=_FMC_INDEX).mock(return_value=httpx.Response(200, text=_fmc_html()))
    contracts = await rates.get_fmc_contracts("NEOLINE", limit=20)
    assert len(contracts) == 1
    first = contracts[0]
    assert first["id"] == "201464-001"
    assert "CMA CGM" in first["carrier"]
    assert first["origin"] == "North Europe"
    assert first["destination"] == "US East Coast"
    assert first["status"] == "Active"
    assert first["effective_date"] == "2026-04-20"


@respx.mock
async def test_fmc_contracts_historical_status() -> None:
    respx.get(url__startswith=_FMC_INDEX).mock(return_value=httpx.Response(200, text=_fmc_html()))
    contracts = await rates.get_fmc_contracts("Old Test", limit=20)
    assert len(contracts) == 1
    assert contracts[0]["status"] == "Historical"
    assert contracts[0]["effective_date"] == "2000-01-01"


@respx.mock
async def test_fmc_contracts_query_matches_id_and_lane() -> None:
    respx.get(url__startswith=_FMC_INDEX).mock(return_value=httpx.Response(200, text=_fmc_html()))
    by_id = await rates.get_fmc_contracts("201353")
    assert [c["id"] for c in by_id] == ["201353-003"]
    by_lane = await rates.get_fmc_contracts("US East Coast")
    assert [c["id"] for c in by_lane] == ["201464-001"]


@respx.mock
async def test_fmc_contracts_limit_respected() -> None:
    respx.get(url__startswith=_FMC_INDEX).mock(return_value=httpx.Response(200, text=_fmc_html()))
    # "201" matches both 201353-003 and 201464-001.
    assert len(await rates.get_fmc_contracts("201", limit=1)) == 1
    assert len(await rates.get_fmc_contracts("201", limit=20)) == 2


async def test_fmc_contracts_blank_query_returns_empty() -> None:
    assert await rates.get_fmc_contracts("") == []
    assert await rates.get_fmc_contracts("   ") == []


@respx.mock
async def test_fmc_contracts_http_error_returns_empty() -> None:
    respx.get(url__startswith=_FMC_INDEX).mock(return_value=httpx.Response(500, text="boom"))
    assert await rates.get_fmc_contracts("evergreen") == []


@respx.mock
async def test_fmc_contracts_malformed_html_returns_empty() -> None:
    respx.get(url__startswith=_FMC_INDEX).mock(
        return_value=httpx.Response(200, text="<html><body>nothing here</body></html>")
    )
    assert await rates.get_fmc_contracts("evergreen") == []


@respx.mock
async def test_fmc_contracts_network_error_never_raises() -> None:
    respx.get(url__startswith=_FMC_INDEX).mock(side_effect=httpx.ConnectError("refused"))
    assert await rates.get_fmc_contracts("evergreen") == []


# ── routers ────────────────────────────────────────────────────────────


@pytest.fixture
def freight_app() -> FastAPI:
    app = FastAPI()

    @app.exception_handler(PryError)
    async def pry_error_handler(request: Request, exc: PryError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": str(exc)})

    app.include_router(freight_router)
    return app


def _client(app: FastAPI) -> TestClient:
    return TestClient(app)


def test_packages_importable() -> None:
    assert hasattr(freight_data, "get_container_rates")
    assert hasattr(freight_data, "get_fmc_contracts")
    assert hasattr(freight_router_mod, "router")


def test_freight_router_rates_success(
    freight_app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake(route: str = "all", limit: int = 20) -> list[dict[str, Any]]:
        return [
            {
                "route": "china-us-west-coast",
                "origin": "China",
                "destination": "US West Coast",
                "rate_40ft_usd": 7422.0,
                "index_source": "freightos_fbx",
                "date": "2026-08-14",
            }
        ]

    monkeypatch.setattr(rates, "get_container_rates", fake)
    resp = _client(freight_app).get("/v1/freight/rates", params={"route": "FBX01", "limit": 5})
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["route"] == "FBX01"
    assert body["data"][0]["rate_40ft_usd"] == 7422.0


def test_freight_router_fmc_success(freight_app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake(query: str, limit: int = 20) -> list[dict[str, Any]]:
        return [
            {
                "id": "201353-003",
                "carrier": "THE Alliance / Evergreen",
                "shipper": None,
                "commodity": None,
                "origin": None,
                "destination": None,
                "status": "Active",
                "effective_date": "2021-03-15",
            }
        ]

    monkeypatch.setattr(rates, "get_fmc_contracts", fake)
    resp = _client(freight_app).get("/v1/freight/fmc/contracts", params={"query": "evergreen"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["query"] == "evergreen"
    assert body["data"][0]["id"] == "201353-003"


def test_freight_router_502_when_module_absent(
    freight_app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(freight_router_mod, "_freight_module", lambda name: None)
    assert _client(freight_app).get("/v1/freight/rates").status_code == 502
    assert (
        _client(freight_app)
        .get("/v1/freight/fmc/contracts", params={"query": "evergreen"})
        .status_code
        == 502
    )


def test_freight_router_validation(freight_app: FastAPI) -> None:
    # FMC contracts requires a non-blank query.
    assert _client(freight_app).get("/v1/freight/fmc/contracts").status_code == 422
    assert (
        _client(freight_app).get("/v1/freight/fmc/contracts", params={"query": "   "}).status_code
        == 400
    )
    # Limit bounds on both endpoints.
    assert _client(freight_app).get("/v1/freight/rates", params={"limit": 0}).status_code == 422
    assert _client(freight_app).get("/v1/freight/rates", params={"limit": 201}).status_code == 422
    assert (
        _client(freight_app)
        .get("/v1/freight/fmc/contracts", params={"query": "x", "limit": 0})
        .status_code
        == 422
    )
