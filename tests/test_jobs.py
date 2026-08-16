"""Tests for the jobs & salary intelligence module (``jobs`` package + router).

All HTTP is mocked with respx — no live network. The ATS boards and
Levels.fyi responses are fixture-shaped so every parse path (Greenhouse,
Lever, Ashby, Workday, salary page, 404s, malformed payloads) is covered.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx
from fastapi import FastAPI
from fastapi.testclient import TestClient

import jobs.ats as ats
import jobs.salary as salary

# ── Fixtures ───────────────────────────────────────────────────────────

GREENHOUSE_URL = "https://boards-api.greenhouse.io/v1/boards/stripe/jobs"
GREENHOUSE_JOB_URL = "https://boards-api.greenhouse.io/v1/boards/stripe/jobs/123"
LEVER_URL = "https://api.lever.co/v0/postings/leverdemo?mode=json"
ASHBY_URL = "https://api.ashbyhq.com/posting-api/job-board/linear?includeCompensation=true"
WORKDAY_URL = "https://acme.wd1.myworkdayjobs.com/wday/cxs/acme/acme/jobs"
LEVELS_URL = "https://www.levels.fyi/companies/google/salaries/software-engineer"
LEVELS_HOME = "https://www.levels.fyi/"

GREENHOUSE_JOBS: dict[str, Any] = {
    "jobs": [
        {
            "id": 123,
            "title": "Backend Engineer",
            "location": {"name": "Remote (US)"},
            "is_remote": True,
            "absolute_url": "https://boards.greenhouse.io/stripe/jobs/123",
            "first_published": "2026-08-01T00:00:00Z",
        },
        {
            "id": 456,
            "title": "Designer",
            "location": {"name": "San Francisco, CA"},
            "is_remote": False,
            "absolute_url": "https://boards.greenhouse.io/stripe/jobs/456",
            "first_published": "2026-08-02T00:00:00Z",
        },
    ]
}

LEVER_JOBS: list[dict[str, Any]] = [
    {
        "id": "abc-123",
        "text": "Fullstack Engineer",
        "categories": {"location": "New York, NY", "allLocations": []},
        "workplaceType": "remote",
        "hostedUrl": "https://jobs.lever.co/leverdemo/abc-123",
        "createdAt": 1720000000000,
        "descriptionPlain": "Build things.",
        "salaryRange": {"min": 120000, "max": 180000, "currency": "USD", "interval": "yearly"},
    }
]

ASHBY_JOBS: dict[str, Any] = {
    "jobs": [
        {
            "id": "job-xyz",
            "title": "Product Engineer",
            "location": "London, UK",
            "remote": False,
            "jobUrl": "https://jobs.ashbyhq.com/linear/job-xyz",
            "publishedAt": "2026-08-03T00:00:00Z",
            "descriptionPlain": "Ship features.",
            "compensation": {"compensationTierSummary": "$150k - $220k"},
        }
    ]
}

WORKDAY_JOBS: dict[str, Any] = {
    "jobPostings": [
        {
            "jobPostingId": "R-100",
            "title": "Solutions Architect",
            "locationsText": "Austin, TX",
            "remote": True,
            "externalPath": "/wday/cxs/acme/acme/jobs/R-100",
            "postedOn": "2026-07-30T00:00:00Z",
        }
    ]
}

LEVELS_HTML = """<!DOCTYPE html><html><head><title>Google SWE Salaries</title></head><body>
<script id="__NEXT_DATA__" type="application/json">{"props":{"pageProps":{
  "company":{"name":"Google"},
  "levels":{"job_family":"Software Engineer"},
  "averages":[
    {"primaryLevelName":"L3","total":202529,"base":161233,"stock":31878,"bonus":9418,"count":103},
    {"primaryLevelName":"L4","total":260000,"base":195000,"stock":55000,"bonus":10000,"count":210}
  ]}}}</script></body></html>"""


@pytest.fixture(autouse=True)
def _clear_jobs_caches() -> None:
    """Isolate the TTL caches between tests."""
    ats._clear_cache()
    salary._clear_cache()


# ── list_jobs: Greenhouse ─────────────────────────────────────────────
@respx.mock
async def test_list_jobs_greenhouse_normalizes_schema() -> None:
    respx.get(GREENHOUSE_URL).mock(return_value=httpx.Response(200, json=GREENHOUSE_JOBS))
    items = await ats.list_jobs("stripe", board="greenhouse")
    assert len(items) == 2
    first = items[0]
    assert set(first) == {"id", "title", "company", "location", "remote", "url", "posted_at"}
    assert first["id"] == "123"
    assert first["company"] == "stripe"
    assert first["remote"] is True
    assert first["location"] == "Remote (US)"
    assert first["posted_at"] == "2026-08-01T00:00:00+00:00"
    assert items[1]["remote"] is False


@respx.mock
async def test_list_jobs_greenhouse_truncates_to_limit() -> None:
    respx.get(GREENHOUSE_URL).mock(return_value=httpx.Response(200, json=GREENHOUSE_JOBS))
    items = await ats.list_jobs("stripe", board="greenhouse", limit=1)
    assert len(items) == 1
    assert items[0]["id"] == "123"


# ── list_jobs: Lever / Ashby / Workday ────────────────────────────────
@respx.mock
async def test_list_jobs_lever_normalizes_schema() -> None:
    respx.get(LEVER_URL).mock(return_value=httpx.Response(200, json=LEVER_JOBS))
    items = await ats.list_jobs("leverdemo", board="lever")
    assert len(items) == 1
    first = items[0]
    assert set(first) == {"id", "title", "company", "location", "remote", "url", "posted_at"}
    assert first["id"] == "abc-123"
    assert first["title"] == "Fullstack Engineer"
    assert first["remote"] is True
    assert first["posted_at"] == "2024-07-03T09:46:40+00:00"


@respx.mock
async def test_list_jobs_ashby_normalizes_schema() -> None:
    respx.get(ASHBY_URL).mock(return_value=httpx.Response(200, json=ASHBY_JOBS))
    items = await ats.list_jobs("linear", board="ashby")
    assert len(items) == 1
    assert items[0]["id"] == "job-xyz"
    assert items[0]["location"] == "London, UK"
    assert items[0]["posted_at"] == "2026-08-03T00:00:00+00:00"


@respx.mock
async def test_list_jobs_workday_posts_json_payload() -> None:
    route = respx.post(WORKDAY_URL).mock(return_value=httpx.Response(200, json=WORKDAY_JOBS))
    items = await ats.list_jobs("acme", board="workday")
    assert len(items) == 1
    first = items[0]
    assert first["id"] == "R-100"
    assert first["remote"] is True
    assert first["url"] == "https://acme.wd1.myworkdayjobs.com/wday/cxs/acme/acme/jobs/R-100"
    assert route.called
    request = route.calls[0].request
    assert request.method == "POST"
    assert request.headers["content-type"] == "application/json"
    assert request.headers["origin"] == "https://acme.wd1.myworkdayjobs.com"


# ── list_jobs: degradation ─────────────────────────────────────────────
@respx.mock
async def test_list_jobs_unknown_board_returns_empty() -> None:
    assert await ats.list_jobs("stripe", board="nope") == []


@respx.mock
async def test_list_jobs_blank_company_returns_empty() -> None:
    assert await ats.list_jobs("   ", board="greenhouse") == []


@respx.mock
async def test_list_jobs_http_error_returns_empty() -> None:
    respx.get(GREENHOUSE_URL).mock(return_value=httpx.Response(503))
    assert await ats.list_jobs("stripe", board="greenhouse") == []


@respx.mock
async def test_list_jobs_bad_json_returns_empty() -> None:
    respx.get(GREENHOUSE_URL).mock(return_value=httpx.Response(200, text="<html>nope</html>"))
    assert await ats.list_jobs("stripe", board="greenhouse") == []


# ── search_jobs ────────────────────────────────────────────────────────
@respx.mock
async def test_search_jobs_filters_by_keyword(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ats, "SEARCH_COMPANIES", (("stripe", "greenhouse"),))
    respx.get(GREENHOUSE_URL).mock(return_value=httpx.Response(200, json=GREENHOUSE_JOBS))
    hits = await ats.search_jobs("remote")
    assert len(hits) == 1
    assert hits[0]["id"] == "123"


@respx.mock
async def test_search_jobs_blank_query_returns_empty() -> None:
    assert await ats.search_jobs("  ") == []


# ── get_job ────────────────────────────────────────────────────────────
@respx.mock
async def test_get_job_greenhouse_detail() -> None:
    detail = {
        "title": "Backend Engineer",
        "location": {"name": "Remote (US)"},
        "content": "<p>Build APIs.</p><ul><li>Python</li></ul>",
        "absolute_url": "https://boards.greenhouse.io/stripe/jobs/123",
        "metadata": [{"name": "Compensation", "value": "$150k - $220k"}],
    }
    respx.get(GREENHOUSE_JOB_URL).mock(return_value=httpx.Response(200, json=detail))
    result = await ats.get_job("123", board="greenhouse", company="stripe")
    assert result["title"] == "Backend Engineer"
    assert result["company"] == "stripe"
    assert "Build APIs" in result["description"]
    assert "Python" in result["description"]
    assert result["compensation"] == "Compensation: $150k - $220k"


@respx.mock
async def test_get_job_lever_detail() -> None:
    respx.get(LEVER_URL).mock(return_value=httpx.Response(200, json=LEVER_JOBS))
    result = await ats.get_job("abc-123", board="lever", company="leverdemo")
    assert result["title"] == "Fullstack Engineer"
    assert result["compensation"] == "120000 - 180000 USD yearly"
    assert result["description"] == "Build things."


@respx.mock
async def test_get_job_missing_company_returns_empty() -> None:
    assert await ats.get_job("123", board="greenhouse") == {}


@respx.mock
async def test_get_job_unknown_board_returns_empty() -> None:
    assert await ats.get_job("123", board="nope", company="stripe") == {}


# ── salary ─────────────────────────────────────────────────────────────
@respx.mock
async def test_get_salary_parses_levels_page() -> None:
    respx.get(LEVELS_URL).mock(return_value=httpx.Response(200, text=LEVELS_HTML))
    result = await salary.get_salary("google")
    assert result["company"] == "Google"
    assert result["role"] == "Software Engineer"
    assert len(result["levels"]) == 2
    assert result["levels"][0] == {
        "level": "L3",
        "total_comp": 202529.0,
        "base_salary": 161233.0,
        "stock": 31878.0,
        "bonus": 9418.0,
    }
    assert result["samples"] == 313


@respx.mock
async def test_get_salary_custom_role_slug() -> None:
    url = "https://www.levels.fyi/companies/google/salaries/product-manager"
    respx.get(url).mock(return_value=httpx.Response(200, text=LEVELS_HTML))
    result = await salary.get_salary("google", role="product_manager")
    assert result["company"] == "Google"


@respx.mock
async def test_get_salary_404_returns_empty() -> None:
    respx.get(LEVELS_URL).mock(return_value=httpx.Response(404))
    respx.get(LEVELS_HOME).mock(return_value=httpx.Response(404))
    assert await salary.get_salary("google") == {}


@respx.mock
async def test_get_salary_blank_company_returns_empty() -> None:
    assert await salary.get_salary("") == {}


@respx.mock
async def test_get_salary_canonical_name_resolution() -> None:
    # Direct slug 404s; homepage index resolves the canonical name, retry succeeds.
    respx.get("https://www.levels.fyi/companies/foo-bar/salaries/software-engineer").mock(
        return_value=httpx.Response(404)
    )
    homepage = """<html><body><script id="__NEXT_DATA__" type="application/json">{"props":{"pageProps":{
      "companiesWithLevels":{"Software Engineer":["Foo Bar Inc."]}
    }}}</script></body></html>"""
    respx.get(LEVELS_HOME).mock(return_value=httpx.Response(200, text=homepage))
    respx.get("https://www.levels.fyi/companies/foo-bar-inc/salaries/software-engineer").mock(
        return_value=httpx.Response(200, text=LEVELS_HTML)
    )
    result = await salary.get_salary("Foo Bar")
    assert result["company"] == "Google"


# ── Router ─────────────────────────────────────────────────────────────
@pytest.fixture
def jobs_client() -> TestClient:
    from routers.jobs import router as jobs_router

    app = FastAPI()
    app.include_router(jobs_router)
    return TestClient(app)


@respx.mock
def test_router_list_jobs(jobs_client: TestClient) -> None:
    respx.get(GREENHOUSE_URL).mock(return_value=httpx.Response(200, json=GREENHOUSE_JOBS))
    response = jobs_client.get("/v1/jobs/greenhouse/stripe")
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert len(body["data"]) == 2
    assert body["board"] == "greenhouse"
    assert body["company"] == "stripe"


@respx.mock
def test_router_list_jobs_bad_board_degrades(jobs_client: TestClient) -> None:
    response = jobs_client.get("/v1/jobs/unknown/stripe")
    assert response.status_code == 200
    assert response.json()["data"] == []


@respx.mock
def test_router_search_jobs(jobs_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ats, "SEARCH_COMPANIES", (("stripe", "greenhouse"),))
    respx.get(GREENHOUSE_URL).mock(return_value=httpx.Response(200, json=GREENHOUSE_JOBS))
    response = jobs_client.get("/v1/jobs/search", params={"q": "engineer"})
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert len(body["data"]) == 1
    assert body["data"][0]["id"] == "123"


@respx.mock
def test_router_get_job(jobs_client: TestClient) -> None:
    detail = {
        "title": "Backend Engineer",
        "location": {"name": "Remote (US)"},
        "content": "<p>Build APIs.</p>",
        "absolute_url": "https://boards.greenhouse.io/stripe/jobs/123",
        "metadata": [],
    }
    respx.get(GREENHOUSE_JOB_URL).mock(return_value=httpx.Response(200, json=detail))
    response = jobs_client.get("/v1/jobs/greenhouse/job/123", params={"company": "stripe"})
    assert response.status_code == 200
    assert response.json()["success"] is True
    assert response.json()["data"]["title"] == "Backend Engineer"


@respx.mock
def test_router_salary(jobs_client: TestClient) -> None:
    respx.get(LEVELS_URL).mock(return_value=httpx.Response(200, text=LEVELS_HTML))
    response = jobs_client.get("/v1/jobs/salary/google")
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["data"]["company"] == "Google"
    assert body["data"]["samples"] == 313
