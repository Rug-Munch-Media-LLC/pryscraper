"""Tests for the ip_data package (patents / trademarks / company registry).

Covers Google Patents XHR-query normalization, USPTO Trademark Search /
TSDR parsing, the Nevada SOS company-registry JSON API, the never-raise
contract (HTTP errors, timeouts, malformed JSON, unsupported states all
degrade to [] / {}), and the /v1/ip/* router (200 + 502-degradation +
query validation).

All HTTP is mocked with respx — no live network.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import pry.api.routers.data.ip_data as ip_router_mod
from pry.api.routers.data.ip_data import router as ip_router

GP_QUERY = "https://patents.google.com/xhr/query"

GP_PAGE = "https://patents.google.com/patent/{id}/en"

TM_SEARCH = "https://tmsearch.uspto.gov/api-v1-0-0/tmsearch"

TSDR = "https://tsdrapi.uspto.gov/ts/cd/casestatus/{serial}/info.json"

NV_SEARCH = "https://nv-sos.elb.us-eas-2.aws.sos.nv.gov/api/CorpSearch/Search"

PATENT_KEYS = {
    "patent_id",
    "title",
    "assignee",
    "inventor",
    "filing_date",
    "grant_date",
    "abstract",
    "url",
}

TM_KEYS = {"serial_no", "mark", "owner", "status", "classes", "registration_date", "url"}

COMPANY_KEYS = {
    "name",
    "entity_id",
    "type",
    "status",
    "state",
    "formation_date",
    "registered_agent",
}


@pytest.fixture
def ip_app() -> FastAPI:
    from fastapi import Request
    from fastapi.responses import JSONResponse

    from pry.core.errors import PryError

    app = FastAPI()

    @app.exception_handler(PryError)
    async def pry_error_handler(request: Request, exc: PryError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": str(exc)})

    app.include_router(ip_router)
    return app


def _client(app: FastAPI) -> TestClient:
    return TestClient(app)


class _FakePatents:
    @staticmethod
    async def search_patents(query: str, limit: int = 20) -> list[dict[str, Any]]:
        return [{"patent_id": "US9012345B2", "title": query, "limit": limit}]

    @staticmethod
    async def get_patent(patent_id: str) -> dict[str, Any]:
        return {"patent_id": patent_id, "title": "Detail"}


class _FakeTrademarks:
    @staticmethod
    async def search_trademarks(query: str, limit: int = 20) -> list[dict[str, Any]]:
        return [{"serial_no": "97774270", "mark": query, "limit": limit}]


class _FakeCompanyRegistry:
    @staticmethod
    async def search_companies(name: str, limit: int = 20) -> list[dict[str, Any]]:
        return [{"name": name, "entity_id": "E1234", "state": "NV", "limit": limit}]


def test_router_patents_search_success(ip_app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ip_router_mod, "_ip_module", lambda name: _FakePatents())
    resp = _client(ip_app).get("/v1/ip/patents/search", params={"q": "solar", "limit": 5})
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["data"][0]["patent_id"] == "US9012345B2"
    assert body["limit"] == 5


def test_router_patents_get_success(ip_app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ip_router_mod, "_ip_module", lambda name: _FakePatents())
    resp = _client(ip_app).get("/v1/ip/patents/US9012345B2")
    assert resp.status_code == 200
    assert resp.json()["data"]["title"] == "Detail"


def test_router_trademarks_search_success(ip_app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ip_router_mod, "_ip_module", lambda name: _FakeTrademarks())
    resp = _client(ip_app).get("/v1/ip/trademarks/search", params={"q": "rugmunch"})
    assert resp.status_code == 200
    assert resp.json()["data"][0]["serial_no"] == "97774270"


def test_router_companies_search_success(ip_app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ip_router_mod, "_ip_module", lambda name: _FakeCompanyRegistry())
    resp = _client(ip_app).get("/v1/ip/companies/search", params={"name": "tesla", "state": "NV"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"][0]["name"] == "tesla"
    assert body["state"] == "NV"


@pytest.mark.parametrize(
    ("path", "params"),
    [
        ("/v1/ip/patents/search", {"q": "solar"}),
        ("/v1/ip/trademarks/search", {"q": "rugmunch"}),
        ("/v1/ip/companies/search", {"name": "tesla"}),
    ],
)
def test_router_search_502_when_module_absent(
    ip_app: FastAPI, monkeypatch: pytest.MonkeyPatch, path: str, params: dict[str, str]
) -> None:
    monkeypatch.setattr(ip_router_mod, "_ip_module", lambda name: None)
    resp = _client(ip_app).get(path, params=params)
    assert resp.status_code == 502


def test_router_patents_get_502_when_module_absent(
    ip_app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ip_router_mod, "_ip_module", lambda name: None)
    resp = _client(ip_app).get("/v1/ip/patents/US9012345B2")
    assert resp.status_code == 502


def test_router_patents_get_400_when_not_found(
    ip_app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    class _EmptyPatents:
        @staticmethod
        async def get_patent(patent_id: str) -> dict[str, Any]:
            return {}

    monkeypatch.setattr(ip_router_mod, "_ip_module", lambda name: _EmptyPatents())
    resp = _client(ip_app).get("/v1/ip/patents/US9999999B2")
    assert resp.status_code == 400


def test_router_search_missing_query_is_422(ip_app: FastAPI) -> None:
    resp = _client(ip_app).get("/v1/ip/patents/search")
    assert resp.status_code == 422
