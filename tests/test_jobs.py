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

import datasets.jobs.ats as ats
import datasets.jobs.salary as salary

# ── Fixtures ───────────────────────────────────────────────────────────

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


# ── list_jobs: Workable / Breezy HR ───────────────────────────────────
@respx.mock
async def test_list_jobs_workable_normalizes_schema() -> None:
    respx.get(WORKABLE_URL).mock(return_value=httpx.Response(200, json=WORKABLE_JOBS))
    items = await ats.list_jobs("acme", board="workable")
    assert len(items) == 2
    first = items[0]
    assert set(first) == {"id", "title", "company", "location", "remote", "url", "posted_at"}
    assert first["id"] == "wb-1"
    assert first["title"] == "Platform Engineer"
    assert first["location"] == "Denver, CO, USA"
    assert first["remote"] is True
    assert first["posted_at"] == "2026-08-04T00:00:00+00:00"
    assert items[1]["remote"] is False


@respx.mock
async def test_list_jobs_workable_empty_payload_returns_empty() -> None:
    respx.get(WORKABLE_URL).mock(return_value=httpx.Response(200, json={"jobs": []}))
    assert await ats.list_jobs("acme", board="workable") == []


@respx.mock
async def test_list_jobs_breezy_normalizes_schema() -> None:
    respx.get(BREEZY_URL).mock(return_value=httpx.Response(200, json=BREEZY_JOBS))
    items = await ats.list_jobs("acme", board="breezy")
    assert len(items) == 2
    first = items[0]
    assert set(first) == {"id", "title", "company", "location", "remote", "url", "posted_at"}
    assert first["id"] == "bz-1"
    assert first["title"] == "Support Specialist"
    assert first["location"] == "Remote, US"
    assert first["remote"] is True
    assert first["url"] == "https://acme.breezy.hr/p/bz-1"
    assert first["posted_at"] == "2026-08-06T00:00:00+00:00"
    assert items[1]["location"] == "Austin, TX, US"
    assert items[1]["remote"] is False


@respx.mock
async def test_list_jobs_breezy_dict_payload_uses_postings() -> None:
    respx.get(BREEZY_URL).mock(return_value=httpx.Response(200, json={"postings": BREEZY_JOBS}))
    items = await ats.list_jobs("acme", board="breezy")
    assert len(items) == 2
    assert items[0]["id"] == "bz-1"


@respx.mock
async def test_list_jobs_breezy_http_error_returns_empty() -> None:
    respx.get(BREEZY_URL).mock(return_value=httpx.Response(500))
    assert await ats.list_jobs("acme", board="breezy") == []


# ── get_job: Workable / Breezy HR ─────────────────────────────────────
@respx.mock
async def test_get_job_workable_detail() -> None:
    respx.get(WORKABLE_URL).mock(return_value=httpx.Response(200, json=WORKABLE_JOBS))
    result = await ats.get_job("wb-1", board="workable", company="acme")
    assert result["title"] == "Platform Engineer"
    assert result["company"] == "acme"
    assert result["location"] == "Denver, CO, USA"
    assert result["url"] == "https://apply.workable.com/acme/j/abc123/"


@respx.mock
async def test_get_job_breezy_detail() -> None:
    respx.get(BREEZY_URL).mock(return_value=httpx.Response(200, json=BREEZY_JOBS))
    result = await ats.get_job("bz-1", board="breezy", company="acme")
    assert result["title"] == "Support Specialist"
    assert result["company"] == "acme"
    assert result["location"] == "Remote, US"
    assert result["compensation"] == "$60k - $75k"
    assert result["url"] == "https://acme.breezy.hr/p/bz-1"


# ── list_jobs: SmartRecruiters / Recruitee / Jobvite ─────────────────
@respx.mock
async def test_list_jobs_smartrecruiters_normalizes_schema() -> None:
    respx.get(SMARTRECRUITERS_URL).mock(return_value=httpx.Response(200, json=SMARTRECRUITERS_JOBS))
    items = await ats.list_jobs("acme", board="smartrecruiters")
    assert len(items) == 2
    first = items[0]
    assert set(first) == {"id", "title", "company", "location", "remote", "url", "posted_at"}
    assert first["id"] == "sr-1"
    assert first["title"] == "DevOps Engineer"
    assert first["company"] == "acme"
    assert first["location"] == "Seattle, WA, US"
    assert first["remote"] is True
    assert first["url"] == "https://jobs.smartrecruiters.com/acme/sr-1"
    assert first["posted_at"] == "2026-08-08T00:00:00+00:00"
    assert items[1]["remote"] is False


@respx.mock
async def test_list_jobs_recruitee_normalizes_schema() -> None:
    respx.get(RECRUITEE_URL).mock(return_value=httpx.Response(200, json=RECRUITEE_JOBS))
    items = await ats.list_jobs("acme", board="recruitee")
    assert len(items) == 2
    first = items[0]
    assert set(first) == {"id", "title", "company", "location", "remote", "url", "posted_at"}
    assert first["id"] == "7001"
    assert first["title"] == "QA Engineer"
    assert first["location"] == "Austin, TX"
    assert first["remote"] is False
    assert first["posted_at"] == "2026-08-10T00:00:00+00:00"
    assert items[1]["remote"] is True


