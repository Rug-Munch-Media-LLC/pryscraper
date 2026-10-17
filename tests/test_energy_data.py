# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for the energy_data package (NYISO DAM LMP + EIA fuel prices).

Covers NYISO day-ahead LMP CSV mapping + trading-day fallback, PJM
key-gating, EIA fuel-price mapping + key-gating, the never-raise contract
(HTTP errors and malformed payloads all degrade to empty output), and the
/v1/energy/* router (200 + 502-degradation + 422 validation).

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

import datasets.energy_data as energy_data
import datasets.energy_data.lmp as lmp
import pry.api.routers.data.energy_data as energy_router_mod
from pry.api.routers.data.energy_data import router as energy_router
from pry.core.errors import PryError
from pry.engine.retry import RetryConfig

_NYISO = "https://mis.nyiso.com/public/csv/damlbmp"
_PJM = "https://dataminer2.pjm.com/feed/da_hrl_lmps"
_EIA = "https://api.eia.gov/v2/petroleum/pri/gnd/data/"
_ERCOT = "https://www.ercot.com/api/1/services/read/dashboards/systemWidePrices.json"
_CAISO = "https://oasis.caiso.com/oasisapi/SingleZip"

# max_retries=0 → single deterministic attempt, zero backoff.
_ZERO_RETRY = RetryConfig(
    max_retries=0, base_delay=0.0, max_delay=0.0, retryable_exceptions=(httpx.HTTPError,)
)


@pytest.fixture(autouse=True)
def _hermetic_energy(monkeypatch: pytest.MonkeyPatch) -> None:
    """Kill backoff delays and clear keys so tests are deterministic."""
    monkeypatch.setattr(lmp, "_RETRY_CONFIG", _ZERO_RETRY)
    monkeypatch.delenv("PRY_PJM_API_KEY", raising=False)
    monkeypatch.delenv("PRY_EIA_API_KEY", raising=False)


# ── Payload fixtures ───────────────────────────────────────────────────


def _nyiso_csv() -> str:
    return (
        "Time Stamp,Name,PTID,LBMP ($/MWHr),Marginal Cost Losses ($/MWHr),"
        "Marginal Cost Congestion ($/MWHr)\n"
        "08/15/2026 00:00,CAPITL,61757,42.97,1.13,0.00\n"
        "08/15/2026 00:00,CENTRL,61754,41.67,-0.17,0.00\n"
        "08/15/2026 01:00,CAPITL,61757,43.10,1.20,0.00\n"
    )


def _pjm_payload() -> list[dict[str, Any]]:
    return [
        {
            "datetime_beginning_utc": "2026-08-15 04:00:00",
            "node_id": "5106421",
            "type": "LD",
            "marginal_cost_lmp": 38.44,
        },
        {
            "datetime_beginning_utc": "2026-08-15 04:00:00",
            "node_id": "5106422",
            "type": "LD",
            "marginal_cost_lmp": 39.01,
        },
    ]


def _eia_payload() -> dict[str, Any]:
    return {
        "response": {
            "total": "3",
            "dateFormat": "YYYY-MM-DD",
            "frequency": "weekly",
            "data": [
                {
                    "period": "2026-08-10",
                    "duoarea": "NUS",
                    "area-name": "U.S.",
                    "product": "EDI0",
                    "process": "PTE",
                    "value": "3.772",
                    "units": "$/GAL",
                },
                {
                    "period": "2026-08-10",
                    "duoarea": "NUS",
                    "area-name": "U.S.",
                    "product": "EPD0",
                    "process": "PTE",
                    "value": "4.501",
                    "units": "$/GAL",
                },
                {
                    "period": "2026-08-10",
                    "duoarea": "NUS",
                    "area-name": "U.S.",
                    "product": "EPM0",
                    "process": "PTE",
                    "value": "4.141",
                    "units": "$/GAL",
                },
            ],
        },
        "request": {"command": "/v2/petroleum/pri/gnd/data/"},
    }


def _ercot_payload() -> dict[str, Any]:
    return {
        "rtSppData": [
            {"interval": "08/15/2026 14:30", "hbBusAvg": 45.12},
            {"interval": "08/15/2026 14:15", "hbBusAvg": 44.98},
        ]
    }


def _caiso_zip() -> bytes:
    csv_text = (
        "INTERVALSTARTTIME,NODE_ID,LMP_PRICE\n"
        "2026-08-15T04:00:00-00:00,TH_NP15_GEN-APND,38.50\n"
        "2026-08-15T04:00:00-00:00,TH_SP15_GEN-APND,39.10\n"
    )
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("lmp.csv", csv_text)
    return buf.getvalue()


# ── get_lmp: NYISO ────────────────────────────────────────────────────


@respx.mock
async def test_get_lmp_nyiso_success() -> None:
    respx.get(url__startswith=_NYISO).mock(return_value=httpx.Response(200, text=_nyiso_csv()))
    results = await lmp.get_lmp(region="nyiso", date="2026-08-15")
    assert len(results) == 3
    record = results[0]
    assert record["region"] == "nyiso"
    assert record["node"] == "CAPITL"
    assert record["timestamp"] == "2026-08-15T04:00:00+00:00"  # ET 00:00 -> UTC 04:00
    assert record["price_usd_mwh"] == 42.97
    assert record["lmp_type"] == "DAM"
    assert results[1]["node"] == "CENTRL"
    assert results[1]["price_usd_mwh"] == 41.67
    assert results[2]["timestamp"] == "2026-08-15T05:00:00+00:00"


@respx.mock
async def test_get_lmp_region_all_fetches_keyless_sources() -> None:
    # NYISO, ERCOT and CAISO are all keyless; PJM still needs PRY_PJM_API_KEY.
    respx.get(url__startswith=_NYISO).mock(return_value=httpx.Response(200, text=_nyiso_csv()))
    respx.get(url=_ERCOT).mock(return_value=httpx.Response(200, json=_ercot_payload()))
    respx.get(url__startswith=_CAISO).mock(return_value=httpx.Response(200, content=_caiso_zip()))
    results = await lmp.get_lmp(region="all", date="2026-08-15")
    regions = {r["region"] for r in results}
    expected = {"nyiso", "ercot", "caiso"}
    assert regions == expected
    assert len([r for r in results if r["region"] == "nyiso"]) == 3
    assert len([r for r in results if r["region"] == "ercot"]) == 2
    assert len([r for r in results if r["region"] == "caiso"]) == 2
    assert respx.calls.call_count == 3


@respx.mock
async def test_get_lmp_date_fallback_to_prior_day() -> None:
    respx.get(url__startswith=f"{_NYISO}/20260816").mock(return_value=httpx.Response(404))
    respx.get(url__startswith=f"{_NYISO}/20260815").mock(
        return_value=httpx.Response(200, text=_nyiso_csv())
    )
    results = await lmp.get_lmp(region="nyiso", date="2026-08-16")
    assert len(results) == 3
    assert results[0]["node"] == "CAPITL"
    assert respx.calls.call_count == 2


@respx.mock
async def test_get_lmp_unknown_region_returns_empty() -> None:
    assert await lmp.get_lmp(region="miso", date="2026-08-15") == []
    assert respx.calls.call_count == 0


@respx.mock
async def test_get_lmp_invalid_date_returns_empty() -> None:
    assert await lmp.get_lmp(region="nyiso", date="not-a-date") == []
    assert respx.calls.call_count == 0


@respx.mock
async def test_get_lmp_http_error_returns_empty() -> None:
    respx.get(url__startswith=_NYISO).mock(return_value=httpx.Response(500))
    assert await lmp.get_lmp(region="nyiso", date="2026-08-15") == []
    # 4 candidate dates (3 fallback + requested) x 1 attempt each
    assert respx.calls.call_count == 4


@respx.mock
async def test_get_lmp_malformed_payload_returns_empty() -> None:
    respx.get(url__startswith=_NYISO).mock(
        return_value=httpx.Response(200, text="<html>not a csv</html>")
    )
    assert await lmp.get_lmp(region="nyiso", date="2026-08-15") == []
    assert respx.calls.call_count == 4


# ── get_lmp: PJM ──────────────────────────────────────────────────────


@respx.mock
async def test_get_lmp_pjm_with_key_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PRY_PJM_API_KEY", "test-key")
    respx.get(url__startswith=_PJM).mock(return_value=httpx.Response(200, json=_pjm_payload()))
    results = await lmp.get_lmp(region="pjm", date="2026-08-15")
    assert len(results) == 2
    record = results[0]
    assert record["region"] == "pjm"
    assert record["node"] == "5106421"
    assert record["timestamp"] == "2026-08-15T04:00:00+00:00"
    assert record["price_usd_mwh"] == 38.44
    assert record["lmp_type"] == "LD"


@respx.mock
async def test_get_lmp_pjm_without_key_returns_empty() -> None:
    assert await lmp.get_lmp(region="pjm", date="2026-08-15") == []
    assert respx.calls.call_count == 0


@respx.mock
async def test_get_lmp_pjm_http_error_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PRY_PJM_API_KEY", "test-key")
    respx.get(url__startswith=_PJM).mock(return_value=httpx.Response(500))
    assert await lmp.get_lmp(region="pjm", date="2026-08-15") == []


# ── get_lmp: ERCOT (keyless dashboard) ────────────────────────────────


@respx.mock
async def test_get_lmp_ercot_success() -> None:
    respx.get(url=_ERCOT).mock(return_value=httpx.Response(200, json=_ercot_payload()))
    results = await lmp.get_lmp(region="ercot", date="2026-08-15")
    assert len(results) == 2
    record = results[0]
    assert record["region"] == "ercot"
    assert record["node"] == "HB_BUS_AVG"
    assert record["timestamp"] == "2026-08-15T19:30:00+00:00"  # CT 14:30 -> UTC 19:30
    assert record["price_usd_mwh"] == 45.12
    assert record["lmp_type"] == "RTM"


@respx.mock
async def test_get_lmp_ercot_http_error_returns_empty() -> None:
    respx.get(url=_ERCOT).mock(return_value=httpx.Response(500))
    assert await lmp.get_lmp(region="ercot", date="2026-08-15") == []


@respx.mock
async def test_get_lmp_ercot_malformed_payload_returns_empty() -> None:
    respx.get(url=_ERCOT).mock(return_value=httpx.Response(200, json={"nope": 1}))
    assert await lmp.get_lmp(region="ercot", date="2026-08-15") == []


# ── get_lmp: CAISO OASIS ──────────────────────────────────────────────


@respx.mock
async def test_get_lmp_caiso_success() -> None:
    respx.get(url__startswith=_CAISO).mock(return_value=httpx.Response(200, content=_caiso_zip()))
    results = await lmp.get_lmp(region="caiso", date="2026-08-15")
    assert len(results) == 2
    record = results[0]
    assert record["region"] == "caiso"
    assert record["node"] == "TH_NP15_GEN-APND"
    assert record["timestamp"] == "2026-08-15T04:00:00+00:00"
    assert record["price_usd_mwh"] == 38.50
    assert record["lmp_type"] == "RTM"


@respx.mock
async def test_get_lmp_caiso_http_error_returns_empty() -> None:
    respx.get(url__startswith=_CAISO).mock(return_value=httpx.Response(500))
    assert await lmp.get_lmp(region="caiso", date="2026-08-15") == []


@respx.mock
async def test_get_lmp_caiso_bad_zip_returns_empty() -> None:
    respx.get(url__startswith=_CAISO).mock(
        return_value=httpx.Response(200, content=b"<html>not a zip</html>")
    )
    assert await lmp.get_lmp(region="caiso", date="2026-08-15") == []


# ── get_fuel_prices: EIA ──────────────────────────────────────────────


@respx.mock
async def test_get_fuel_prices_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRY_EIA_API_KEY", "test-key")
    respx.get(url__startswith=_EIA).mock(return_value=httpx.Response(200, json=_eia_payload()))
    results = await lmp.get_fuel_prices(region="us")
    assert len(results) == 3
    by_fuel = {r["fuel"]: r for r in results}
    assert by_fuel["gasoline"]["region"] == "us"
    assert by_fuel["gasoline"]["price"] == 4.141
    assert by_fuel["gasoline"]["unit"] == "$/GAL"
    assert by_fuel["gasoline"]["date"] == "2026-08-10"
    assert by_fuel["premium gasoline"]["price"] == 4.501
    assert by_fuel["diesel"]["price"] == 3.772


@respx.mock
async def test_get_fuel_prices_all_areas(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRY_EIA_API_KEY", "test-key")
    respx.get(url__startswith=_EIA).mock(return_value=httpx.Response(200, json=_eia_payload()))
    results = await lmp.get_fuel_prices(region="all")
    # 6 EIA areas (NUS + 5 PADDs) x 3 products
    assert len(results) == 18
    assert respx.calls.call_count == 6
    regions = {r["region"] for r in results}
    expected = {"us", "padd1", "padd2", "padd3", "padd4", "padd5"}
    assert regions == expected


@respx.mock
async def test_get_fuel_prices_no_key_returns_empty() -> None:
    assert await lmp.get_fuel_prices(region="us") == []
    assert respx.calls.call_count == 0


@respx.mock
async def test_get_fuel_prices_http_error_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PRY_EIA_API_KEY", "test-key")
    respx.get(url__startswith=_EIA).mock(return_value=httpx.Response(500))
    assert await lmp.get_fuel_prices(region="us") == []


@respx.mock
async def test_get_fuel_prices_malformed_payload_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PRY_EIA_API_KEY", "test-key")
    respx.get(url__startswith=_EIA).mock(return_value=httpx.Response(200, json={"nope": True}))
    assert await lmp.get_fuel_prices(region="us") == []


@respx.mock
async def test_get_fuel_prices_unknown_region_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PRY_EIA_API_KEY", "test-key")
    assert await lmp.get_fuel_prices(region="mars") == []
    assert respx.calls.call_count == 0


# ── router ─────────────────────────────────────────────────────────────


@pytest.fixture
def energy_app() -> FastAPI:
    app = FastAPI()

    @app.exception_handler(PryError)
    async def pry_error_handler(request: Request, exc: PryError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": str(exc)})

    app.include_router(energy_router)
    return app


def _client(app: FastAPI) -> TestClient:
    return TestClient(app)


def test_router_importable() -> None:
    assert hasattr(energy_data, "get_lmp")
    assert hasattr(energy_data, "get_fuel_prices")
    assert hasattr(energy_router_mod, "router")


def test_router_lmp_success(energy_app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake(region: str = "all", date: str = "today") -> list[dict[str, Any]]:
        return [
            {
                "region": region,
                "node": "CAPITL",
                "timestamp": "2026-08-15T04:00:00+00:00",
                "price_usd_mwh": 42.97,
                "lmp_type": "DAM",
            }
        ]

    monkeypatch.setattr(lmp, "get_lmp", fake)
    resp = _client(energy_app).get(
        "/v1/energy/lmp", params={"region": "nyiso", "date": "2026-08-15"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["region"] == "nyiso"
    assert body["date"] == "2026-08-15"
    assert body["data"][0]["node"] == "CAPITL"


def test_router_fuel_prices_success(energy_app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake(region: str = "all") -> list[dict[str, Any]]:
        return [
            {
                "region": region,
                "fuel": "gasoline",
                "price": 4.141,
                "unit": "$/GAL",
                "date": "2026-08-10",
            }
        ]

    monkeypatch.setattr(lmp, "get_fuel_prices", fake)
    resp = _client(energy_app).get("/v1/energy/fuel-prices", params={"region": "us"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["region"] == "us"
    assert body["data"][0]["fuel"] == "gasoline"


def test_router_502_when_module_absent(
    energy_app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(energy_router_mod, "_energy_module", lambda name: None)
    assert _client(energy_app).get("/v1/energy/lmp").status_code == 502
    assert _client(energy_app).get("/v1/energy/fuel-prices").status_code == 502


def test_router_validation_422(energy_app: FastAPI) -> None:
    assert _client(energy_app).get("/v1/energy/lmp", params={"region": ""}).status_code == 422
    assert _client(energy_app).get("/v1/energy/lmp", params={"date": ""}).status_code == 422
    assert (
        _client(energy_app).get("/v1/energy/fuel-prices", params={"region": ""}).status_code == 422
    )
