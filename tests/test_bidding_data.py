# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for the bidding_data package (contracts + grants).

Covers the contracts search across SAM.gov / TED / NY Contract Reporter /
FedConnect (multi-source merge, sorting, truncation, gov_data reuse,
never-raise degradation), contract lookup by source-prefixed id, the grants
search + detail from the free Grants.gov GrantsWS API, the never-raise
contract (HTTP errors and malformed payloads all degrade to empty output),
and the /v1/bidding/* router (200 + 502-degradation + 422 validation).

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

import datasets.bidding_data as bidding_data
import datasets.bidding_data.contracts as contracts
import datasets.bidding_data.grants as grants
import routers.bidding_data as bidding_router_mod
from pry.core.errors import PryError
from pry.engine.retry import RetryConfig
from routers.bidding_data import router as bidding_router

_SAM = "https://api.sam.gov/opportunities/v2/search"
_TED = "https://api.ted.europa.eu/v3/notices/search"
_TED_DETAIL = "https://api.ted.europa.eu/v3/notices/"
_NY = "https://www.nycr.ny.gov/api/contracts/search"
_NY_DETAIL = "https://www.nycr.ny.gov/api/contracts/"
_FEDCONNECT = "https://www.fedconnect.net/FedConnect/PublicPages/PublicSearch.aspx"
_GRANTS_SEARCH = "https://apply07.grants.gov/grantsws/rest/opportunities/search/"
_GRANTS_DETAIL = "https://apply07.grants.gov/grantsws/rest/opportunities/"

_ZERO_RETRY = RetryConfig(
    max_retries=1, base_delay=0.0, max_delay=0.0, retryable_exceptions=(httpx.HTTPError,)
)


@pytest.fixture(autouse=True)
def _hermetic_bidding(monkeypatch: pytest.MonkeyPatch) -> None:
    """Kill backoff delays, clear the SAM key and force the direct SAM path."""
    monkeypatch.setattr(contracts, "_RETRY_CONFIG", _ZERO_RETRY)
    monkeypatch.setattr(grants, "_RETRY_CONFIG", _ZERO_RETRY)
    monkeypatch.delenv("PRY_SAM_API_KEY", raising=False)
    # gov_data.procurement exists in this tree; patch the resolver itself to
    # force the direct SAM.gov client so every SAM test is deterministic
    # (dedicated tests below cover the gov_data reuse path explicitly).
    monkeypatch.setattr(contracts, "_gov_procurement", lambda: None)


class _FakeGovData:
    """Stands in for gov_data.procurement in the reuse test."""

    async def search_opportunities(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        return [
            {
                "id": "999",
                "title": f"fake {query}",
                "agency": "FAKE AGENCY",
                "type": "Presolicitation",
                "naics": "111111",
                "set_aside": None,
                "due_date": "2026-06-01 00:00:00+00",
                "url": "https://sam.gov/opp/999/view",
            }
        ]

    async def get_opportunity(self, notice_id: str | int) -> dict[str, Any]:
        return {
            "id": str(notice_id),
            "title": "fake detail",
            "agency": "FAKE AGENCY",
            "type": "Presolicitation",
            "naics": "111111",
            "set_aside": None,
            "due_date": "2026-06-01 00:00:00+00",
            "url": "https://sam.gov/opp/999/view",
            "description": "Fake detail description.",
        }


# ── Payload fixtures ───────────────────────────────────────────────────


def _sam_payload() -> dict[str, Any]:
    return {
        "totalRecords": 1,
        "opportunitiesData": [
            {
                "noticeId": "3488234",
                "title": "Z--TEST Presolicitation for aircraft maintenance",
                "agency": "DEPT OF THE AIR FORCE",
                "typeOfNotice": "Presolicitation",
                "naicsCode": "336411",
                "setAside": "Total Small Business Set-Aside (FAR 19.5)",
                "responseDeadLine": "2026-01-01 12:00:00+00",
                "url": "https://sam.gov/opp/3488234/view",
                "description": "Aircraft maintenance test opportunity.",
            }
        ],
    }


def _sam_award_payload() -> dict[str, Any]:
    return {
        "totalRecords": 1,
        "opportunitiesData": [
            {
                "noticeId": "5551234",
                "title": "Award Notice -- aircraft maintenance",
                "agency": "DEPT OF THE AIR FORCE",
                "typeOfNotice": "Award Notice",
                "naicsCode": "336411",
                "responseDeadLine": None,
                "awardDate": "2026-02-15",
                "url": "https://sam.gov/opp/5551234/view",
                "description": "Awarded contract notice.",
            }
        ],
    }


def _ted_payload() -> dict[str, Any]:
    return {
        "results": [
            {
                "publicationNumber": "123456-2026",
                "title": "IT support services",
                "buyer": {"name": "City of Paris"},
                "noticeType": "Contract notice",
                "deadlineDate": "2026-05-01 12:00:00+00",
            }
        ]
    }


def _ny_payload() -> dict[str, Any]:
    return {
        "results": [
            {
                "id": 42,
                "title": "Bridge rehabilitation",
                "agencyName": "NYS DOT",
                "dueDate": "2026-03-01 16:00:00",
                "description": "Rehabilitate the Smith St bridge.",
            }
        ]
    }


def _fedconnect_html() -> str:
    return (
        '<html><body><table><tr><td><a href="PublicSearch.aspx?doc=FA1234">'
        "Aircraft fuel</a></td></tr></table></body></html>"
    )


def _fedconnect_detail_html() -> str:
    return "<html><head><title>FA1234 -- Aircraft fuel</title></head><body></body></html>"


def _grants_search_payload() -> dict[str, Any]:
    return {
        "oppSearchResults": [
            {
                "oppId": 351234,
                "opportunityTitle": "Community Development Block Grant",
                "agency": "HUD",
                "oppNumber": "FR-6800-N-01",
                "opportunityCategoryExplanation": "Discretionary",
                "openDate": "2026-01-01 00:00:00",
                "closeDate": "2026-03-01 23:59:59",
                "awardCeiling": 750000,
                "estimatedTotalProgramFunding": 1000000,
                "opportunityStatus": "posted",
            }
        ]
    }


def _grants_detail_payload() -> dict[str, Any]:
    return {
        "oppDetail": {
            "oppId": 351234,
            "opportunityTitle": "Community Development Block Grant",
            "agency": "HUD",
            "oppNumber": "FR-6800-N-01",
            "opportunityCategoryExplanation": "Discretionary",
            "openDate": "2026-01-01 00:00:00",
            "closeDate": "2026-03-01 23:59:59",
            "awardCeiling": 750000,
            "description": "Funds community development projects.",
            "applicantEligibility": "State and local governments",
            "agencyContact": {
                "firstName": "Ada",
                "lastName": "Lovelace",
                "email": "ada@example.gov",
                "phone": "555-0100",
            },
            "documents": [
                {"title": "NOFO", "url": "https://www.grants.gov/files/nofo.pdf"},
            ],
        }
    }


# ── contracts: search ─────────────────────────────────────────────────


@respx.mock
async def test_search_contracts_merges_sources_and_sorts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PRY_SAM_API_KEY", "test-key")
    respx.get(url__startswith=_SAM).mock(return_value=httpx.Response(200, json=_sam_payload()))
    respx.get(url__startswith=_TED).mock(return_value=httpx.Response(200, json=_ted_payload()))
    respx.get(url__startswith=_NY).mock(return_value=httpx.Response(200, json=_ny_payload()))
    respx.get(url__startswith=_FEDCONNECT).mock(
        return_value=httpx.Response(200, text=_fedconnect_html())
    )
    results = await contracts.search_contracts("aircraft", limit=10)
    assert len(results) == 4
    # sorted by due date ascending; fedconnect (no due date) sorts last
    assert [r["id"] for r in results] == [
        "sam:3488234",
        "ny:42",
        "ted:123456-2026",
        "fedconnect:FA1234",
    ]
    sam = results[0]
    assert sam["title"] == "Z--TEST Presolicitation for aircraft maintenance"
    assert sam["agency"] == "DEPT OF THE AIR FORCE"
    assert sam["type"] == "solicitation"
    assert sam["notice_type"] == "Presolicitation"
    assert sam["naics"] == "336411"
    assert sam["set_aside"] == "Total Small Business Set-Aside (FAR 19.5)"
    assert sam["url"] == "https://sam.gov/opp/3488234/view"
    assert sam["source"] == "sam_gov"
    assert results[1]["source"] == "ny_contract_reporter"
    assert results[2]["source"] == "ted"
    assert results[3]["source"] == "fedconnect"


@respx.mock
async def test_search_contracts_truncates_to_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRY_SAM_API_KEY", "test-key")
    respx.get(url__startswith=_SAM).mock(return_value=httpx.Response(200, json=_sam_payload()))
    respx.get(url__startswith=_TED).mock(return_value=httpx.Response(200, json=_ted_payload()))
    respx.get(url__startswith=_NY).mock(return_value=httpx.Response(200, json=_ny_payload()))
    respx.get(url__startswith=_FEDCONNECT).mock(
        return_value=httpx.Response(200, text=_fedconnect_html())
    )
    results = await contracts.search_contracts("aircraft", limit=2)
    assert [r["id"] for r in results] == ["sam:3488234", "ny:42"]


@respx.mock
async def test_search_contracts_award_type_canonicalized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PRY_SAM_API_KEY", "test-key")
    respx.get(url__startswith=_SAM).mock(
        return_value=httpx.Response(200, json=_sam_award_payload())
    )
    respx.get(url__startswith=_TED).mock(return_value=httpx.Response(200, json={"results": []}))
    respx.get(url__startswith=_NY).mock(return_value=httpx.Response(200, json={"results": []}))
    respx.get(url__startswith=_FEDCONNECT).mock(
        return_value=httpx.Response(200, text="<html></html>")
    )
    results = await contracts.search_contracts("award")
    assert len(results) == 1
    assert results[0]["type"] == "award"
    assert results[0]["award_date"] == "2026-02-15"


@respx.mock
async def test_search_contracts_reuses_gov_data(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(contracts, "_gov_procurement", lambda: _FakeGovData())
    respx.get(url__startswith=_TED).mock(return_value=httpx.Response(200, json={"results": []}))
    respx.get(url__startswith=_NY).mock(return_value=httpx.Response(200, json={"results": []}))
    respx.get(url__startswith=_FEDCONNECT).mock(
        return_value=httpx.Response(200, text="<html></html>")
    )
    results = await contracts.search_contracts("widgets")
    assert len(results) == 1
    assert results[0]["id"] == "sam:999"
    assert results[0]["title"] == "fake widgets"
    assert results[0]["source"] == "sam_gov"
    assert respx.calls.call_count == 3  # SAM served by gov_data, not HTTP


@respx.mock
async def test_search_contracts_no_sam_key_skips_sam() -> None:
    respx.get(url__startswith=_TED).mock(return_value=httpx.Response(200, json=_ted_payload()))
    respx.get(url__startswith=_NY).mock(return_value=httpx.Response(200, json={"results": []}))
    respx.get(url__startswith=_FEDCONNECT).mock(
        return_value=httpx.Response(200, text="<html></html>")
    )
    results = await contracts.search_contracts("it services")
    assert [r["id"] for r in results] == ["ted:123456-2026"]


@respx.mock
async def test_search_contracts_empty_query_returns_empty() -> None:
    assert await contracts.search_contracts("   ") == []
    assert respx.calls.call_count == 0


@respx.mock
async def test_search_contracts_http_error_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PRY_SAM_API_KEY", "test-key")
    for endpoint in (_SAM, _TED, _NY, _FEDCONNECT):
        respx.get(url__startswith=endpoint).mock(return_value=httpx.Response(500))
    assert await contracts.search_contracts("aircraft") == []


@respx.mock
async def test_search_contracts_malformed_payload_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PRY_SAM_API_KEY", "test-key")
    respx.get(url__startswith=_SAM).mock(return_value=httpx.Response(200, json={"nope": True}))
    respx.get(url__startswith=_TED).mock(return_value=httpx.Response(200, json={"nope": True}))
    respx.get(url__startswith=_NY).mock(return_value=httpx.Response(200, json={"nope": True}))
    respx.get(url__startswith=_FEDCONNECT).mock(
        return_value=httpx.Response(200, text="<html></html>")
    )
    assert await contracts.search_contracts("aircraft") == []


# ── contracts: get ────────────────────────────────────────────────────


@respx.mock
async def test_get_contract_sam_direct(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRY_SAM_API_KEY", "test-key")
    respx.get(url__startswith=_SAM).mock(return_value=httpx.Response(200, json=_sam_payload()))
    record = await contracts.get_contract("sam:3488234")
    assert record["id"] == "sam:3488234"
    assert record["title"] == "Z--TEST Presolicitation for aircraft maintenance"
    assert record["description"] == "Aircraft maintenance test opportunity."
    assert record["type"] == "solicitation"


@respx.mock
async def test_get_contract_sam_via_gov_data(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(contracts, "_gov_procurement", lambda: _FakeGovData())
    record = await contracts.get_contract("999")
    assert record["id"] == "sam:999"
    assert record["description"] == "Fake detail description."
    assert respx.calls.call_count == 0


@respx.mock
async def test_get_contract_ted() -> None:
    respx.get(url__startswith=_TED_DETAIL).mock(
        return_value=httpx.Response(
            200,
            json={
                "publicationNumber": "123456-2026",
                "title": "IT support services",
                "buyer": {"name": "City of Paris"},
                "noticeType": "Contract notice",
                "description": "Long description.",
                "documents": [{"title": "Tender docs", "url": "https://ted.europa.eu/doc"}],
            },
        )
    )
    record = await contracts.get_contract("ted:123456-2026")
    assert record["id"] == "ted:123456-2026"
    assert record["agency"] == "City of Paris"
    assert record["description"] == "Long description."
    assert record["attachments"] == [{"title": "Tender docs", "url": "https://ted.europa.eu/doc"}]


@respx.mock
async def test_get_contract_ny() -> None:
    respx.get(url__startswith=_NY_DETAIL).mock(
        return_value=httpx.Response(
            200,
            json={
                "id": 42,
                "title": "Bridge rehabilitation",
                "agencyName": "NYS DOT",
                "dueDate": "2026-03-01 16:00:00",
                "description": "Rehabilitate the Smith St bridge.",
                "contactName": "Jane Doe",
                "contactEmail": "jane@dot.ny.gov",
                "documents": [{"title": "Specs", "url": "https://nycr.ny.gov/specs.pdf"}],
            },
        )
    )
    record = await contracts.get_contract("ny:42")
    assert record["id"] == "ny:42"
    assert record["description"] == "Rehabilitate the Smith St bridge."
    assert record["contacts"] == {
        "name": "Jane Doe",
        "email": "jane@dot.ny.gov",
        "phone": None,
    }
    assert record["attachments"] == [{"title": "Specs", "url": "https://nycr.ny.gov/specs.pdf"}]


@respx.mock
async def test_get_contract_fedconnect() -> None:
    respx.get(url__startswith=_FEDCONNECT).mock(
        return_value=httpx.Response(200, text=_fedconnect_detail_html())
    )
    record = await contracts.get_contract("fedconnect:FA1234")
    assert record["id"] == "fedconnect:FA1234"
    assert record["title"] == "FA1234 -- Aircraft fuel"
    assert record["source"] == "fedconnect"


@respx.mock
async def test_get_contract_unknown_prefix_returns_empty() -> None:
    assert await contracts.get_contract("epa:123") == {}
    assert respx.calls.call_count == 0


@respx.mock
async def test_get_contract_empty_id_returns_empty() -> None:
    assert await contracts.get_contract("") == {}
    assert await contracts.get_contract("   ") == {}
    assert respx.calls.call_count == 0


@respx.mock
async def test_get_contract_http_error_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PRY_SAM_API_KEY", "test-key")
    respx.get(url__startswith=_SAM).mock(return_value=httpx.Response(500))
    assert await contracts.get_contract("sam:3488234") == {}


# ── grants: search ────────────────────────────────────────────────────


@respx.mock
async def test_search_grants_success() -> None:
    respx.post(url__startswith=_GRANTS_SEARCH).mock(
        return_value=httpx.Response(200, json=_grants_search_payload())
    )
    results = await grants.search_grants("community development", limit=5)
    assert len(results) == 1
    record = results[0]
    assert record["id"] == "351234"
    assert record["title"] == "Community Development Block Grant"
    assert record["agency"] == "HUD"
    assert record["funding_type"] == "Discretionary"
    assert record["open_date"] == "2026-01-01 00:00:00"
    assert record["close_date"] == "2026-03-01 23:59:59"
    assert record["amount"] == "750000"
    assert record["eligible"] is None
    assert record["url"] == "https://www.grants.gov/search-results-detail/FR-6800-N-01"
    assert record["source"] == "grants_gov"


@respx.mock
async def test_search_grants_empty_query_returns_empty() -> None:
    assert await grants.search_grants("  ") == []
    assert respx.calls.call_count == 0


@respx.mock
async def test_search_grants_http_error_returns_empty() -> None:
    respx.post(url__startswith=_GRANTS_SEARCH).mock(return_value=httpx.Response(500))
    assert await grants.search_grants("community development") == []


@respx.mock
async def test_search_grants_malformed_payload_returns_empty() -> None:
    respx.post(url__startswith=_GRANTS_SEARCH).mock(return_value=httpx.Response(200, json={"x": 1}))
    assert await grants.search_grants("community development") == []


# ── grants: get ───────────────────────────────────────────────────────


@respx.mock
async def test_get_grant_success() -> None:
    respx.post(url__startswith=_GRANTS_DETAIL).mock(
        return_value=httpx.Response(200, json=_grants_detail_payload())
    )
    record = await grants.get_grant("351234")
    assert record["id"] == "351234"
    assert record["title"] == "Community Development Block Grant"
    assert record["description"] == "Funds community development projects."
    assert record["eligible"] == "State and local governments"
    assert record["contacts"] == {
        "name": "Ada Lovelace",
        "email": "ada@example.gov",
        "phone": "555-0100",
    }
    assert record["attachments"] == [
        {"title": "NOFO", "url": "https://www.grants.gov/files/nofo.pdf"}
    ]
    assert record["amount"] == "750000"


@respx.mock
async def test_get_grant_empty_id_returns_empty() -> None:
    assert await grants.get_grant("") == {}
    assert respx.calls.call_count == 0


@respx.mock
async def test_get_grant_not_found_returns_empty() -> None:
    respx.post(url__startswith=_GRANTS_DETAIL).mock(
        return_value=httpx.Response(200, json={"oppDetail": None})
    )
    assert await grants.get_grant("999999") == {}


@respx.mock
async def test_get_grant_http_error_returns_empty() -> None:
    respx.post(url__startswith=_GRANTS_DETAIL).mock(return_value=httpx.Response(500))
    assert await grants.get_grant("351234") == {}


# ── router ────────────────────────────────────────────────────────────


@pytest.fixture
def bidding_app() -> FastAPI:
    app = FastAPI()

    @app.exception_handler(PryError)
    async def pry_error_handler(request: Request, exc: PryError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": str(exc)})

    app.include_router(bidding_router)
    return app


def _client(app: FastAPI) -> TestClient:
    return TestClient(app)


def test_router_importable() -> None:
    assert hasattr(bidding_data, "search_contracts")
    assert hasattr(bidding_data, "get_contract")
    assert hasattr(bidding_data, "search_grants")
    assert hasattr(bidding_data, "get_grant")
    assert hasattr(bidding_router_mod, "router")


def test_router_contracts_search_success(
    bidding_app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake(query: str, limit: int = 20) -> list[dict[str, Any]]:
        return [{"id": "sam:3488234", "title": f"match for {query}", "source": "sam_gov"}]

    monkeypatch.setattr(contracts, "search_contracts", fake)
    resp = _client(bidding_app).get(
        "/v1/bidding/contracts", params={"query": "aircraft", "limit": 5}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["query"] == "aircraft"
    assert body["data"][0]["id"] == "sam:3488234"


def test_router_contracts_get_success(
    bidding_app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake(contract_id: str) -> dict[str, Any]:
        return {"id": contract_id, "title": "Z--TEST", "source": "sam_gov"}

    monkeypatch.setattr(contracts, "get_contract", fake)
    resp = _client(bidding_app).get("/v1/bidding/contracts/sam:3488234")
    assert resp.status_code == 200
    assert resp.json()["data"]["id"] == "sam:3488234"


def test_router_grants_search_success(
    bidding_app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake(query: str, limit: int = 20) -> list[dict[str, Any]]:
        return [{"id": "351234", "title": f"grant {query}", "source": "grants_gov"}]

    monkeypatch.setattr(grants, "search_grants", fake)
    resp = _client(bidding_app).get("/v1/bidding/grants", params={"query": "community", "limit": 5})
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["query"] == "community"
    assert body["data"][0]["title"] == "grant community"


def test_router_grants_get_success(bidding_app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake(grant_id: str) -> dict[str, Any]:
        return {"id": grant_id, "title": "CDBG", "source": "grants_gov"}

    monkeypatch.setattr(grants, "get_grant", fake)
    resp = _client(bidding_app).get("/v1/bidding/grants/351234")
    assert resp.status_code == 200
    assert resp.json()["data"]["id"] == "351234"


def test_router_502_when_module_absent(
    bidding_app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(bidding_router_mod, "_bidding_module", lambda name: None)
    assert (
        _client(bidding_app).get("/v1/bidding/contracts", params={"query": "x"}).status_code == 502
    )
    assert _client(bidding_app).get("/v1/bidding/contracts/sam:1").status_code == 502
    assert _client(bidding_app).get("/v1/bidding/grants", params={"query": "x"}).status_code == 502
    assert _client(bidding_app).get("/v1/bidding/grants/1").status_code == 502


def test_router_validation_422(bidding_app: FastAPI) -> None:
    assert (
        _client(bidding_app).get("/v1/bidding/contracts", params={"query": ""}).status_code == 422
    )
    assert (
        _client(bidding_app)
        .get("/v1/bidding/contracts", params={"query": "x", "limit": 0})
        .status_code
        == 422
    )
    assert (
        _client(bidding_app)
        .get("/v1/bidding/contracts", params={"query": "x", "limit": 201})
        .status_code
        == 422
    )
    assert _client(bidding_app).get("/v1/bidding/grants", params={"query": ""}).status_code == 422
    assert (
        _client(bidding_app)
        .get("/v1/bidding/grants", params={"query": "x", "limit": 101})
        .status_code
        == 422
    )
