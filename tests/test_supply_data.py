# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for the supply_data package (imports + firmographics).

Covers the ImportYeti/Panjiva-style import-record lookup (API-key gating,
honest anti-bot/login-wall degradation, partial records, mapping), the B2B
firmographics builder (website probing, tech-stack detection, LinkedIn
extraction, industry detection, job-board hiring signal, Crunchbase-adjacent
partner fields, independent field degradation), the never-raise contract,
and the /v1/supply/* router (200 + 502-degradation + 422 validation).

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

import routers.supply_data as supply_router_mod
import datasets.supply_data as supply_data
import datasets.supply_data.firmographics as firmographics
import datasets.supply_data.imports as imports_mod
from pry.core.errors import PryError
from pry.engine.retry import RetryConfig
from routers.supply_data import router as supply_router

_IMPORTS = "http://imports.test/v1/records"
_FIRMO = "http://firmo.test/v1/companies"
_GREENHOUSE = "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"
_LEVER = "https://api.lever.co/v0/postings/{slug}?mode=json"
_ASHBY = "https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=false"

_ZERO_RETRY = RetryConfig(
    max_retries=1, base_delay=0.0, max_delay=0.0, retryable_exceptions=(httpx.HTTPError,)
)


@pytest.fixture(autouse=True)
def _hermetic_supply(monkeypatch: pytest.MonkeyPatch) -> None:
    """Kill backoff delays and clear partner env so tests are deterministic."""
    monkeypatch.setattr(imports_mod, "_RETRY_CONFIG", _ZERO_RETRY)
    monkeypatch.setattr(firmographics, "_RETRY_CONFIG", _ZERO_RETRY)
    monkeypatch.delenv("PRY_IMPORTS_API_KEY", raising=False)
    monkeypatch.delenv("PRY_IMPORTS_API_URL", raising=False)
    monkeypatch.delenv("PRY_FIRMO_API_KEY", raising=False)
    monkeypatch.delenv("PRY_FIRMO_API_URL", raising=False)
    monkeypatch.delenv("PRY_FIRMO_WEBSITE", raising=False)


# ── Payload fixtures ───────────────────────────────────────────────────


def _imports_payload() -> dict[str, Any]:
    return {
        "records": [
            {
                "company": "Acme Trading Co",
                "hs_code": "8471.30",
                "product": "Laptop computers",
                "origin": "CN",
                "consignee": "Acme Trading Co",
                "shipment_date": "2026-06-14",
                "quantity": 4200,
                "teu": 6,
            }
        ]
    }


def _firmo_html() -> str:
    return """
    <html><head>
      <title>Acme Trading Co — Freight Forwarding &amp; Logistics</title>
      <meta name="description" content="Acme Trading Co provides freight forwarding,
        warehousing and customs brokerage worldwide.">
    </head><body>
      <a href="https://www.linkedin.com/company/acme-trading-co">LinkedIn</a>
      <link rel="stylesheet" href="/wp-content/themes/acme/style.css">
      <script src="https://js.stripe.com/v3/"></script>
      <script src="https://www.google-analytics.com/analytics.js"></script>
    </body></html>
    """


def _firmo_partner_payload() -> dict[str, Any]:
    return {
        "data": {
            "headcount": 1200,
            "last_funding": 40000000,
            "total_funding": "$120M",
        }
    }


# ── imports: get_import_records ───────────────────────────────────────


@respx.mock
async def test_get_import_records_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRY_IMPORTS_API_KEY", "test-key")
    monkeypatch.setattr(imports_mod, "_IMPORTS_API_URL", _IMPORTS)
    respx.get(url__startswith=_IMPORTS).mock(
        return_value=httpx.Response(200, json=_imports_payload())
    )
    results = await imports_mod.get_import_records("Acme Trading Co", limit=5)
    assert len(results) == 1
    record = results[0]
    assert record["company"] == "Acme Trading Co"
    assert record["hs_code"] == "8471.30"
    assert record["product"] == "Laptop computers"
    assert record["origin"] == "CN"
    assert record["consignee"] == "Acme Trading Co"
    assert record["shipment_date"] == "2026-06-14"
    assert record["quantity"] == 4200
    assert record["teu"] == 6
    assert record["source"] == "imports_partner"
    # the partner key travels as api_key query param
    assert "api_key" in respx.calls[0].request.url.params


@respx.mock
async def test_get_import_records_no_key_returns_empty_and_no_network() -> None:
    assert await imports_mod.get_import_records("Acme Trading Co") == []
    assert respx.calls.call_count == 0


@respx.mock
async def test_get_import_records_http_error_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PRY_IMPORTS_API_KEY", "test-key")
    monkeypatch.setattr(imports_mod, "_IMPORTS_API_URL", _IMPORTS)
    respx.get(url__startswith=_IMPORTS).mock(return_value=httpx.Response(500))
    assert await imports_mod.get_import_records("Acme Trading Co") == []


@respx.mock
async def test_get_import_records_malformed_payload_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PRY_IMPORTS_API_KEY", "test-key")
    monkeypatch.setattr(imports_mod, "_IMPORTS_API_URL", _IMPORTS)
    respx.get(url__startswith=_IMPORTS).mock(return_value=httpx.Response(200, json={"bad": True}))
    assert await imports_mod.get_import_records("Acme Trading Co") == []


@respx.mock
async def test_get_import_records_anti_bot_marker_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PRY_IMPORTS_API_KEY", "test-key")
    monkeypatch.setattr(imports_mod, "_IMPORTS_API_URL", _IMPORTS)
    respx.get(url__startswith=_IMPORTS).mock(
        return_value=httpx.Response(200, json={"blocked": True, "reason": "challenge"})
    )
    assert await imports_mod.get_import_records("Acme Trading Co") == []


@respx.mock
async def test_get_import_records_empty_company_returns_empty() -> None:
    assert await imports_mod.get_import_records("   ") == []
    assert respx.calls.call_count == 0


@respx.mock
async def test_get_import_records_partial_record_keeps_none_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PRY_IMPORTS_API_KEY", "test-key")
    monkeypatch.setattr(imports_mod, "_IMPORTS_API_URL", _IMPORTS)
    respx.get(url__startswith=_IMPORTS).mock(
        return_value=httpx.Response(
            200,
            json={
                "records": [
                    {
                        "company": "Acme Trading Co",
                        "hsCode": "8471.30",
                        "product_description": "Laptop computers",
                        "origin_country": "CN",
                        # quantity / teu / consignee / shipment_date missing
                    }
                ]
            },
        )
    )
    results = await imports_mod.get_import_records("Acme Trading Co", limit=5)
    assert len(results) == 1
    record = results[0]
    assert record["company"] == "Acme Trading Co"
    assert record["hs_code"] == "8471.30"
    assert record["product"] == "Laptop computers"
    assert record["origin"] == "CN"
    assert record["quantity"] is None
    assert record["teu"] is None
    assert record["consignee"] is None
    assert record["shipment_date"] is None


@respx.mock
async def test_get_import_records_limit_is_clamped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRY_IMPORTS_API_KEY", "test-key")
    monkeypatch.setattr(imports_mod, "_IMPORTS_API_URL", _IMPORTS)
    respx.get(url__startswith=_IMPORTS).mock(
        return_value=httpx.Response(200, json={"records": [dict(_imports_payload()["records"][0])]})
    )
    await imports_mod.get_import_records("Acme Trading Co", limit=500)
    assert respx.calls[0].request.url.params["limit"] == "200"


# ── firmographics: full success path ──────────────────────────────────


@respx.mock
async def test_get_company_firmographics_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(firmographics, "_FIRMO_API_URL", _FIRMO)
    monkeypatch.setenv("PRY_FIRMO_API_KEY", "test-key")
    respx.get("https://acme-trading-co.com").mock(
        return_value=httpx.Response(200, text=_firmo_html())
    )
    respx.get(_GREENHOUSE.format(slug="acme-trading-co")).mock(
        return_value=httpx.Response(200, json={"jobs": [{}, {}]})
    )
    respx.get(url__startswith=_FIRMO).mock(
        return_value=httpx.Response(200, json=_firmo_partner_payload())
    )
    record = await firmographics.get_company_firmographics("Acme Trading Co")
    assert record["name"] == "Acme Trading Co"
    assert record["website"] == "https://acme-trading-co.com"
    assert set(record["tech_stack"]) == {"WordPress", "Stripe", "Google Analytics"}
    assert record["linkedin_url"] == "https://www.linkedin.com/company/acme-trading-co"
    assert record["industry"] == "Logistics & Supply Chain"
    assert record["hiring_openings"] == 2
    assert record["headcount"] == 1200
    assert record["funding"] == 40000000
    assert record["total_funding"] == 120000000


@respx.mock
async def test_firmographics_website_fallback_tld(monkeypatch: pytest.MonkeyPatch) -> None:
    respx.get("https://acme-trading-co.com").mock(return_value=httpx.Response(404))
    respx.get("https://acme-trading-co.io").mock(
        return_value=httpx.Response(200, text=_firmo_html())
    )
    respx.get(_GREENHOUSE.format(slug="acme-trading-co")).mock(return_value=httpx.Response(404))
    respx.get(_LEVER.format(slug="acme-trading-co")).mock(return_value=httpx.Response(404))
    respx.get(_ASHBY.format(slug="acme-trading-co")).mock(return_value=httpx.Response(404))
    record = await firmographics.get_company_firmographics("Acme Trading Co")
    assert record["website"] == "https://acme-trading-co.io"
    assert set(record["tech_stack"]) == {"WordPress", "Stripe", "Google Analytics"}
    assert record["industry"] == "Logistics & Supply Chain"


@respx.mock
async def test_firmographics_no_website_degrades_fields() -> None:
    for candidate in (
        "https://acme-trading-co.com",
        "https://acme-trading-co.io",
        "https://acme-trading-co.co",
        "https://acme-trading-co.ai",
    ):
        respx.get(candidate).mock(return_value=httpx.Response(404))
    respx.get(_GREENHOUSE.format(slug="acme-trading-co")).mock(return_value=httpx.Response(404))
    respx.get(_LEVER.format(slug="acme-trading-co")).mock(return_value=httpx.Response(404))
    respx.get(_ASHBY.format(slug="acme-trading-co")).mock(return_value=httpx.Response(404))
    record = await firmographics.get_company_firmographics("Acme Trading Co")
    assert record["website"] is None
    assert record["tech_stack"] == []
    assert record["linkedin_url"] is None
    assert record["industry"] is None
    assert record["hiring_openings"] == 0
    assert record["headcount"] is None
    assert record["funding"] is None
    assert record["total_funding"] is None


@respx.mock
async def test_firmographics_anti_bot_page_degrades_html_signals() -> None:
    anti_bot_html = (
        "<html><head><title>Checking your browser</title></head>"
        "<body>Please wait while we verify you are human... cf-challenge</body></html>"
    )
    respx.get("https://acme-trading-co.com").mock(
        return_value=httpx.Response(200, text=anti_bot_html)
    )
    respx.get(_GREENHOUSE.format(slug="acme-trading-co")).mock(
        return_value=httpx.Response(200, json={"jobs": [{}]})
    )
    record = await firmographics.get_company_firmographics("Acme Trading Co")
    # html signals unreliable behind a challenge — degraded honestly
    assert record["website"] == "https://acme-trading-co.com"
    assert record["tech_stack"] == []
    assert record["linkedin_url"] is None
    assert record["industry"] is None
    # non-HTML signals still work
    assert record["hiring_openings"] == 1


@respx.mock
async def test_firmographics_hiring_lever_list_payload() -> None:
    respx.get("https://acme-trading-co.com").mock(
        return_value=httpx.Response(200, text=_firmo_html())
    )
    respx.get(_GREENHOUSE.format(slug="acme-trading-co")).mock(return_value=httpx.Response(404))
    respx.get(_LEVER.format(slug="acme-trading-co")).mock(
        return_value=httpx.Response(200, json=[{}, {}, {}])
    )
    record = await firmographics.get_company_firmographics("Acme Trading Co")
    assert record["hiring_openings"] == 3


@respx.mock
async def test_firmographics_partner_unconfigured_funding_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    respx.get("https://acme-trading-co.com").mock(
        return_value=httpx.Response(200, text=_firmo_html())
    )
    respx.get(_GREENHOUSE.format(slug="acme-trading-co")).mock(return_value=httpx.Response(404))
    respx.get(_LEVER.format(slug="acme-trading-co")).mock(return_value=httpx.Response(404))
    respx.get(_ASHBY.format(slug="acme-trading-co")).mock(return_value=httpx.Response(404))
    record = await firmographics.get_company_firmographics("Acme Trading Co")
    assert record["headcount"] is None
    assert record["funding"] is None
    assert record["total_funding"] is None
    assert record["hiring_openings"] == 0


@respx.mock
async def test_firmographics_http_errors_never_raise() -> None:
    for candidate in (
        "https://acme-trading-co.com",
        "https://acme-trading-co.io",
        "https://acme-trading-co.co",
        "https://acme-trading-co.ai",
    ):
        respx.get(candidate).mock(return_value=httpx.Response(500))
    respx.get(_GREENHOUSE.format(slug="acme-trading-co")).mock(return_value=httpx.Response(500))
    respx.get(_LEVER.format(slug="acme-trading-co")).mock(return_value=httpx.Response(500))
    respx.get(_ASHBY.format(slug="acme-trading-co")).mock(return_value=httpx.Response(500))
    record = await firmographics.get_company_firmographics("Acme Trading Co")
    for key in (
        "name",
        "headcount",
        "funding",
        "total_funding",
        "tech_stack",
        "industry",
        "hiring_openings",
        "linkedin_url",
        "website",
    ):
        assert key in record
    assert record["website"] is None
    assert record["hiring_openings"] == 0


@respx.mock
async def test_firmographics_blank_company_returns_empty_no_network() -> None:
    record = await firmographics.get_company_firmographics("   ")
    assert record["name"] == ""
    assert record["website"] is None
    assert respx.calls.call_count == 0


def test_as_money_parsing() -> None:
    assert firmographics._as_money(40000000) == 40000000
    assert firmographics._as_money("$120M") == 120000000
    assert firmographics._as_money("1.5B") == 1500000000
    assert firmographics._as_money("850K") == 850000
    assert firmographics._as_money("n/a") is None
    assert firmographics._as_money(None) is None


# ── router ─────────────────────────────────────────────────────────────


@pytest.fixture
def supply_app() -> FastAPI:
    app = FastAPI()

    @app.exception_handler(PryError)
    async def pry_error_handler(request: Request, exc: PryError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": str(exc)})

    app.include_router(supply_router)
    return app


def _client(app: FastAPI) -> TestClient:
    return TestClient(app)


def test_router_importable() -> None:
    assert hasattr(supply_data, "get_import_records")
    assert hasattr(supply_data, "get_company_firmographics")
    assert hasattr(supply_router_mod, "router")


def test_router_imports_success(supply_app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake(company: str, limit: int = 20) -> list[dict[str, Any]]:
        return [{"company": company, "hs_code": "8471.30", "source": "imports_partner"}]

    monkeypatch.setattr(imports_mod, "get_import_records", fake)
    resp = _client(supply_app).get("/v1/supply/imports/Acme%20Trading%20Co", params={"limit": 5})
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["company"] == "Acme Trading Co"
    assert body["limit"] == 5
    assert body["data"][0]["hs_code"] == "8471.30"


def test_router_firmographics_success(supply_app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake(company: str) -> dict[str, Any]:
        return {"name": company, "website": "https://acme-trading-co.com", "tech_stack": []}

    monkeypatch.setattr(firmographics, "get_company_firmographics", fake)
    resp = _client(supply_app).get("/v1/supply/firmographics/Acme%20Trading%20Co")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["company"] == "Acme Trading Co"
    assert body["data"]["website"] == "https://acme-trading-co.com"


def test_router_502_when_module_absent(
    supply_app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(supply_router_mod, "_supply_module", lambda name: None)
    assert _client(supply_app).get("/v1/supply/imports/Acme").status_code == 502
    assert _client(supply_app).get("/v1/supply/firmographics/Acme").status_code == 502


def test_router_validation_422(supply_app: FastAPI) -> None:
    assert (
        _client(supply_app).get("/v1/supply/imports/Acme", params={"limit": 0}).status_code == 422
    )
    assert (
        _client(supply_app).get("/v1/supply/imports/Acme", params={"limit": 201}).status_code == 422
    )
