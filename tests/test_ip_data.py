# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
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

import httpx
import pytest
import respx
from fastapi import FastAPI
from fastapi.testclient import TestClient

import datasets.ip_data.company_registry as company_registry
import datasets.ip_data.patents as patents
import datasets.ip_data.trademarks as trademarks
import pry.api.routers.data.ip_data as ip_router_mod
from datasets.ip_data import search_patents
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


# ── Fixtures / payload builders ─────────────────────────────────────────


def _gp_doc(
    patent_id: str = "US9012345B2",
    title: str = "Solar panel array",
    assignee: str = "Tesla Inc",
    inventor: str = "Elon M",
    filing_date: str = "2020-01-15",
    publication_date: str = "2021-06-30",
    snippet: str = "A wind-resistant solar panel array…",
) -> dict[str, Any]:
    return {
        "id": f"patent/{patent_id}/en",
        "rank": 0,
        "patent": {
            "title": title,
            "snippet": snippet,
            "filing_date": filing_date,
            "publication_date": publication_date,
            "inventor": inventor,
            "assignee": assignee,
            "publication_number": patent_id,
            "language": "en",
        },
    }


def _gp_payload(*docs: dict[str, Any]) -> dict[str, Any]:
    return {
        "results": {
            "total_num_results": len(docs),
            "total_num_pages": 1,
            "cluster": [{"result": list(docs)}],
        }
    }


def _tm_doc(
    serial: str = "97774270",
    mark: str = "RUGMUNCH",
    owner: str = "Rug Munch Media LLC",
    status: str = "Live/Registered",
    classes: list[dict[str, str]] | None = None,
    reg_date: str = "2024-03-01",
) -> dict[str, Any]:
    return {
        "serialNumber": serial,
        "markIdentification": mark,
        "partyName": owner,
        "status": status,
        "classifications": classes if classes is not None else [{"classNumber": "36"}],
        "registrationDate": reg_date,
    }


def _nv_row(
    name: str = "TESLA INC",
    entity_id: str = "E1234567-8",
    entity_type: str = "Foreign Corporation",
    status: str = "Active",
    formation_date: str = "2012-05-31",
    agent: str = "C T Corporation System",
) -> dict[str, Any]:
    return {
        "businessName": name,
        "businessId": entity_id,
        "entityType": entity_type,
        "status": status,
        "formationDate": formation_date,
        "registeredAgentName": agent,
    }


def _assert_company_schema(entry: dict[str, Any]) -> None:
    assert set(entry) == COMPANY_KEYS
    assert entry["state"] == "NV"


# ── Package importability ───────────────────────────────────────────────


def test_package_importable() -> None:
    import datasets.ip_data as ip_data
    import pry.api.routers.data.ip_data  # noqa: F401

    assert callable(ip_data.search_patents)
    assert hasattr(ip_router_mod, "router")


# ── patents.search_patents ──────────────────────────────────────────────


@respx.mock
async def test_search_patents_normalizes_gp_payload() -> None:
    respx.get(url__startswith=GP_QUERY).mock(
        return_value=httpx.Response(200, json=_gp_payload(_gp_doc()))
    )
    results = await search_patents("solar panel")
    assert len(results) == 1
    entry = results[0]
    assert set(entry) == PATENT_KEYS
    assert entry["patent_id"] == "US9012345B2"
    assert entry["title"] == "Solar panel array"
    assert entry["assignee"] == "Tesla Inc"
    assert entry["inventor"] == "Elon M"
    assert entry["filing_date"] == "2020-01-15"
    assert entry["grant_date"] == "2021-06-30"  # B2 kind code => granted
    assert "solar panel array" in entry["abstract"].lower()
    assert entry["url"] == "https://patents.google.com/patent/US9012345B2/en"


@respx.mock
async def test_search_patents_grant_date_empty_for_application_docs() -> None:
    respx.get(url__startswith=GP_QUERY).mock(
        return_value=httpx.Response(200, json=_gp_payload(_gp_doc(patent_id="US20240123456A1")))
    )
    results = await search_patents("application doc")
    assert results[0]["grant_date"] == ""


