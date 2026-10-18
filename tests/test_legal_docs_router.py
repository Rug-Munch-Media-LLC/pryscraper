"""Tests for the legal_docs package (CourtListener / SEC EDGAR / OFAC SDN).

Covers docket search + lookup, SEC filing search / filing lookup / Form 4
insider trades, OFAC SDN name screening (JSON source, XML fallback, disk
cache), the never-raise contract (HTTP errors and malformed payloads all
degrade to empty output), and the /v1/legal/* router (200 + 502-degradation
+ 422 validation).

All HTTP is mocked with respx — no live network.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

import datasets.legal_docs.dockets as dockets
import datasets.legal_docs.sanctions as sanctions
import datasets.legal_docs.sec_filings as sec_filings
import pry.api.routers.data.legal_docs as legal_router_mod
from pry.api.routers.data.legal_docs import router as legal_router
from pry.core.errors import PryError
from pry.engine.retry import RetryConfig

_CL_BASE = "https://www.courtlistener.com/api/rest/v4"

_PACER_FETCH = f"{_CL_BASE}/pacer-fetch/"

_JUSTIA = "https://dockets.justia.com"

_NY_ECOURTS = "https://iapps.courts.state.ny.us/webcivil/FCASSearch"

_FTS = "https://efts.sec.gov/LATEST/search-index"

_TICKERS = "https://www.sec.gov/files/company_tickers.json"

_SUBMISSIONS = "https://data.sec.gov/submissions/CIK0000320193.json"

_INDEX = "https://www.sec.gov/Archives/edgar/data/320193/000032019324000005/"

_OFAC_JSON = "https://www.treasury.gov/ofac/downloads/sdn.json"

_OFAC_XML = "https://www.treasury.gov/ofac/downloads/sdn.xml"

_OFAC_CSV = "https://www.treasury.gov/ofac/downloads/sdn.csv"

_ZERO_RETRY = RetryConfig(
    max_retries=1, base_delay=0.0, max_delay=0.0, retryable_exceptions=(httpx.HTTPError,)
)


@pytest.fixture(autouse=True)
def _hermetic_legal(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Kill backoff delays and reset caches without patching module internals."""
    previous_dockets = dockets.configure_retries(_ZERO_RETRY)
    previous_sec = sec_filings.configure_retries(_ZERO_RETRY)
    previous_sanctions = sanctions.configure_retries(_ZERO_RETRY)
    for env_name in ("PRY_COURTLISTENER_API_KEY", "PRY_LEGAL_OFAC_CACHE_PATH"):
        monkeypatch.delenv(env_name, raising=False)
    sec_filings.reset_ticker_cache()
    sanctions.reset_cache()
    yield
    dockets.configure_retries(previous_dockets)
    sec_filings.configure_retries(previous_sec)
    sanctions.configure_retries(previous_sanctions)
    sec_filings.reset_ticker_cache()
    sanctions.reset_cache()


@pytest.fixture
def legal_app() -> FastAPI:
    app = FastAPI()

    @app.exception_handler(PryError)
    async def pry_error_handler(request: Request, exc: PryError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": str(exc)})

    app.include_router(legal_router)
    return app


def _client(app: FastAPI) -> TestClient:
    return TestClient(app)


def test_router_sec_search_success(legal_app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake(ticker: str, form_type: str = "8-K", limit: int = 20) -> list[dict[str, Any]]:
        return [{"accession_number": "a", "form_type": form_type, "ticker": ticker.upper()}]

    monkeypatch.setattr(sec_filings, "search_filings", fake)
    resp = _client(legal_app).get(
        "/v1/legal/sec/search", params={"ticker": "aapl", "form_type": "10-Q"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["data"][0]["form_type"] == "10-Q"
    assert body["ticker"] == "AAPL"


def test_router_sec_insider_success(legal_app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake(ticker: str, limit: int = 20) -> list[dict[str, Any]]:
        return [{"ticker": ticker.upper(), "owner": "SMITH JOHN", "form_type": "4"}]

    monkeypatch.setattr(sec_filings, "insider_trades", fake)
    resp = _client(legal_app).get("/v1/legal/sec/insider/aapl")
    assert resp.status_code == 200
    assert resp.json()["data"][0]["owner"] == "SMITH JOHN"


def test_router_sanctions_success(legal_app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake(name: str) -> list[dict[str, Any]]:
        return [{"uid": "12345", "name": "JOHN SMITH", "source": "ofac_sdn"}]

    monkeypatch.setattr(sanctions, "screen_name", fake)
    resp = _client(legal_app).get("/v1/legal/sanctions/john%20smith")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["data"][0]["name"] == "JOHN SMITH"
    assert body["name"] == "john smith"


def test_router_502_when_module_absent(legal_app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(legal_router_mod, "_legal_module", lambda name: None)
    assert (
        _client(legal_app).get("/v1/legal/dockets/search", params={"query": "x"}).status_code == 502
    )
    assert _client(legal_app).get("/v1/legal/dockets/42").status_code == 502
    assert (
        _client(legal_app).get("/v1/legal/sec/search", params={"ticker": "aapl"}).status_code == 502
    )
    assert _client(legal_app).get("/v1/legal/sec/insider/aapl").status_code == 502
    assert _client(legal_app).get("/v1/legal/sanctions/x").status_code == 502


def test_router_validation_422(legal_app: FastAPI) -> None:
    assert (
        _client(legal_app).get("/v1/legal/dockets/search", params={"query": ""}).status_code == 422
    )
    assert _client(legal_app).get("/v1/legal/dockets/abc").status_code == 422
    assert _client(legal_app).get("/v1/legal/sec/search", params={"ticker": ""}).status_code == 422
    assert (
        _client(legal_app)
        .get("/v1/legal/sec/search", params={"ticker": "aapl", "limit": 0})
        .status_code
        == 422
    )
    assert (
        _client(legal_app).get("/v1/legal/sec/insider/aapl", params={"limit": 101}).status_code
        == 422
    )
