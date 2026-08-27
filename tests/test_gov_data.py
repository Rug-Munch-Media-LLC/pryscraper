# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for the gov_data package (SAM.gov / CPSC / FDA openFDA).

Covers SAM.gov procurement search + lookup (API-key gating, mapping,
never-raise degradation), CPSC + FDA recall search per agency and merged,
recall lookup by prefixed id, the never-raise contract (HTTP errors and
malformed payloads all degrade to empty output), and the /v1/gov/* router
(200 + 502-degradation + 422 validation).

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

import datasets.gov_data as gov_data
import datasets.gov_data.procurement as procurement
import datasets.gov_data.recalls as recalls
import pry.api.routers.data.gov_data as gov_router_mod
from pry.api.routers.data.gov_data import router as gov_router
from pry.core.errors import PryError
from pry.engine.retry import RetryConfig

_SAM = "https://api.sam.gov/opportunities/v2/search"
_GRANTS = "https://api.grants.gov/v2/search/opportunities/"
_TED = "https://api.ted.europa.eu/v3/notices/search"
_CPSC = "https://api.cpsc.gov/cpsc/v1/recalls"
_FDA_FOOD = "https://api.fda.gov/food/enforcement.json"
_FDA_DEVICE = "https://api.fda.gov/device/enforcement.json"
_FDA_DRUG = "https://api.fda.gov/drug/enforcement.json"
_ALL_FDA = (_FDA_FOOD, _FDA_DEVICE, _FDA_DRUG)

_ZERO_RETRY = RetryConfig(
    max_retries=1, base_delay=0.0, max_delay=0.0, retryable_exceptions=(httpx.HTTPError,)
)


@pytest.fixture(autouse=True)
def _hermetic_gov(monkeypatch: pytest.MonkeyPatch) -> None:
    """Kill backoff delays and clear the SAM key so tests are deterministic."""
    monkeypatch.setattr(procurement, "_RETRY_CONFIG", _ZERO_RETRY)
    monkeypatch.setattr(recalls, "_RETRY_CONFIG", _ZERO_RETRY)
    monkeypatch.delenv("PRY_SAM_API_KEY", raising=False)


# ── Payload fixtures ───────────────────────────────────────────────────


def _sam_search_payload() -> dict[str, Any]:
    return {
        "totalRecords": 1,
        "opportunitiesData": [
            {
                "noticeId": "3488234",
                "title": "Z--TEST Presolicitation for aircraft maintenance",
                "solicitationNumber": "FA1234-26-R-0001",
                "agency": "DEPT OF THE AIR FORCE",
                "office": "FA8539 AFSC PZAA",
                "typeOfNotice": "Presolicitation",
                "noticeType": "Presolicitation",
                "naicsCode": "336411",
                "naicsCodes": ["336411"],
                "setAside": "Total Small Business Set-Aside (FAR 19.5)",
                "typeOfSetAsideDescription": "Total Small Business Set-Aside",
                "responseDeadLine": "2026-01-01 12:00:00+00",
                "responseDate": "2026-01-01",
                "postedDate": "2025-12-01 08:00:00+00",
                "active": "Yes",
                "url": "https://sam.gov/opp/3488234/view",
                "description": "Aircraft maintenance test opportunity.",
            }
        ],
    }


def _cpsc_payload() -> dict[str, Any]:
    return {
        "total": 1,
        "recalls": [
            {
                "cpscId": "12345",
                "title": "Children's Hooded Sweatshirts Recalled Due to Drawstring Hazard",
                "nameOfProduct": "Children's hooded sweatshirts",
                "recallDate": "2023-01-01",
                "hazards": "The drawstrings can become entangled ...",
                "description": "The garments have drawstrings at the neck.",
                "units": "About 1,000",
                "remedy": "Refund",
                "consumerContact": "Acme at 800-555-0100",
                "manufacturers": [{"name": "Acme Clothing"}],
                "url": "https://www.cpsc.gov/Recalls/2023/Recall-12345",
            }
        ],
    }


def _fda_payload(recall_number: str, date: str, classification: str) -> dict[str, Any]:
    return {
        "meta": {"results": {"total": 1}},
        "results": [
            {
                "recall_number": recall_number,
                "reason_for_recall": "Product may contain undeclared allergen.",
                "status": "Ongoing",
                "recalling_firm": "Example Foods Inc.",
                "product_description": "Crunchy peanut butter",
                "classification": classification,
                "recall_initiation_date": date,
                "center_classification_date": date,
                "report_date": date,
            }
        ],
    }


def _grants_payload() -> dict[str, Any]:
    return {
        "success": True,
        "message": "",
        "data": {
            "paging": {"page": 1, "limit": 25, "totalRecords": 1},
            "opportunities": [
                {
                    "opportunityId": "326598",
                    "opportunityTitle": "Rural Broadband Grant Program",
                    "agencyName": "DEPARTMENT OF AGRICULTURE",
                    "agencyCode": "USDA",
                    "opportunityCategory": "Discretionary",
                    "closeDate": "2026-06-01 23:59:59.000",
                    "postedDate": "2026-01-15 00:00:00.000",
                    "opportunityDetailUrl": "https://www.grants.gov/search-results-detail/326598",
                }
            ],
        },
    }


def _ted_payload() -> dict[str, Any]:
    return {
        "total": 1,
        "limit": 25,
        "offset": 0,
        "notices": [
            {
                "OJS_number": "2023/S 123-456789",
                "title": {"en": "Aircraft maintenance services"},
                "buyer": {"name": "Ministry of Defence"},
                "type": "Contract Notice",
                "submission_deadline": "2023-12-31T12:00:00",
            }
        ],
    }


# ── procurement: search ────────────────────────────────────────────────


@respx.mock
async def test_search_opportunities_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRY_SAM_API_KEY", "test-key")
    respx.get(url__startswith=_SAM).mock(
        return_value=httpx.Response(200, json=_sam_search_payload())
    )
    results = await procurement.search_opportunities("aircraft maintenance", limit=5)
    assert len(results) == 1
    record = results[0]
    assert record["id"] == "3488234"
    assert record["title"] == "Z--TEST Presolicitation for aircraft maintenance"
    assert record["agency"] == "DEPT OF THE AIR FORCE"
    assert record["type"] == "Presolicitation"
    assert record["naics"] == "336411"
    assert record["set_aside"] == "Total Small Business Set-Aside (FAR 19.5)"
    assert record["due_date"] == "2026-01-01 12:00:00+00"
    assert record["url"] == "https://sam.gov/opp/3488234/view"
    assert record["source"] == "sam_gov"


@respx.mock
async def test_search_opportunities_no_key_falls_through_to_keyless_sources() -> None:
    # No PRY_SAM_API_KEY → SAM skipped, grants.gov fills in (no auth).
    respx.post(_GRANTS).mock(return_value=httpx.Response(200, json=_grants_payload()))
    results = await procurement.search_opportunities("rural broadband")
    assert len(results) == 1
    assert results[0]["source"] == "grants_gov"
    assert results[0]["id"] == "326598"
    assert results[0]["title"] == "Rural Broadband Grant Program"
    assert results[0]["due_date"] == "2026-06-01 23:59:59"
    # SAM was never hit (no key), grants.gov was.
    assert not any(str(call.request.url).startswith(_SAM) for call in respx.calls)


@respx.mock
async def test_search_opportunities_http_error_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PRY_SAM_API_KEY", "test-key")
    respx.get(url__startswith=_SAM).mock(return_value=httpx.Response(500))
    respx.post(_GRANTS).mock(return_value=httpx.Response(500))
    respx.post(_TED).mock(return_value=httpx.Response(500))
    assert await procurement.search_opportunities("aircraft maintenance") == []


@respx.mock
async def test_search_opportunities_malformed_payload_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PRY_SAM_API_KEY", "test-key")
    respx.get(url__startswith=_SAM).mock(return_value=httpx.Response(200, json={"nope": True}))
    respx.post(_GRANTS).mock(return_value=httpx.Response(200, json={"nope": True}))
    respx.post(_TED).mock(return_value=httpx.Response(200, json={"nope": True}))
    assert await procurement.search_opportunities("aircraft maintenance") == []


@respx.mock
async def test_search_opportunities_empty_query_returns_empty() -> None:
    assert await procurement.search_opportunities("   ") == []
    assert respx.calls.call_count == 0


@respx.mock
async def test_search_opportunities_falls_back_to_grants_gov(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # SAM errors → grants.gov fills in.
    monkeypatch.setenv("PRY_SAM_API_KEY", "test-key")
    respx.get(url__startswith=_SAM).mock(return_value=httpx.Response(500))
    respx.post(_GRANTS).mock(return_value=httpx.Response(200, json=_grants_payload()))
    results = await procurement.search_opportunities("rural broadband", limit=5)
    assert len(results) == 1
    assert results[0]["source"] == "grants_gov"
    assert results[0]["agency"] == "DEPARTMENT OF AGRICULTURE"
    assert results[0]["type"] == "Discretionary"
    assert results[0]["url"] == "https://www.grants.gov/search-results-detail/326598"


@respx.mock
async def test_search_opportunities_falls_back_to_ted(monkeypatch: pytest.MonkeyPatch) -> None:
    # SAM + grants.gov both fail → TED (EU) fills in.
    monkeypatch.setenv("PRY_SAM_API_KEY", "test-key")
    respx.get(url__startswith=_SAM).mock(return_value=httpx.Response(500))
    respx.post(_GRANTS).mock(return_value=httpx.Response(500))
    respx.post(_TED).mock(return_value=httpx.Response(200, json=_ted_payload()))
    results = await procurement.search_opportunities("aircraft maintenance", limit=5)
    assert len(results) == 1
    record = results[0]
    assert record["source"] == "ted"
    assert record["id"] == "2023/S 123-456789"
    assert record["title"] == "Aircraft maintenance services"
    assert record["agency"] == "Ministry of Defence"
    assert record["url"] == "https://ted.europa.eu/en/notice/-/detail/2023/S 123-456789"


# ── procurement: search_grants ─────────────────────────────────────────


@respx.mock
async def test_search_grants_success() -> None:
    respx.post(_GRANTS).mock(return_value=httpx.Response(200, json=_grants_payload()))
    results = await procurement.search_grants("rural broadband", limit=5)
    assert len(results) == 1
    assert results[0]["source"] == "grants_gov"
    assert results[0]["id"] == "326598"
    assert results[0]["due_date"] == "2026-06-01 23:59:59"


@respx.mock
async def test_search_grants_falls_back_to_ted() -> None:
    respx.post(_GRANTS).mock(return_value=httpx.Response(500))
    respx.post(_TED).mock(return_value=httpx.Response(200, json=_ted_payload()))
    results = await procurement.search_grants("aircraft", limit=5)
    assert len(results) == 1
    assert results[0]["source"] == "ted"
    assert results[0]["id"] == "2023/S 123-456789"


@respx.mock
async def test_search_grants_never_raises() -> None:
    respx.post(_GRANTS).mock(return_value=httpx.Response(500))
    respx.post(_TED).mock(return_value=httpx.Response(500))
    assert await procurement.search_grants("aircraft") == []


async def test_search_grants_blank_query() -> None:
    assert await procurement.search_grants("   ") == []
    assert respx.calls.call_count == 0


# ── procurement: get ───────────────────────────────────────────────────


@respx.mock
async def test_get_opportunity_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRY_SAM_API_KEY", "test-key")
    respx.get(url__startswith=_SAM).mock(
        return_value=httpx.Response(200, json=_sam_search_payload())
    )
    record = await procurement.get_opportunity("3488234")
    assert record["id"] == "3488234"
    assert record["url"] == "https://sam.gov/opp/3488234/view"


@respx.mock
async def test_get_opportunity_no_key_returns_empty() -> None:
    assert await procurement.get_opportunity("3488234") == {}
    assert respx.calls.call_count == 0


@respx.mock
async def test_get_opportunity_http_error_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PRY_SAM_API_KEY", "test-key")
    respx.get(url__startswith=_SAM).mock(return_value=httpx.Response(500))
    assert await procurement.get_opportunity("3488234") == {}


@respx.mock
async def test_get_opportunity_not_found_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PRY_SAM_API_KEY", "test-key")
    respx.get(url__startswith=_SAM).mock(
        return_value=httpx.Response(200, json={"totalRecords": 0, "opportunitiesData": []})
    )
    assert await procurement.get_opportunity("9999999") == {}


@respx.mock
async def test_get_opportunity_empty_id_returns_empty() -> None:
    assert await procurement.get_opportunity("") == {}
    assert respx.calls.call_count == 0


# ── recalls: search ────────────────────────────────────────────────────


@respx.mock
async def test_search_recalls_cpsc_only() -> None:
    respx.get(url__startswith=_CPSC).mock(return_value=httpx.Response(200, json=_cpsc_payload()))
    results = await recalls.search_recalls("sweatshirt", agency="cpsc", limit=5)
    assert len(results) == 1
    record = results[0]
    assert record["id"] == "cpsc:12345"
    assert record["agency"] == "cpsc"
    assert record["title"].startswith("Children's Hooded Sweatshirts")
    assert record["product"] == "Children's hooded sweatshirts"
    assert record["reason"].startswith("The drawstrings")
    assert record["date"] == "2023-01-01"
    assert record["severity"] is None
    assert record["url"] == "https://www.cpsc.gov/Recalls/2023/Recall-12345"
    assert record["source"] == "cpsc"


@respx.mock
async def test_search_recalls_fda_only_sorted_newest_first() -> None:
    for endpoint, payload in (
        (_FDA_FOOD, _fda_payload("F-1000-2023", "20230101", "Class I")),
        (_FDA_DEVICE, _fda_payload("Z-2000-2023", "20230515", "Class II")),
        (_FDA_DRUG, _fda_payload("D-3000-2023", "20230720", "Class III")),
    ):
        respx.get(url__startswith=endpoint).mock(return_value=httpx.Response(200, json=payload))
    results = await recalls.search_recalls("peanut butter", agency="fda", limit=10)
    assert len(results) == 3
    # newest first by date
    assert results[0]["id"] == "fda:D-3000-2023"
    assert results[1]["id"] == "fda:Z-2000-2023"
    assert results[2]["id"] == "fda:F-1000-2023"
    record = results[0]
    assert record["agency"] == "fda"
    assert record["title"] == "Crunchy peanut butter"
    assert record["product"] == "Crunchy peanut butter"
    assert record["reason"].startswith("Product may contain")
    assert record["date"] == "2023-07-20"  # YYYYMMDD -> YYYY-MM-DD
    assert record["severity"] == "Class III"
    assert record["url"] == f"{_FDA_DRUG}?search=recall_number:%22D-3000-2023%22"
    assert record["source"] == "openfda"


@respx.mock
async def test_search_recalls_all_merges_and_truncates() -> None:
    respx.get(url__startswith=_CPSC).mock(return_value=httpx.Response(200, json=_cpsc_payload()))
    respx.get(url__startswith=_FDA_FOOD).mock(
        return_value=httpx.Response(200, json=_fda_payload("F-1000-2023", "20230101", "Class I"))
    )
    respx.get(url__startswith=_FDA_DEVICE).mock(
        return_value=httpx.Response(200, json={"meta": {}, "results": []})
    )
    respx.get(url__startswith=_FDA_DRUG).mock(
        return_value=httpx.Response(200, json={"meta": {}, "results": []})
    )
    # limit=3 → both sources merged (1 CPSC + 1 FDA food) with no truncation
    results = await recalls.search_recalls("peanut", agency="all", limit=3)
    assert len(results) == 2
    agencies = {r["agency"] for r in results}
    assert agencies == {"cpsc", "fda"}
    assert sorted(r["date"] for r in results) == ["2023-01-01", "2023-01-01"]


@respx.mock
async def test_search_recalls_all_truncates_to_limit() -> None:
    respx.get(url__startswith=_CPSC).mock(return_value=httpx.Response(200, json=_cpsc_payload()))
    respx.get(url__startswith=_FDA_FOOD).mock(
        return_value=httpx.Response(200, json=_fda_payload("F-1000-2023", "20230101", "Class I"))
    )
    respx.get(url__startswith=_FDA_DEVICE).mock(
        return_value=httpx.Response(200, json={"meta": {}, "results": []})
    )
    respx.get(url__startswith=_FDA_DRUG).mock(
        return_value=httpx.Response(200, json={"meta": {}, "results": []})
    )
    results = await recalls.search_recalls("peanut", agency="all", limit=1)
    assert len(results) == 1


@respx.mock
async def test_search_recalls_invalid_agency_returns_empty() -> None:
    assert await recalls.search_recalls("peanut", agency="nasa") == []
    assert respx.calls.call_count == 0


@respx.mock
async def test_search_recalls_http_error_returns_empty() -> None:
    for endpoint in (_CPSC, *_ALL_FDA):
        respx.get(url__startswith=endpoint).mock(return_value=httpx.Response(500))
    assert await recalls.search_recalls("peanut", agency="all") == []


@respx.mock
async def test_search_recalls_malformed_payload_returns_empty() -> None:
    respx.get(url__startswith=_CPSC).mock(return_value=httpx.Response(200, json={"bad": True}))
    respx.get(url__startswith=_FDA_FOOD).mock(return_value=httpx.Response(200, json={"bad": True}))
    respx.get(url__startswith=_FDA_DEVICE).mock(
        return_value=httpx.Response(200, json={"bad": True})
    )
    respx.get(url__startswith=_FDA_DRUG).mock(return_value=httpx.Response(200, json={"bad": True}))
    assert await recalls.search_recalls("peanut", agency="all") == []


# ── recalls: get ───────────────────────────────────────────────────────


@respx.mock
async def test_get_recall_cpsc() -> None:
    respx.get(url__startswith=_CPSC).mock(return_value=httpx.Response(200, json=_cpsc_payload()))
    record = await recalls.get_recall("cpsc:12345")
    assert record["id"] == "cpsc:12345"
    assert record["agency"] == "cpsc"
    assert record["product"] == "Children's hooded sweatshirts"


@respx.mock
async def test_get_recall_bare_numeric_defaults_cpsc() -> None:
    respx.get(url__startswith=_CPSC).mock(return_value=httpx.Response(200, json=_cpsc_payload()))
    record = await recalls.get_recall("12345")
    assert record["id"] == "cpsc:12345"


@respx.mock
async def test_get_recall_cpsc_not_found_returns_empty() -> None:
    respx.get(url__startswith=_CPSC).mock(
        return_value=httpx.Response(200, json={"total": 0, "recalls": []})
    )
    assert await recalls.get_recall("cpsc:99999") == {}


@respx.mock
async def test_get_recall_fda() -> None:
    respx.get(url__startswith=_FDA_FOOD).mock(
        return_value=httpx.Response(200, json=_fda_payload("F-1000-2023", "20230101", "Class I"))
    )
    respx.get(url__startswith=_FDA_DEVICE).mock(
        return_value=httpx.Response(200, json={"meta": {}, "results": []})
    )
    respx.get(url__startswith=_FDA_DRUG).mock(
        return_value=httpx.Response(200, json={"meta": {}, "results": []})
    )
    record = await recalls.get_recall("fda:F-1000-2023")
    assert record["id"] == "fda:F-1000-2023"
    assert record["agency"] == "fda"
    assert record["severity"] == "Class I"


@respx.mock
async def test_get_recall_fda_not_found_returns_empty() -> None:
    for endpoint in _ALL_FDA:
        respx.get(url__startswith=endpoint).mock(
            return_value=httpx.Response(200, json={"meta": {}, "results": []})
        )
    assert await recalls.get_recall("fda:NOPE-0000-0000") == {}


@respx.mock
async def test_get_recall_unknown_prefix_returns_empty() -> None:
    assert await recalls.get_recall("epa:123") == {}
    assert respx.calls.call_count == 0


@respx.mock
async def test_get_recall_empty_id_returns_empty() -> None:
    assert await recalls.get_recall("") == {}
    assert respx.calls.call_count == 0


# ── router ─────────────────────────────────────────────────────────────


@pytest.fixture
def gov_app() -> FastAPI:
    app = FastAPI()

    @app.exception_handler(PryError)
    async def pry_error_handler(request: Request, exc: PryError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": str(exc)})

    app.include_router(gov_router)
    return app


def _client(app: FastAPI) -> TestClient:
    return TestClient(app)


def test_router_importable() -> None:
    assert hasattr(gov_data, "search_opportunities")
    assert hasattr(gov_data, "get_opportunity")
    assert hasattr(gov_data, "search_recalls")
    assert hasattr(gov_data, "get_recall")
    assert hasattr(gov_router_mod, "router")


def test_router_procurement_search_success(
    gov_app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake(query: str, limit: int = 20) -> list[dict[str, Any]]:
        return [{"id": "3488234", "title": f"match for {query}", "source": "sam_gov"}]

    monkeypatch.setattr(procurement, "search_opportunities", fake)
    resp = _client(gov_app).get(
        "/v1/gov/procurement/search", params={"query": "aircraft", "limit": 5}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["query"] == "aircraft"
    assert body["data"][0]["id"] == "3488234"


def test_router_procurement_get_success(gov_app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake(notice_id: str) -> dict[str, Any]:
        return {"id": notice_id, "title": "Z--TEST", "source": "sam_gov"}

    monkeypatch.setattr(procurement, "get_opportunity", fake)
    resp = _client(gov_app).get("/v1/gov/procurement/3488234")
    assert resp.status_code == 200
    assert resp.json()["data"]["id"] == "3488234"


def test_router_recalls_search_success(gov_app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake(query: str, agency: str = "all", limit: int = 20) -> list[dict[str, Any]]:
        return [{"id": "cpsc:1", "agency": agency, "title": f"recall {query}", "source": "cpsc"}]

    monkeypatch.setattr(recalls, "search_recalls", fake)
    resp = _client(gov_app).get(
        "/v1/gov/recalls/search", params={"query": "sweatshirt", "agency": "cpsc", "limit": 5}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["agency"] == "cpsc"
    assert body["data"][0]["title"] == "recall sweatshirt"


def test_router_502_when_module_absent(gov_app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gov_router_mod, "_gov_module", lambda name: None)
    assert (
        _client(gov_app).get("/v1/gov/procurement/search", params={"query": "x"}).status_code == 502
    )
    assert _client(gov_app).get("/v1/gov/procurement/3488234").status_code == 502
    assert _client(gov_app).get("/v1/gov/recalls/search", params={"query": "x"}).status_code == 502


def test_router_validation_422(gov_app: FastAPI) -> None:
    assert (
        _client(gov_app).get("/v1/gov/procurement/search", params={"query": ""}).status_code == 422
    )
    assert (
        _client(gov_app)
        .get("/v1/gov/procurement/search", params={"query": "x", "limit": 0})
        .status_code
        == 422
    )
    assert (
        _client(gov_app)
        .get("/v1/gov/procurement/search", params={"query": "x", "limit": 201})
        .status_code
        == 422
    )
    assert _client(gov_app).get("/v1/gov/recalls/search", params={"limit": 0}).status_code == 422
    assert _client(gov_app).get("/v1/gov/recalls/search", params={"limit": 101}).status_code == 422
