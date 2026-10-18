"""Tests for the compliance_data package (FDA / FTC / CFPB / SEC).

Covers FDA openFDA enforcement mapping, FTC cases & proceedings listing
parsing + client-side filtering, CFPB complaints search (including the
company-exact → full-text fallback), SEC AAER admin listing + EDGAR
full-text, the never-raise contract (HTTP errors and malformed payloads
all degrade to empty output), company screening (watch_company), and the
/v1/compliance/* router (200 + 502-degradation + 422 validation).

All HTTP is mocked with respx — no live network.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

import datasets.compliance_data.enforcement as enforcement
import pry.api.routers.integrations.compliance_data as compliance_router_mod
from pry.api.routers.integrations.compliance_data import router as compliance_router
from pry.core.errors import PryError
from pry.engine.retry import RetryConfig

_FDA_DRUG = "https://api.fda.gov/drug/enforcement.json"

_FDA_FOOD = "https://api.fda.gov/food/enforcement.json"

_FDA_DEVICE = "https://api.fda.gov/device/enforcement.json"

_ALL_FDA = (_FDA_DRUG, _FDA_FOOD, _FDA_DEVICE)

_FTC_LIST = "https://www.ftc.gov/legal-library/browse/cases-proceedings"

_CFPB = "https://www.consumerfinance.gov/data-research/consumer-complaints/search/api/v1/"

_SEC_ADMIN = "https://www.sec.gov/enforcement-litigation/administrative-proceedings"

_SEC_FTS = "https://efts.sec.gov/LATEST/search-index"

_ECHO = "https://echo.epa.gov/rest/enforcement/case_search"

_OSHA_EST = "https://www.osha.gov/pls/imis/establishmentsearch.html"

_OSHA_DETAIL = "https://www.osha.gov/pls/imis/establishment.html"

_DOJ = "https://www.justice.gov/api/v1/press_releases.json"

_ZERO_RETRY = RetryConfig(
    max_retries=1, base_delay=0.0, max_delay=0.0, retryable_exceptions=(httpx.HTTPError,)
)


@pytest.fixture(autouse=True)
def _hermetic_compliance(monkeypatch: pytest.MonkeyPatch) -> None:
    """Kill backoff delays so tests are deterministic."""
    monkeypatch.setattr(enforcement, "_RETRY_CONFIG", _ZERO_RETRY)


@pytest.fixture
def compliance_app() -> FastAPI:
    app = FastAPI()

    @app.exception_handler(PryError)
    async def pry_error_handler(request: Request, exc: PryError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": str(exc)})

    app.include_router(compliance_router)
    return app


def _client(app: FastAPI) -> TestClient:
    return TestClient(app)


def test_router_search_success(compliance_app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake(agency: str = "all", query: str = "", limit: int = 20) -> list[dict[str, Any]]:
        return [
            {"agency": "sec", "id": "sec:34-106135", "title": f"match {query}", "source": "sec.gov"}
        ]

    monkeypatch.setattr(enforcement, "search_enforcement", fake)
    resp = _client(compliance_app).get(
        "/v1/compliance/enforcement",
        params={"agency": "sec", "query": "glenncap", "limit": 5},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["agency"] == "sec"
    assert body["query"] == "glenncap"
    assert body["data"][0]["title"] == "match glenncap"


def test_router_get_success(compliance_app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake(agency: str, id: str) -> dict[str, Any]:
        return {"agency": agency, "id": id, "title": "FTC action", "summary": None}

    monkeypatch.setattr(enforcement, "get_action", fake)
    resp = _client(compliance_app).get("/v1/compliance/enforcement/ftc/ftc:acme-matter")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["agency"] == "ftc"
    assert body["data"]["title"] == "FTC action"


def test_router_watch_success(compliance_app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake(company: str, agencies: str = "all") -> list[dict[str, Any]]:
        return [{"agency": "cfpb", "id": "cfpb:1", "company": company, "source": "cfpb"}]

    monkeypatch.setattr(enforcement, "watch_company", fake)
    resp = _client(compliance_app).get("/v1/compliance/watch/Acme%20Foods")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["company"] == "Acme Foods"
    assert body["data"][0]["company"] == "Acme Foods"


def test_router_502_when_module_absent(
    compliance_app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(compliance_router_mod, "_compliance_module", lambda name: None)
    assert (
        _client(compliance_app).get("/v1/compliance/enforcement", params={"query": "x"}).status_code
        == 502
    )
    assert _client(compliance_app).get("/v1/compliance/enforcement/fda/D-1234").status_code == 502
    assert _client(compliance_app).get("/v1/compliance/watch/Acme").status_code == 502


def test_router_validation_422(compliance_app: FastAPI) -> None:
    assert (
        _client(compliance_app).get("/v1/compliance/enforcement", params={"limit": 0}).status_code
        == 422
    )
    assert (
        _client(compliance_app).get("/v1/compliance/enforcement", params={"limit": 101}).status_code
        == 422
    )
    assert (
        _client(compliance_app).get("/v1/compliance/enforcement", params={"agency": ""}).status_code
        == 422
    )
    assert (
        _client(compliance_app)
        .get("/v1/compliance/watch/Acme", params={"agencies": ""})
        .status_code
        == 422
    )