@respx.mock
async def test_search_patents_multiple_clusters_flattened_and_limited() -> None:
    docs = [_gp_doc(patent_id=f"US{1000000 + i}B2", title=f"Patent {i}") for i in range(5)]
    payload = {
        "results": {
            "total_num_results": 5,
            "cluster": [{"result": docs[:2]}, {"result": docs[2:]}],
        }
    }
    respx.get(url__startswith=GP_QUERY).mock(return_value=httpx.Response(200, json=payload))
    results = await search_patents("many", limit=3)
    assert len(results) == 3
    assert [r["patent_id"] for r in results] == [f"US{1000000 + i}B2" for i in range(3)]


@respx.mock
async def test_search_patents_never_raises_on_http_error() -> None:
    respx.get(url__startswith=GP_QUERY).mock(return_value=httpx.Response(500, text="boom"))
    assert await search_patents("solar") == []
    assert respx.calls.call_count == 1


@respx.mock
async def test_search_patents_never_raises_on_timeout() -> None:
    respx.get(url__startswith=GP_QUERY).mock(side_effect=httpx.ReadTimeout("read timed out"))
    assert await search_patents("solar") == []
    assert respx.calls.call_count == 1


@respx.mock
async def test_search_patents_never_raises_on_bad_json() -> None:
    respx.get(url__startswith=GP_QUERY).mock(
        return_value=httpx.Response(200, content=b"<html>not json</html>")
    )
    assert await search_patents("solar") == []
    assert respx.calls.call_count == 1


@respx.mock
async def test_search_patents_empty_query_returns_empty() -> None:
    assert await search_patents("   ") == []
    assert respx.calls.call_count == 0


@respx.mock
async def test_search_patents_non_string_inputs_never_raise() -> None:
    assert await search_patents(None) == []  # type: ignore[arg-type]
    respx.get(url__startswith=GP_QUERY).mock(
        return_value=httpx.Response(200, json=_gp_payload(_gp_doc()))
    )
    results = await search_patents(12345)  # type: ignore[arg-type]
    assert results[0]["patent_id"] == "US9012345B2"  # int coerced to str query


# ── patents.get_patent ──────────────────────────────────────────────────


@respx.mock
async def test_get_patent_exact_match_enriches_abstract() -> None:
    respx.get(url__startswith=GP_QUERY).mock(
        return_value=httpx.Response(200, json=_gp_payload(_gp_doc(snippet="short snippet")))
    )
    respx.get(GP_PAGE.format(id="US9012345B2")).mock(
        return_value=httpx.Response(
            200,
            text='<html><head><meta name="description" content="Full abstract here.">'
            "</head><body>patent page</body></html>",
        )
    )
    result = await patents.get_patent("us9012345b2")  # case-insensitive
    assert result["patent_id"] == "US9012345B2"
    assert result["abstract"] == "Full abstract here."


@respx.mock
async def test_get_patent_keeps_snippet_when_detail_page_fails() -> None:
    respx.get(url__startswith=GP_QUERY).mock(
        return_value=httpx.Response(200, json=_gp_payload(_gp_doc(snippet="fallback snippet")))
    )
    respx.get(GP_PAGE.format(id="US9012345B2")).mock(return_value=httpx.Response(500, text="boom"))
    result = await patents.get_patent("US9012345B2")
    assert result["patent_id"] == "US9012345B2"
    assert result["abstract"] == "fallback snippet"


@respx.mock
async def test_get_patent_not_found_returns_empty_dict() -> None:
    respx.get(url__startswith=GP_QUERY).mock(
        return_value=httpx.Response(200, json=_gp_payload(_gp_doc(patent_id="US9999999B2")))
    )
    assert await patents.get_patent("US1111111B2") == {}
    assert respx.calls.call_count == 1


@respx.mock
async def test_get_patent_never_raises_on_network_error() -> None:
    respx.get(url__startswith=GP_QUERY).mock(side_effect=httpx.ConnectError("connection refused"))
    assert await patents.get_patent("US9012345B2") == {}
    assert respx.calls.call_count == 1


async def test_get_patent_empty_id_returns_empty_dict() -> None:
    assert await patents.get_patent("") == {}
    assert respx.calls.call_count == 0


# ── trademarks.search_trademarks ────────────────────────────────────────