@respx.mock
async def test_list_jobs_jobvite_normalizes_schema() -> None:
    respx.get(JOBVITE_URL).mock(return_value=httpx.Response(200, json=JOBVITE_JOBS))
    items = await ats.list_jobs("acme", board="jobvite")
    assert len(items) == 1
    first = items[0]
    assert set(first) == {"id", "title", "company", "location", "remote", "url", "posted_at"}
    assert first["id"] == "jv-1"
    assert first["title"] == "Site Reliability Engineer"
    assert first["location"] == "Remote, US"
    assert first["remote"] is True
    assert first["url"] == "https://jobs.jobvite.com/acme/jobs/jv-1/apply"
    assert first["posted_at"] == "2026-08-12T00:00:00+00:00"


@respx.mock
async def test_list_jobs_smartrecruiters_http_error_returns_empty() -> None:
    respx.get(SMARTRECRUITERS_URL).mock(return_value=httpx.Response(500))
    assert await ats.list_jobs("acme", board="smartrecruiters") == []


@respx.mock
async def test_list_jobs_recruitee_bad_json_returns_empty() -> None:
    respx.get(RECRUITEE_URL).mock(return_value=httpx.Response(200, text="<html>nope</html>"))
    assert await ats.list_jobs("acme", board="recruitee") == []


# ── get_job: SmartRecruiters / Recruitee / Jobvite ────────────────────
@respx.mock
async def test_get_job_smartrecruiters_detail() -> None:
    detail = {
        "id": "sr-1",
        "name": "DevOps Engineer",
        "location": {"city": "Seattle", "region": "WA", "country": "US", "remote": True},
        "applyUrl": "https://jobs.smartrecruiters.com/acme/sr-1",
        "compensation": {"currency": "USD", "min": 120000, "max": 180000, "salaryPeriod": "YEAR"},
        "jobAd": {
            "sections": {
                "jobDescription": {"text": "<p>Run the fleet.</p>", "label": "Job Description"},
                "qualifications": {
                    "text": "<p>5+ years Kubernetes.</p>",
                    "label": "Qualifications",
                },
            }
        },
    }
    respx.get(SMARTRECRUITERS_JOB_URL).mock(return_value=httpx.Response(200, json=detail))
    result = await ats.get_job("sr-1", board="smartrecruiters", company="acme")
    assert result["title"] == "DevOps Engineer"
    assert result["company"] == "acme"
    assert result["location"] == "Seattle, WA, US"
    assert "Run the fleet" in result["description"]
    assert "5+ years Kubernetes" in result["requirements"]
    assert result["compensation"] == "120000 - 180000 USD YEAR"
    assert result["url"] == "https://jobs.smartrecruiters.com/acme/sr-1"


@respx.mock
async def test_get_job_smartrecruiters_detail_error_returns_empty() -> None:
    respx.get(SMARTRECRUITERS_JOB_URL).mock(return_value=httpx.Response(404))
    assert await ats.get_job("sr-1", board="smartrecruiters", company="acme") == {}


@respx.mock
async def test_get_job_recruitee_detail() -> None:
    detail = {
        "offer": {
            "id": 7001,
            "title": "QA Engineer",
            "location": "Austin, TX",
            "description": "<p>Write tests.</p>",
            "requirements": "<ul><li>Python</li></ul>",
            "careers_url": "https://acme.recruitee.com/o/qa-engineer",
            "salary_min": 90000,
            "salary_max": 120000,
            "salary_currency": "USD",
            "salary_period": "yearly",
        }
    }
    respx.get(RECRUITEE_JOB_URL).mock(return_value=httpx.Response(200, json=detail))
    result = await ats.get_job("7001", board="recruitee", company="acme")
    assert result["title"] == "QA Engineer"
    assert result["company"] == "acme"
    assert result["location"] == "Austin, TX"
    assert "Write tests" in result["description"]
    assert "Python" in result["requirements"]
    assert result["compensation"] == "USD 90000 - 120000 yearly"
    assert result["url"] == "https://acme.recruitee.com/o/qa-engineer"


@respx.mock
async def test_get_job_recruitee_detail_missing_offer_returns_empty() -> None:
    respx.get(RECRUITEE_JOB_URL).mock(return_value=httpx.Response(200, json={"offer": {}}))
    assert await ats.get_job("7001", board="recruitee", company="acme") == {}


@respx.mock
async def test_get_job_jobvite_detail() -> None:
    respx.get(JOBVITE_URL).mock(return_value=httpx.Response(200, json=JOBVITE_JOBS))
    result = await ats.get_job("jv-1", board="jobvite", company="acme")
    assert result["title"] == "Site Reliability Engineer"
    assert result["company"] == "acme"
    assert result["location"] == "Remote, US"
    assert "Keep things up" in result["description"]
    assert result["url"] == "https://jobs.jobvite.com/acme/jobs/jv-1/apply"


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
    from pry.api.routers.data.jobs import router as jobs_router

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
