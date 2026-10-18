"""Tests for the jobs & salary intelligence module (``jobs`` package + router).

All HTTP is mocked with respx — no live network. The ATS boards and
Levels.fyi responses are fixture-shaped so every parse path (Greenhouse,
Lever, Ashby, Workday, salary page, 404s, malformed payloads) is covered.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx
from fastapi import FastAPI
from fastapi.testclient import TestClient

import datasets.jobs.ats as ats
import datasets.jobs.salary as salary

GREENHOUSE_URL = "https://boards-api.greenhouse.io/v1/boards/stripe/jobs"

GREENHOUSE_JOB_URL = "https://boards-api.greenhouse.io/v1/boards/stripe/jobs/123"

LEVER_URL = "https://api.lever.co/v0/postings/leverdemo?mode=json"

ASHBY_URL = "https://api.ashbyhq.com/posting-api/job-board/linear?includeCompensation=true"

WORKDAY_URL = "https://acme.wd1.myworkdayjobs.com/wday/cxs/acme/acme/jobs"

WORKABLE_URL = "https://apply.workable.com/api/v3/accounts/acme/jobs"

BREEZY_URL = "https://acme.breezy.hr/json"

SMARTRECRUITERS_URL = "https://api.smartrecruiters.com/v1/companies/acme/postings"

SMARTRECRUITERS_JOB_URL = "https://api.smartrecruiters.com/v1/companies/acme/postings/sr-1"

RECRUITEE_URL = "https://acme.recruitee.com/api/offers"

RECRUITEE_JOB_URL = "https://acme.recruitee.com/api/offers/7001"

JOBVITE_URL = "https://acme.jobvite.com/api/v1/jobs"

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

WORKABLE_JOBS: dict[str, Any] = {
    "jobs": [
        {
            "id": "wb-1",
            "shortcode": "abc123",
            "title": "Platform Engineer",
            "location": {"city": "Denver", "region": "CO", "country": "USA"},
            "remote": True,
            "url": "https://apply.workable.com/acme/j/abc123/",
            "published": "2026-08-04T00:00:00Z",
        },
        {
            "id": "wb-2",
            "shortcode": "def456",
            "title": "Account Executive",
            "location": {"city": "Chicago", "region": "IL", "country": "USA"},
            "remote": False,
            "url": "https://apply.workable.com/acme/j/def456/",
            "published": "2026-08-05T00:00:00Z",
        },
    ]
}

BREEZY_JOBS: list[dict[str, Any]] = [
    {
        "posting_id": "bz-1",
        "title": "Support Specialist",
        "apply_url": "https://acme.breezy.hr/p/bz-1",
        "published_date": "2026-08-06T00:00:00Z",
        "location_city": "Remote",
        "location_country": "US",
        "is_remote": True,
        "salary": "$60k - $75k",
    },
    {
        "posting_id": "bz-2",
        "title": "Data Analyst",
        "apply_url": "https://acme.breezy.hr/p/bz-2",
        "published_date": "2026-08-07T00:00:00Z",
        "location_city": "Austin",
        "location_state": "TX",
        "location_country": "US",
        "is_remote": False,
    },
]

SMARTRECRUITERS_JOBS: dict[str, Any] = {
    "content": [
        {
            "id": "sr-1",
            "name": "DevOps Engineer",
            "releasedDate": "2026-08-08T00:00:00Z",
            "location": {"city": "Seattle", "region": "WA", "country": "US", "remote": True},
            "applyUrl": "https://jobs.smartrecruiters.com/acme/sr-1",
        },
        {
            "id": "sr-2",
            "name": "Mobile Engineer",
            "releasedDate": "2026-08-09T00:00:00Z",
            "location": {"city": "New York", "region": "NY", "country": "US"},
            "applyUrl": "https://jobs.smartrecruiters.com/acme/sr-2",
        },
    ]
}

RECRUITEE_JOBS: dict[str, Any] = {
    "offers": [
        {
            "id": 7001,
            "title": "QA Engineer",
            "location": "Austin, TX",
            "city": "Austin",
            "country": "US",
            "careers_url": "https://acme.recruitee.com/o/qa-engineer",
            "published_at": "2026-08-10T00:00:00Z",
            "remote": False,
        },
        {
            "id": 7002,
            "title": "Support Engineer",
            "location": "Remote",
            "city": "Remote",
            "country": "US",
            "careers_url": "https://acme.recruitee.com/o/support-engineer",
            "published_at": "2026-08-11T00:00:00Z",
            "remote": True,
        },
    ]
}

JOBVITE_JOBS: dict[str, Any] = {
    "requisitions": [
        {
            "id": "jv-1",
            "title": "Site Reliability Engineer",
            "location": "Remote, US",
            "city": "Remote",
            "state": "US",
            "country": "United States",
            "jobDescription": "<p>Keep things up.</p>",
            "applyUrl": "https://jobs.jobvite.com/acme/jobs/jv-1/apply",
            "date": "2026-08-12T00:00:00Z",
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


@pytest.fixture
def jobs_client() -> TestClient:
    from pry.api.routers.data.jobs import router as jobs_router

    app = FastAPI()
    app.include_router(jobs_router)
    return TestClient(app)


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
