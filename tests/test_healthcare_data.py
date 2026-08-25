# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for the healthcare_data package (clinical trials / drug pricing / insurance).

Covers clinicaltrials.gov v2 search + lookup (mapping, phase/status
normalization, never-raise degradation), NADAC drug pricing via the DKAN
metastore → weekly CSV flow (best-match selection, GoodRx fallback,
never-raise degradation), insurance quote feasibility (captcha-gated probe
→ documented ``available: False``; parseable page → real quotes; public
rate-table scraping), and the /v1/health/* router (200 + 502-degradation +
422 validation).

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

import datasets.healthcare_data as healthcare_data
import datasets.healthcare_data.clinical_trials as clinical_trials
import datasets.healthcare_data.drug_pricing as drug_pricing
import datasets.healthcare_data.insurance as insurance
import pry.api.routers.healthcare_data as health_router_mod
from pry.api.routers.healthcare_data import router as health_router
from pry.core.errors import PryError
from pry.engine.retry import RetryConfig

_TRIALS = "https://clinicaltrials.gov/api/v2/studies"
_NADAC_SEARCH = "https://data.medicaid.gov/api/1/search"
_NADAC_METASTORE = "https://data.medicaid.gov/api/1/metastore/schemas/dataset/items/"
_NADAC_CSV = (
    "https://download.medicaid.gov/data/nadac-national-average-drug-acquisition-cost-12-31-2025.csv"
)
_GOODRX = "https://www.goodrx.com/"
_III_AUTO = "https://www.iii.org/fact-statistic/facts-statistics-auto-insurance"
_AUTO_PROVIDERS = (
    "https://www.progressive.com/auto/",
    "https://www.geico.com/quote/auto/",
    "https://www.statefarm.com/insurance/auto/start",
)

_ZERO_RETRY = RetryConfig(
    max_retries=1, base_delay=0.0, max_delay=0.0, retryable_exceptions=(httpx.HTTPError,)
)


@pytest.fixture(autouse=True)
def _hermetic_healthcare(monkeypatch: pytest.MonkeyPatch) -> None:
    """Kill retry backoff and drop in-process caches so tests are deterministic."""
    drug_pricing._clear_caches()
    monkeypatch.setattr(clinical_trials, "_RETRY_CONFIG", _ZERO_RETRY)
    monkeypatch.setattr(drug_pricing, "_RETRY_CONFIG", _ZERO_RETRY)
    monkeypatch.setattr(insurance, "_RETRY_CONFIG", _ZERO_RETRY)
    monkeypatch.setattr(insurance, "_PROBE_RETRY", _ZERO_RETRY)


# ── Payload fixtures ───────────────────────────────────────────────────


def _trial_study(nct_id: str = "NCT05966207") -> dict[str, Any]:
    return {
        "protocolSection": {
            "identificationModule": {
                "nctId": nct_id,
                "briefTitle": "Individual Intervention of Cognitive Stimulation",
                "officialTitle": "Individual Intervention of Cognitive Stimulation",
            },
            "statusModule": {
                "overallStatus": "RECRUITING",
                "startDateStruct": {"date": "2021-12-27", "type": "ACTUAL"},
            },
            "designModule": {"phases": ["PHASE1", "PHASE2"]},
            "conditionsModule": {"conditions": ["Cognitive Dysfunction"]},
            "sponsorCollaboratorsModule": {
                "leadSponsor": {
                    "name": "Escola Superior de Enfermagem de Coimbra",
                    "class": "OTHER",
                }
            },
            "contactsLocationsModule": {
                "locations": [
                    {
                        "facility": "The Health Sciences Research Unit: Nursing",
                        "city": "Coimbra",
                        "country": "Portugal",
                    },
                    {"city": "Lisbon", "country": "Portugal"},
                ]
            },
        }
    }


def _trial_search_payload() -> dict[str, Any]:
    return {"studies": [_trial_study()], "totalCount": 1, "nextPageToken": None}


def _nadac_metastore_payload(csv_url: str) -> dict[str, Any]:
    return {
        "identifier": "99315a95-37ac-4eee-946a-3c523b4c481e",
        "distribution": [
            {
                "data": {
                    "@type": "dcat:Distribution",
                    "format": "csv",
                    "downloadURL": csv_url,
                }
            }
        ],
    }


_NADAC_CSV_TEXT = (
    "NDC Description,NDC,NADAC Per Unit,Effective Date,Pricing Unit,"
    "Pharmacy Type Indicator,OTC,Explanation Code,Classification for Rate Setting,"
    "Corresponding Generic Drug NADAC Per Unit,Corresponding Generic Drug Effective Date,As of Date\n"
    "ATORVASTATIN CALCIUM 10 MG,00093072098,0.02633,12/24/2025,EA,C/I,N,1,G,,,01/01/2026\n"
    "ATORVASTATIN CALCIUM 20 MG,00093072101,0.05200,12/24/2025,EA,C/I,N,1,G,,,01/01/2026\n"
    "ATORVASTATIN CALCIUM 10 MG,00093072099,0.02500,12/17/2025,EA,C/I,N,1,G,,,01/01/2026\n"
    "LIPITOR 10 MG,00071015518,0.28910,12/24/2025,EA,C/I,N,1,G,,,01/01/2026\n"
)


def _goodrx_page(price: str) -> str:
    return (
        "<html><head>"
        f'<script type="application/ld+json">'
        f'{{"@type": "Product", "name": "test drug", '
        f'"offers": {{"@type": "Offer", "price": "{price}"}}}}</script>'
        "</head><body></body></html>"
    )


def _quote_page(price: str) -> str:
    return (
        "<html><body>"
        f'<script type="application/ld+json">'
        f'{{"@type": "Product", "name": "auto quote", '
        f'"offers": {{"@type": "Offer", "price": "{price}"}}}}</script>'
        "</body></html>"
    )


_RATE_TABLE_HTML = """<html><body>
<table>
<tr><th>State</th><th>Average annual premium</th></tr>
<tr><td>California</td><td>$2,345</td></tr>
<tr><td>Texas</td><td>$1,800</td></tr>
<tr><td>New Hampshire</td><td>$983</td></tr>
</table>
</body></html>"""

# Mirrors the real III paired layout: most/least expensive states side by
# side in one row, values rendered without a leading "$".
_III_PAIRED_HTML = """<html><body>
<table>
<tr><th>Rank</th><th>Most expensive states</th><th>Average expenditure</th>
    <th>Rank</th><th>Least expensive states</th><th>Average expenditure</th></tr>
<tr><td>1</td><td>New York</td><td>1,511.04</td><td>1</td><td>North Dakota</td><td>691.50</td></tr>
<tr><td>2</td><td>Louisiana</td><td>1,500.38</td><td>2</td><td>Maine</td><td>712.97</td></tr>
</table>
</body></html>"""


# ── package / router importability ─────────────────────────────────────


def test_package_and_router_importable() -> None:
    assert hasattr(healthcare_data, "search_trials")
    assert hasattr(healthcare_data, "get_trial")
    assert hasattr(healthcare_data, "get_drug_price")
    assert hasattr(healthcare_data, "get_insurance_quotes")
    assert hasattr(healthcare_data, "get_insurance_rate_table")
    assert hasattr(health_router_mod, "router")
    paths = {route.path for route in health_router.routes}
    assert "/v1/health/trials/search" in paths
    assert "/v1/health/trials/{nct_id}" in paths
    assert "/v1/health/drug/{drug}" in paths
    assert "/v1/health/insurance/quotes" in paths


# ── clinical_trials: search ────────────────────────────────────────────


@respx.mock
async def test_search_trials_success() -> None:
    respx.get(url__startswith=_TRIALS).mock(
        return_value=httpx.Response(200, json=_trial_search_payload())
    )
    results = await clinical_trials.search_trials("alzheimer", limit=5)
    assert len(results) == 1
    record = results[0]
    assert record["nct_id"] == "NCT05966207"
    assert record["title"] == "Individual Intervention of Cognitive Stimulation"
    assert record["status"] == "Recruiting"
    assert record["phase"] == "Phase 1 | Phase 2"
    assert record["conditions"] == ["Cognitive Dysfunction"]
    assert record["sponsor"] == "Escola Superior de Enfermagem de Coimbra"
    assert record["start_date"] == "2021-12-27"
    assert record["locations"][0]["facility"] == "The Health Sciences Research Unit: Nursing"
    assert record["locations"][0]["city"] == "Coimbra"
    assert record["locations"][1]["city"] == "Lisbon"  # no facility → still mapped
    assert record["locations"][1]["country"] == "Portugal"


@respx.mock
async def test_search_trials_phase_na_normalized() -> None:
    study = _trial_study()
    study["protocolSection"]["designModule"]["phases"] = ["NA"]
    study["protocolSection"]["statusModule"]["overallStatus"] = "ACTIVE_NOT_RECRUITING"
    respx.get(url__startswith=_TRIALS).mock(
        return_value=httpx.Response(200, json={"studies": [study]})
    )
    results = await clinical_trials.search_trials("covid")
    assert results[0]["phase"] == "N/A"
    assert results[0]["status"] == "Active, not recruiting"


@respx.mock
async def test_search_trials_empty_query_returns_empty() -> None:
    assert await clinical_trials.search_trials("   ") == []
    assert respx.calls.call_count == 0


@respx.mock
async def test_search_trials_http_error_returns_empty() -> None:
    respx.get(url__startswith=_TRIALS).mock(return_value=httpx.Response(500))
    assert await clinical_trials.search_trials("alzheimer") == []


@respx.mock
async def test_search_trials_malformed_payload_returns_empty() -> None:
    respx.get(url__startswith=_TRIALS).mock(return_value=httpx.Response(200, json={"nope": True}))
    assert await clinical_trials.search_trials("alzheimer") == []


@respx.mock
async def test_search_trials_limit_clamped() -> None:
    async def _assert_params(request: httpx.Request) -> httpx.Response:
        assert request.url.params["pageSize"] == "100"  # 0 clamped up
        return httpx.Response(200, json={"studies": []})

    respx.get(url__startswith=_TRIALS).mock(side_effect=_assert_params)
    assert await clinical_trials.search_trials("alzheimer", limit=0) == []


# ── clinical_trials: get ───────────────────────────────────────────────


@respx.mock
async def test_get_trial_success() -> None:
    respx.get(f"{_TRIALS}/NCT05966207").mock(return_value=httpx.Response(200, json=_trial_study()))
    record = await clinical_trials.get_trial("NCT05966207")
    assert record["nct_id"] == "NCT05966207"
    assert record["status"] == "Recruiting"
    assert record["conditions"] == ["Cognitive Dysfunction"]


@respx.mock
async def test_get_trial_not_found_returns_empty() -> None:
    respx.get(f"{_TRIALS}/NCT99999999").mock(return_value=httpx.Response(404))
    assert await clinical_trials.get_trial("NCT99999999") == {}


@respx.mock
async def test_get_trial_http_error_returns_empty() -> None:
    respx.get(url__startswith=_TRIALS).mock(return_value=httpx.Response(500))
    assert await clinical_trials.get_trial("NCT05966207") == {}


@respx.mock
async def test_get_trial_invalid_id_returns_empty() -> None:
    assert await clinical_trials.get_trial("12345") == {}  # not NCT-prefixed
    assert await clinical_trials.get_trial("") == {}
    assert respx.calls.call_count == 0


# ── drug_pricing: NADAC ────────────────────────────────────────────────


@respx.mock
async def test_get_drug_price_nadac_success() -> None:
    respx.get(url__startswith=_NADAC_SEARCH).mock(
        return_value=httpx.Response(
            200,
            json={
                "results": {
                    "dkan_dataset/x": {
                        "title": "NADAC (National Average Drug Acquisition Cost) 2024",
                        "identifier": "99315a95-37ac-4eee-946a-3c523b4c481e",
                    }
                }
            },
        )
    )
    respx.get(url__startswith=_NADAC_METASTORE).mock(
        return_value=httpx.Response(200, json=_nadac_metastore_payload(_NADAC_CSV))
    )
    respx.get(_NADAC_CSV).mock(return_value=httpx.Response(200, text=_NADAC_CSV_TEXT))

    record = await drug_pricing.get_drug_price("atorvastatin")
    assert record["drug"] == "ATORVASTATIN CALCIUM 10 MG"
    assert record["ndc"] == "00093072098"
    assert record["price_per_unit"] == 0.02633
    assert record["price_type"] == "NADAC per EA"
    assert record["source"] == "nadac"
    assert record["effective_date"] == "2025-12-24"
    assert record["pricing_unit"] == "EA"
    assert record["otc"] == "N"


@respx.mock
async def test_get_drug_price_picks_most_recent_effective_date() -> None:
    # Same NDC description twice; the 12/24 row must win over 12/17.
    respx.get(url__startswith=_NADAC_SEARCH).mock(return_value=httpx.Response(200, json={}))
    respx.get(url__startswith=_NADAC_METASTORE).mock(
        return_value=httpx.Response(200, json=_nadac_metastore_payload(_NADAC_CSV))
    )
    respx.get(_NADAC_CSV).mock(return_value=httpx.Response(200, text=_NADAC_CSV_TEXT))

    record = await drug_pricing.get_drug_price("atorvastatin")
    assert record["ndc"] == "00093072098"  # newest effective date + lowest NDC
    assert record["price_per_unit"] == 0.02633


@respx.mock
async def test_get_drug_price_brand_name_matches_generic_description() -> None:
    respx.get(url__startswith=_NADAC_SEARCH).mock(return_value=httpx.Response(200, json={}))
    respx.get(url__startswith=_NADAC_METASTORE).mock(
        return_value=httpx.Response(200, json=_nadac_metastore_payload(_NADAC_CSV))
    )
    respx.get(_NADAC_CSV).mock(return_value=httpx.Response(200, text=_NADAC_CSV_TEXT))

    record = await drug_pricing.get_drug_price("Lipitor")
    assert record["drug"] == "LIPITOR 10 MG"
    assert record["ndc"] == "00071015518"
    assert record["source"] == "nadac"


@respx.mock
async def test_get_drug_price_no_match_falls_back_to_goodrx() -> None:
    respx.get(url__startswith=_NADAC_SEARCH).mock(return_value=httpx.Response(200, json={}))
    respx.get(url__startswith=_NADAC_METASTORE).mock(
        return_value=httpx.Response(200, json=_nadac_metastore_payload(_NADAC_CSV))
    )
    respx.get(_NADAC_CSV).mock(return_value=httpx.Response(200, text=_NADAC_CSV_TEXT))
    respx.get(f"{_GOODRX}fancy-brand").mock(
        return_value=httpx.Response(200, text=_goodrx_page("45.99"))
    )

    record = await drug_pricing.get_drug_price("Fancy Brand")
    assert record["drug"] == "Fancy Brand"
    assert record["ndc"] is None
    assert record["price_per_unit"] == 45.99
    assert record["price_type"] == "goodrx_retail"
    assert record["source"] == "goodrx"
    assert record["url"].startswith(_GOODRX)


@respx.mock
async def test_get_drug_price_no_match_goodrx_gated_returns_empty() -> None:
    respx.get(url__startswith=_NADAC_SEARCH).mock(return_value=httpx.Response(200, json={}))
    respx.get(url__startswith=_NADAC_METASTORE).mock(
        return_value=httpx.Response(200, json=_nadac_metastore_payload(_NADAC_CSV))
    )
    respx.get(_NADAC_CSV).mock(return_value=httpx.Response(200, text=_NADAC_CSV_TEXT))
    respx.get(f"{_GOODRX}not-a-real-drug").mock(return_value=httpx.Response(403))

    assert await drug_pricing.get_drug_price("Not A Real Drug") == {}


@respx.mock
async def test_get_drug_price_metastore_down_returns_empty() -> None:
    respx.get(url__startswith=_NADAC_SEARCH).mock(return_value=httpx.Response(200, json={}))
    respx.get(url__startswith=_NADAC_METASTORE).mock(return_value=httpx.Response(500))
    assert await drug_pricing.get_drug_price("atorvastatin") == {}


@respx.mock
async def test_get_drug_price_csv_error_returns_empty() -> None:
    respx.get(url__startswith=_NADAC_SEARCH).mock(return_value=httpx.Response(200, json={}))
    respx.get(url__startswith=_NADAC_METASTORE).mock(
        return_value=httpx.Response(200, json=_nadac_metastore_payload(_NADAC_CSV))
    )
    respx.get(_NADAC_CSV).mock(return_value=httpx.Response(500))
    respx.get(url__startswith=_GOODRX).mock(return_value=httpx.Response(403))
    assert await drug_pricing.get_drug_price("atorvastatin") == {}


@respx.mock
async def test_get_drug_price_empty_name_returns_empty() -> None:
    assert await drug_pricing.get_drug_price("   ") == {}
    assert respx.calls.call_count == 0


# ── insurance: quotes ──────────────────────────────────────────────────


@respx.mock
async def test_get_insurance_quotes_gated_returns_available_false() -> None:
    for url in _AUTO_PROVIDERS:
        respx.get(url__startswith=url).mock(return_value=httpx.Response(403))
    result = await insurance.get_insurance_quotes({"coverage_type": "auto", "zip": "90210"})
    assert result["available"] is False
    assert result["coverage_type"] == "auto"
    assert result["quotes"] == []
    assert "captcha" in result["reason"]
    assert result["sources_checked"] == ["progressive", "geico", "statefarm"]


@respx.mock
async def test_get_insurance_quotes_challenge_page_is_gated() -> None:
    for url in _AUTO_PROVIDERS:
        respx.get(url__startswith=url).mock(
            return_value=httpx.Response(
                200,
                headers={"content-type": "text/html"},
                text="<html>Checking your browser... cf-challenge captcha verify you are human</html>",
            )
        )
    result = await insurance.get_insurance_quotes({"coverage_type": "auto"})
    assert result["available"] is False
    assert result["quotes"] == []


@respx.mock
async def test_get_insurance_quotes_parseable_provider_returns_quotes() -> None:
    respx.get(url__startswith=_AUTO_PROVIDERS[0]).mock(
        return_value=httpx.Response(403)  # progressive gated
    )
    respx.get(url__startswith=_AUTO_PROVIDERS[1]).mock(
        return_value=httpx.Response(
            200,
            headers={"content-type": "text/html"},
            text=_quote_page("129.99"),
        )
    )
    respx.get(url__startswith=_AUTO_PROVIDERS[2]).mock(
        return_value=httpx.Response(403)  # statefarm gated
    )
    result = await insurance.get_insurance_quotes({"coverage_type": "auto", "zip": "90210"})
    assert result["available"] is True
    assert result["coverage_type"] == "auto"
    assert result["quotes"] == [
        {"provider": "geico", "premium": 129.99, "deductible": None, "url": _AUTO_PROVIDERS[1]}
    ]


@respx.mock
async def test_get_insurance_quotes_unsupported_coverage_returns_available_false() -> None:
    result = await insurance.get_insurance_quotes({"coverage_type": "life"})
    assert result["available"] is False
    assert "unsupported coverage_type" in result["reason"]
    assert result["quotes"] == []
    assert respx.calls.call_count == 0


@respx.mock
async def test_get_insurance_quotes_empty_profile_defaults_auto() -> None:
    for url in _AUTO_PROVIDERS:
        respx.get(url__startswith=url).mock(return_value=httpx.Response(403))
    result = await insurance.get_insurance_quotes({})
    assert result["available"] is False
    assert result["coverage_type"] == "auto"


# ── insurance: public rate tables ──────────────────────────────────────


@respx.mock
async def test_get_insurance_rate_table_success() -> None:
    respx.get(_III_AUTO).mock(return_value=httpx.Response(200, text=_RATE_TABLE_HTML))
    rows = await insurance.get_insurance_rate_table()
    assert len(rows) == 3
    assert rows[0]["state"] == "California"
    assert rows[0]["premium"] == 2345.0
    assert rows[0]["source"] == "public_rate_table"
    assert rows[0]["url"] == _III_AUTO


@respx.mock
async def test_get_insurance_rate_table_parses_paired_iii_table() -> None:
    respx.get(_III_AUTO).mock(return_value=httpx.Response(200, text=_III_PAIRED_HTML))
    rows = await insurance.get_insurance_rate_table()
    assert len(rows) == 4  # both halves of both rows
    by_state = {row["state"]: row["premium"] for row in rows}
    assert by_state["New York"] == 1511.04
    assert by_state["North Dakota"] == 691.50
    assert by_state["Louisiana"] == 1500.38
    assert by_state["Maine"] == 712.97


@respx.mock
async def test_get_insurance_rate_table_filter_by_abbreviation() -> None:
    respx.get(_III_AUTO).mock(return_value=httpx.Response(200, text=_RATE_TABLE_HTML))
    rows = await insurance.get_insurance_rate_table(state="CA")
    assert len(rows) == 1
    assert rows[0]["state"] == "California"


@respx.mock
async def test_get_insurance_rate_table_abbr_does_not_substring_match() -> None:
    # "CA" must match California only — NOT "North Carolina".
    html = """<html><body><table>
<tr><th>State</th><th>Average annual premium</th></tr>
<tr><td>California</td><td>1,403</td></tr>
<tr><td>North Carolina</td><td>780</td></tr>
<tr><td>Alabama</td><td>1,610</td></tr>
</table></body></html>"""
    respx.get(_III_AUTO).mock(return_value=httpx.Response(200, text=html))
    rows = await insurance.get_insurance_rate_table(state="CA")
    assert [row["state"] for row in rows] == ["California"]
    rows = await insurance.get_insurance_rate_table(state="AL")
    assert [row["state"] for row in rows] == ["Alabama"]  # not Alaska


@respx.mock
async def test_get_insurance_rate_table_filter_by_name() -> None:
    respx.get(_III_AUTO).mock(return_value=httpx.Response(200, text=_RATE_TABLE_HTML))
    rows = await insurance.get_insurance_rate_table(state="Texas")
    assert len(rows) == 1
    assert rows[0]["premium"] == 1800.0


@respx.mock
async def test_get_insurance_rate_table_http_error_returns_empty() -> None:
    respx.get(_III_AUTO).mock(return_value=httpx.Response(500))
    assert await insurance.get_insurance_rate_table() == []


@respx.mock
async def test_get_insurance_rate_table_unsupported_coverage_returns_empty() -> None:
    assert await insurance.get_insurance_rate_table(coverage_type="life") == []
    assert respx.calls.call_count == 0


# Mirrors the real III home table: merged-cell header + sub-header row whose
# premium cells are prose ("Average premium (2)") — must not be emitted.
_III_HOME_HTML = """<html><body>
<table>
<tr><th></th><th>Homeowners</th><th>Renters</th><th></th><th>Homeowners</th><th>Renters</th></tr>
<tr><th>State</th><th>Average premium (2)</th><th>Rank (3)</th><th>State</th><th>Average premium (2)</th><th>Rank (3)</th></tr>
<tr><td>Alabama</td><td>1,610</td><td>12</td><td>Montana</td><td>1,471</td><td>15</td></tr>
<tr><td>Alaska</td><td>1,067</td><td>35</td><td>Nebraska</td><td>1,684</td><td>9</td></tr>
</table>
</body></html>"""


@respx.mock
async def test_get_insurance_rate_table_skips_prose_header_row() -> None:
    respx.get(_III_AUTO).mock(return_value=httpx.Response(200, text=_III_HOME_HTML))
    rows = await insurance.get_insurance_rate_table()
    assert len(rows) == 4  # 2 data rows x 2 paired halves
    assert all(row["state"] not in {"State", "Rank"} for row in rows)
    by_state = {row["state"]: row["premium"] for row in rows}
    assert by_state["Alabama"] == 1610.0
    assert by_state["Montana"] == 1471.0
    assert by_state["Alaska"] == 1067.0
    assert by_state["Nebraska"] == 1684.0


# ── router ─────────────────────────────────────────────────────────────


@pytest.fixture
def health_app() -> FastAPI:
    app = FastAPI()

    @app.exception_handler(PryError)
    async def pry_error_handler(request: Request, exc: PryError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": str(exc)})

    app.include_router(health_router)
    return app


def _client(app: FastAPI) -> TestClient:
    return TestClient(app)


def test_router_trials_search_success(health_app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake(query: str, limit: int = 20) -> list[dict[str, Any]]:
        return [{"nct_id": "NCT0001", "title": f"match for {query}", "status": "Recruiting"}]

    monkeypatch.setattr(clinical_trials, "search_trials", fake)
    resp = _client(health_app).get(
        "/v1/health/trials/search", params={"query": "alzheimer", "limit": 5}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["query"] == "alzheimer"
    assert body["data"][0]["nct_id"] == "NCT0001"


def test_router_trials_get_success(health_app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake(nct_id: str) -> dict[str, Any]:
        return {"nct_id": nct_id, "title": "trial", "status": "Completed"}

    monkeypatch.setattr(clinical_trials, "get_trial", fake)
    resp = _client(health_app).get("/v1/health/trials/NCT05966207")
    assert resp.status_code == 200
    assert resp.json()["data"]["nct_id"] == "NCT05966207"


def test_router_drug_price_success(health_app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake(drug_name: str) -> dict[str, Any]:
        return {"drug": drug_name, "ndc": "00093072098", "source": "nadac"}

    monkeypatch.setattr(drug_pricing, "get_drug_price", fake)
    resp = _client(health_app).get("/v1/health/drug/atorvastatin")
    assert resp.status_code == 200
    body = resp.json()
    assert body["drug"] == "atorvastatin"
    assert body["data"]["source"] == "nadac"


def test_router_insurance_quotes_success(
    health_app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, Any] = {}

    async def fake(profile: dict[str, Any]) -> dict[str, Any]:
        captured["profile"] = profile
        return {"available": False, "reason": "gated", "coverage_type": "home", "quotes": []}

    monkeypatch.setattr(insurance, "get_insurance_quotes", fake)
    resp = _client(health_app).get(
        "/v1/health/insurance/quotes", params={"coverage_type": "home", "zip": "90210"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["coverage_type"] == "home"
    assert body["data"]["available"] is False
    assert captured["profile"] == {"coverage_type": "home", "zip": "90210"}


def test_router_502_when_module_absent(
    health_app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(health_router_mod, "_healthcare_module", lambda name: None)
    assert (
        _client(health_app).get("/v1/health/trials/search", params={"query": "x"}).status_code
        == 502
    )
    assert _client(health_app).get("/v1/health/trials/NCT0001").status_code == 502
    assert _client(health_app).get("/v1/health/drug/atorvastatin").status_code == 502
    assert _client(health_app).get("/v1/health/insurance/quotes").status_code == 502


def test_router_validation_422(health_app: FastAPI) -> None:
    assert (
        _client(health_app).get("/v1/health/trials/search", params={"query": ""}).status_code == 422
    )
    assert (
        _client(health_app)
        .get("/v1/health/trials/search", params={"query": "x", "limit": 0})
        .status_code
        == 422
    )
    assert (
        _client(health_app)
        .get("/v1/health/trials/search", params={"query": "x", "limit": 101})
        .status_code
        == 422
    )