@respx.mock
async def test_search_trademarks_normalizes_solr_docs() -> None:
    respx.post(TM_SEARCH).mock(
        return_value=httpx.Response(
            200,
            json={"response": {"numFound": 1, "docs": [_tm_doc()]}},
        )
    )
    results = await trademarks.search_trademarks("rugmunch")
    assert len(results) == 1
    entry = results[0]
    assert set(entry) == TM_KEYS
    assert entry["serial_no"] == "97774270"
    assert entry["mark"] == "RUGMUNCH"
    assert entry["owner"] == "Rug Munch Media LLC"
    assert entry["status"] == "Live/Registered"
    expected = ["36"]
    assert entry["classes"] == expected
    assert entry["registration_date"] == "2024-03-01"
    assert "97774270" in entry["url"]


@respx.mock
async def test_search_trademarks_parses_variant_field_shapes() -> None:
    doc = {
        "applicationNumber": "12345",
        "wordMark": "ACME",
        "ownerName": "ACME Corp",
        "applicationStatus": "Live/Pending",
        "internationalClasses": ["9", "42"],
        "caseFile": {"partyName": "ignored"},
    }
    respx.post(TM_SEARCH).mock(return_value=httpx.Response(200, json={"response": {"docs": [doc]}}))
    results = await trademarks.search_trademarks("acme")
    entry = results[0]
    assert entry["serial_no"] == "12345"
    assert entry["mark"] == "ACME"
    assert entry["owner"] == "ACME Corp"
    expected = ["9", "42"]
    assert entry["classes"] == expected


@respx.mock
async def test_search_trademarks_never_raises_on_error() -> None:
    respx.post(TM_SEARCH).mock(side_effect=httpx.ConnectError("connection refused"))
    assert await trademarks.search_trademarks("rugmunch") == []
    assert respx.calls.call_count == 1


@respx.mock
async def test_search_trademarks_never_raises_on_bad_json() -> None:
    respx.post(TM_SEARCH).mock(return_value=httpx.Response(200, content=b"<html></html>"))
    assert await trademarks.search_trademarks("rugmunch") == []
    assert respx.calls.call_count == 1


async def test_search_trademarks_empty_query_returns_empty() -> None:
    assert await trademarks.search_trademarks("") == []
    assert respx.calls.call_count == 0


@respx.mock
async def test_search_trademarks_bad_limit_never_raises() -> None:
    respx.post(TM_SEARCH).mock(
        return_value=httpx.Response(200, json={"response": {"docs": [_tm_doc()]}})
    )
    results = await trademarks.search_trademarks("rugmunch", limit="abc")  # type: ignore[arg-type]
    assert len(results) == 1  # clamps to default 20, request still succeeds


# ── trademarks.get_trademark ────────────────────────────────────────────


@respx.mock
async def test_get_trademark_parses_tsdr_payload() -> None:
    serial = "97774270"
    respx.get(TSDR.format(serial=serial)).mock(
        return_value=httpx.Response(
            200,
            json={
                "response": {
                    "serialNumber": serial,
                    "mark": "RUGMUNCH",
                    "ownerName": "Rug Munch Media LLC",
                    "status": "Registered",
                    "application Filing Date": "2022-01-01",
                    "registrationDate": "2024-03-01",
                    "goodAndServices": "Financial services",
                    "classifications": [{"classNumber": "36"}],
                }
            },
        )
    )
    result = await trademarks.get_trademark(serial)
    assert result["serial_no"] == serial
    assert result["mark"] == "RUGMUNCH"
    assert result["owner"] == "Rug Munch Media LLC"
    assert result["status"] == "Registered"
    assert result["filing_date"] == "2022-01-01"
    assert result["registration_date"] == "2024-03-01"
    assert result["goods_services"] == "Financial services"
    expected = ["36"]
    assert result["classes"] == expected


@respx.mock
async def test_get_trademark_uses_api_key_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    serial = "97774270"
    monkeypatch.setenv("USPTO_API_KEY", "test-key-123")
    respx.get(url__startswith=TSDR.format(serial=serial)).mock(
        return_value=httpx.Response(200, json={"response": {"serialNumber": serial}})
    )
    result = await trademarks.get_trademark(serial)
    assert result["serial_no"] == serial


@respx.mock
async def test_get_trademark_non_json_notice_degrades_to_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    serial = "97774270"
    monkeypatch.delenv("USPTO_API_KEY", raising=False)
    respx.get(TSDR.format(serial=serial)).mock(
        return_value=httpx.Response(
            200,
            text="Beginning October 2, you'll need to register for an API key…",
        )
    )
    assert await trademarks.get_trademark(serial) == {}
    assert respx.calls.call_count == 1


@respx.mock
async def test_get_trademark_never_raises_on_http_error() -> None:
    serial = "97774270"
    respx.get(TSDR.format(serial=serial)).mock(return_value=httpx.Response(403, text="denied"))
    assert await trademarks.get_trademark(serial) == {}
    assert respx.calls.call_count == 1


async def test_get_trademark_empty_serial_returns_empty() -> None:
    assert await trademarks.get_trademark("") == {}
    assert respx.calls.call_count == 0


# ── company_registry.search_companies ───────────────────────────────────


@respx.mock
async def test_search_companies_nv_normalizes_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(company_registry, "DEFAULT_STATE", "NV")
    respx.get(NV_SEARCH).mock(
        return_value=httpx.Response(200, json={"rows": [_nv_row()], "totalRows": 1})
    )
    results = await company_registry.search_companies("tesla")
    assert len(results) == 1
    entry = results[0]
    _assert_company_schema(entry)
    assert entry["name"] == "TESLA INC"
    assert entry["entity_id"] == "E1234567-8"
    assert entry["type"] == "Foreign Corporation"
    assert entry["status"] == "Active"
    assert entry["formation_date"] == "2012-05-31"
    assert entry["registered_agent"] == "C T Corporation System"


@respx.mock
async def test_search_companies_passes_page_size_param(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(company_registry, "DEFAULT_STATE", "NV")
    route = respx.get(NV_SEARCH).mock(
        return_value=httpx.Response(200, json={"rows": [_nv_row() for _ in range(2)]})
    )
    await company_registry.search_companies("tesla", limit=2)
    assert route.calls.last.request.url.params["pageSize"] == "2"
    assert route.calls.last.request.url.params["searchValue"] == "tesla"


@respx.mock
async def test_search_companies_unsupported_state_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(company_registry, "DEFAULT_STATE", "ZZ")
    assert await company_registry.search_companies("tesla") == []
    assert respx.calls.call_count == 0


@respx.mock
async def test_search_companies_never_raises_on_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(company_registry, "DEFAULT_STATE", "NV")
    respx.get(NV_SEARCH).mock(return_value=httpx.Response(500, text="boom"))
    assert await company_registry.search_companies("tesla") == []
    assert respx.calls.call_count == 1


@respx.mock
async def test_search_companies_never_raises_on_bad_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(company_registry, "DEFAULT_STATE", "NV")
    respx.get(NV_SEARCH).mock(return_value=httpx.Response(200, content=b"not json"))
    assert await company_registry.search_companies("tesla") == []
    assert respx.calls.call_count == 1


async def test_search_companies_empty_name_returns_empty() -> None:
    assert await company_registry.search_companies("  ") == []
    assert respx.calls.call_count == 0


# ── company_registry.get_company ────────────────────────────────────────


@respx.mock
async def test_get_company_exact_match_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(company_registry, "DEFAULT_STATE", "NV")
    respx.get(NV_SEARCH).mock(
        return_value=httpx.Response(
            200,
            json={
                "rows": [
                    _nv_row(name="TESLA HOMES LLC", entity_id="E0001"),
                    _nv_row(name="TESLA INC", entity_id="E0002"),
                ]
            },
        )
    )
    result = await company_registry.get_company("Tesla Inc")
    assert result["entity_id"] == "E0002"


@respx.mock
async def test_get_company_falls_back_to_top_result(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(company_registry, "DEFAULT_STATE", "NV")
    respx.get(NV_SEARCH).mock(
        return_value=httpx.Response(200, json={"rows": [_nv_row(name="TESLA HOMES LLC")]})
    )
    result = await company_registry.get_company("tesla")
    assert result["name"] == "TESLA HOMES LLC"


@respx.mock
async def test_get_company_unsupported_state_returns_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(company_registry, "DEFAULT_STATE", "NV")
    respx.get(NV_SEARCH).mock(return_value=httpx.Response(200, json={"rows": []}))
    assert await company_registry.get_company("tesla", state="XX") == {}
    assert respx.calls.call_count == 0


@respx.mock
async def test_get_company_no_results_returns_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(company_registry, "DEFAULT_STATE", "NV")
    respx.get(NV_SEARCH).mock(return_value=httpx.Response(200, json={"rows": []}))
    assert await company_registry.get_company("nonexistent") == {}
    assert respx.calls.call_count == 1


# ── Router tests ────────────────────────────────────────────────────────


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
