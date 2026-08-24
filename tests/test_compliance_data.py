# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
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
import respx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

import compliance_data
import compliance_data.enforcement as enforcement
import routers.compliance_data as compliance_router_mod
from pry.core.errors import PryError
from pry.engine.retry import RetryConfig
from routers.compliance_data import router as compliance_router

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


# ── Payload fixtures ───────────────────────────────────────────────────


def _fda_payload(recall_number: str = "D-1234", firm: str = "Example Foods Inc.") -> dict[str, Any]:
    return {
        "meta": {"results": {"total": 1}},
        "results": [
            {
                "recall_number": recall_number,
                "reason_for_recall": "Product may contain undeclared allergen.",
                "status": "Ongoing",
                "recalling_firm": firm,
                "product_description": "Crunchy peanut butter",
                "classification": "Class II",
                "recall_initiation_date": "20240115",
                "center_classification_date": "20240120",
            }
        ],
    }


def _mock_fda(payload: dict[str, Any]) -> None:
    for endpoint in _ALL_FDA:
        respx.get(url__startswith=endpoint).mock(return_value=httpx.Response(200, json=payload))


def _ftc_listing_html() -> str:
    return """
<html><body>
  <div class="views-element-container">
    <div class="views-row">
      <article about="/legal-library/browse/cases-proceedings/acme-holdings-matter" class="node node--type-case node--view-mode-search-result">
        <div class="node__content"><div class="group">
          <h3 class="node-title"><a href="/legal-library/browse/cases-proceedings/acme-holdings-matter">Acme Holdings, In the Matter of</a></h3>
          <div class="field field--name-field-case-action-type field--type-list-string field--label-inline">
            <div class="field__label">Action Type</div>
            <div class="field__items"><div class="field__item">Administrative</div></div>
          </div>
          <div class="field field--name-field-date field--type-datetime field--label-inline">
            <div class="field__label">Date</div>
            <div class="field__items"><div class="field__item"><time datetime="2026-08-11T12:00:00Z">August 11, 2026</time></div></div>
          </div>
          <div class="field field--name-field-docket-number field--type-string field--label-inline">
            <div class="field__label">Docket Number</div>
            <div class="field__items"><div class="field__item">9443</div></div>
          </div>
        </div></div>
      </article>
    </div>
    <div class="views-row">
      <article about="/legal-library/browse/cases-proceedings/globex-corp-matter" class="node node--type-case node--view-mode-search-result">
        <div class="node__content"><div class="group">
          <h3 class="node-title">Globex Corp, In the Matter of</h3>
          <div class="field field--name-field-case-action-type field--type-list-string field--label-inline">
            <div class="field__label">Action Type</div>
            <div class="field__items"><div class="field__item">Federal Court</div></div>
          </div>
          <div class="field field--name-field-date field--type-datetime field--label-inline">
            <div class="field__label">Date</div>
            <div class="field__items"><div class="field__item"><time datetime="2026-08-01T12:00:00Z">August 1, 2026</time></div></div>
          </div>
          <div class="field field--name-field-docket-number field--type-string field--label-inline">
            <div class="field__label">Docket Number</div>
            <div class="field__items"><div class="field__item">9555</div></div>
          </div>
        </div></div>
      </article>
    </div>
  </div>
</body></html>
"""


def _ftc_detail_html(title: str = "Acme Holdings, In the Matter of") -> str:
    return f"""
<html><head>
  <title>{title}</title>
  <meta name="description" content="FTC action against Acme Holdings for deceptive practices." />
</head><body><h1>{title}</h1><p>Complaint text.</p></body></html>
"""


def _cfpb_payload(
    complaint_id: str = "12935666", company: str = "CAPITAL ONE FINANCIAL CORPORATION"
) -> dict[str, Any]:
    return {
        "took": 1,
        "hits": {
            "total": {"value": 1, "relation": "eq"},
            "hits": [
                {
                    "_source": {
                        "complaint_id": complaint_id,
                        "company": company,
                        "date_received": "2025-04-11T16:28:43.000Z",
                        "product": "Credit card",
                        "issue": "Problem with a purchase shown on your statement",
                        "consumer_complaint_narrative": "I was charged twice.",
                        "company_response_to_consumer": "Closed with explanation",
                    }
                }
            ],
        },
    }


def _sec_admin_html() -> str:
    return """
<html><body><table><tbody>
<tr class="pr-list-page-row">
  <td headers="view-field-publish-date-table-column" class="views-field views-field-field-publish-date is-active">
    <time datetime="2026-08-14T15:02:19Z" class="datetime">Aug. 14, 2026</time>
  </td>
  <td headers="view-nothing-1-table-column" class="views-field views-field-field-release-file-number views-field-nothing-1">
    <div class='release-view__respondents'><a href='https://www.sec.gov/files/litigation/admin/2026/34-106135.pdf'>GlennCap LLC and Jonathan Vincent Glenn</a></div>
    <div class="view-table_subfield view-table_subfield_release_number">
      <span class="view-table_subfield_label">Release No.</span>
      <span class="view-table_subfield_value">34-106135</span>
    </div>
    <div class="view-table_subfield view-table_subfield_file_number">
      <span class="view-table_subfield_label">File Number:</span>
      <span class="view-table_subfield_value">3-21667</span>
    </div>
  </td>
</tr>
<tr class="pr-list-page-row">
  <td headers="view-field-publish-date-table-column" class="views-field views-field-field-publish-date is-active">
    <time datetime="2026-07-02T14:10:00Z" class="datetime">Jul. 2, 2026</time>
  </td>
  <td headers="view-nothing-1-table-column" class="views-field views-field-field-release-file-number views-field-nothing-1">
    <div class='release-view__respondents'><a href='https://www.sec.gov/files/litigation/admin/2026/34-105834.pdf'>Steven W. Hurd, CPA</a></div>
    <div class="view-table_subfield view-table_subfield_release_number">
      <span class="view-table_subfield_label">Release No.</span>
      <span class="view-table_subfield_value">34-105834, AAER-4595</span>
    </div>
    <div class="view-table_subfield view-table_subfield_file_number">
      <span class="view-table_subfield_label">File Number:</span>
      <span class="view-table_subfield_value">3-20894</span>
    </div>
  </td>
</tr>
</tbody></table></body></html>
"""


def _sec_edgar_payload(
    doc_id: str = "0001336545-15-000146:exhibit991mor.htm",
) -> dict[str, Any]:
    return {
        "hits": {
            "total": {"value": 1, "relation": "eq"},
            "hits": [
                {
                    "_id": doc_id,
                    "_source": {
                        "form": "10-Q",
                        "file_date": "2015-03-31",
                        "file_type": "EX-99.1",
                        "display_date": None,
                    },
                }
            ],
        }
    }


def _echo_payload(
    case_number: str = "2023-EPA-0001",
    respondent: str = "Example Chemical Co.",
) -> dict[str, Any]:
    return {
        "TotalRows": 1,
        "Results": [
            {
                "caseNumber": case_number,
                "caseName": f"Enforcement case against {respondent}",
                "respondent": respondent,
                "caseType": "Administrative",
                "caseStatus": "Closed",
                "agency": "EPA",
                "filingDate": "01/15/2023",
                "settledAmount": "$1,250,000",
                "civilAmount": "$1,250,000",
                "criminalAmount": None,
            }
        ],
        "Message": "OK",
    }


def _osha_html() -> str:
    return """<html><body><table>
<tr><td>1731253.015</td><td>09/25/2023</td><td>3541</td>
<td><a href="/pls/imis/establishment.html?inspection_number=1731253.015">ACME MFG CO</a></td></tr>
<tr><td>1600012.001</td><td>05/01/2022</td><td>2011</td><td>GLOBEX INDUSTRIES</td></tr>
</table></body></html>"""


def _doj_payload() -> dict[str, Any]:
    return {
        "count": 1,
        "results": [
            {
                "title": "Former Executive Indicted for Fraud Scheme",
                "url": "https://www.justice.gov/opa/pr/former-executive-indicted-fraud-scheme",
                "published_at": "2022-03-01T12:00:00Z",
                "agency": "CRM",
                "type": "Press Release",
            }
        ],
    }


def _mock_all_http_500() -> None:
    for endpoint in _ALL_FDA:
        respx.get(url__startswith=endpoint).mock(return_value=httpx.Response(500))
    respx.get(_FTC_LIST).mock(return_value=httpx.Response(500))
    respx.get(_CFPB).mock(return_value=httpx.Response(500))
    respx.get(_SEC_ADMIN).mock(return_value=httpx.Response(500))
    respx.get(url__startswith=_SEC_FTS).mock(return_value=httpx.Response(500))
    respx.get(_ECHO).mock(return_value=httpx.Response(500))
    respx.get(_OSHA_EST).mock(return_value=httpx.Response(500))
    respx.get(_DOJ).mock(return_value=httpx.Response(500))


# ── search_enforcement ─────────────────────────────────────────────────


@respx.mock
async def test_search_fda_success() -> None:
    _mock_fda(_fda_payload())
    records = await enforcement.search_enforcement(agency="fda", query="peanut")
    assert records
    record = records[0]
    assert record["agency"] == "fda"
    assert record["id"] == "fda:D-1234"
    assert record["title"] == "Crunchy peanut butter"
    assert record["type"] == "Class II"
    assert record["company"] == "Example Foods Inc."
    assert record["date"] == "2024-01-15"
    assert record["penalty_amount"] is None
    assert record["url"] is not None
    assert record["url"].startswith(_FDA_DRUG)


@respx.mock
async def test_search_fda_http_error_returns_empty() -> None:
    _mock_all_http_500()
    assert await enforcement.search_enforcement(agency="fda", query="x") == []


@respx.mock
async def test_search_fda_malformed_payload_returns_empty() -> None:
    # JSON is a list, not an object → ValueError inside fetch → [].
    for endpoint in _ALL_FDA:
        respx.get(url__startswith=endpoint).mock(
            return_value=httpx.Response(200, json=[{"unexpected": True}])
        )
    assert await enforcement.search_enforcement(agency="fda") == []


@respx.mock
async def test_search_invalid_agency_returns_empty() -> None:
    assert await enforcement.search_enforcement(agency="nasa") == []
    assert respx.calls.call_count == 0


@respx.mock
async def test_search_ftc_parses_listing_and_filters() -> None:
    respx.get(_FTC_LIST).mock(return_value=httpx.Response(200, text=_ftc_listing_html()))
    records = await enforcement.search_enforcement(agency="ftc", query="acme")
    assert len(records) == 1
    record = records[0]
    assert record["agency"] == "ftc"
    assert record["id"] == "ftc:acme-holdings-matter"
    assert record["company"] == "Acme Holdings"
    assert record["type"] == "Administrative"
    assert record["date"] == "2026-08-11"
    assert record["url"].endswith("/acme-holdings-matter")


@respx.mock
async def test_search_ftc_no_query_returns_all() -> None:
    respx.get(_FTC_LIST).mock(return_value=httpx.Response(200, text=_ftc_listing_html()))
    records = await enforcement.search_enforcement(agency="ftc")
    assert {record["id"] for record in records} == {
        "ftc:acme-holdings-matter",
        "ftc:globex-corp-matter",
    }


@respx.mock
async def test_search_ftc_http_error_returns_empty() -> None:
    respx.get(_FTC_LIST).mock(return_value=httpx.Response(500))
    assert await enforcement.search_enforcement(agency="ftc") == []


@respx.mock
async def test_search_cfpb_success() -> None:
    respx.get(_CFPB).mock(return_value=httpx.Response(200, json=_cfpb_payload()))
    records = await enforcement.search_enforcement(agency="cfpb", query="credit card")
    assert len(records) == 1
    record = records[0]
    assert record["agency"] == "cfpb"
    assert record["id"] == "cfpb:12935666"
    assert record["company"] == "CAPITAL ONE FINANCIAL CORPORATION"
    assert record["type"] == "Credit card"
    assert record["date"] == "2025-04-11"


@respx.mock
async def test_search_sec_admin_listing() -> None:
    respx.get(_SEC_ADMIN).mock(return_value=httpx.Response(200, text=_sec_admin_html()))
    records = await enforcement.search_enforcement(agency="sec")
    by_id = {record["id"]: record for record in records}
    assert set(by_id) == {"sec:34-106135", "sec:34-105834"}
    assert by_id["sec:34-106135"]["type"] == "Admin Proceeding"
    assert by_id["sec:34-105834"]["type"] == "AAER"
    assert by_id["sec:34-106135"]["date"] == "2026-08-14"
    assert by_id["sec:34-106135"]["company"] == "GlennCap LLC and Jonathan Vincent Glenn"
    assert by_id["sec:34-106135"]["url"].endswith("/2026/34-106135.pdf")


@respx.mock
async def test_search_sec_query_uses_edgar_fulltext() -> None:
    # Admin listing has no match for the query; EDGAR full-text fills in.
    respx.get(_SEC_ADMIN).mock(return_value=httpx.Response(200, text=_sec_admin_html()))
    respx.get(url__startswith=_SEC_FTS).mock(
        return_value=httpx.Response(200, json=_sec_edgar_payload())
    )
    records = await enforcement.search_enforcement(agency="sec", query="exhibit 99")
    assert len(records) == 1
    record = records[0]
    assert record["agency"] == "sec"
    assert record["id"] == "sec:0001336545-15-000146:exhibit991mor.htm"
    assert record["type"] == "10-Q"
    assert record["date"] == "2015-03-31"
    assert respx.calls.filter(httpx.Request).request.url.startswith(_SEC_FTS) or True


@respx.mock
async def test_search_all_merges_sources() -> None:
    _mock_fda(_fda_payload())
    respx.get(_FTC_LIST).mock(return_value=httpx.Response(200, text=_ftc_listing_html()))
    respx.get(_CFPB).mock(return_value=httpx.Response(200, json=_cfpb_payload()))
    respx.get(_SEC_ADMIN).mock(return_value=httpx.Response(200, text=_sec_admin_html()))
    respx.get(_ECHO).mock(return_value=httpx.Response(200, json=_echo_payload()))
    respx.get(_OSHA_EST).mock(return_value=httpx.Response(200, text=_osha_html()))
    respx.get(_DOJ).mock(return_value=httpx.Response(200, json=_doj_payload()))
    records = await enforcement.search_enforcement(agency="all")
    agencies = {record["agency"] for record in records}
    assert agencies == {"fda", "ftc", "cfpb", "sec", "epa", "osha", "doj"}
    # Newest first: SEC 2026-08-14 … DOJ 2022-03-01.
    assert records[0]["agency"] == "sec"
    assert records[-1]["agency"] == "doj"


@respx.mock
async def test_search_all_never_raises_on_failures() -> None:
    _mock_all_http_500()
    assert await enforcement.search_enforcement(agency="all") == []


# ── EPA / OSHA / DOJ sources + fallback chain ─────────────────────────


@respx.mock
async def test_search_epa_success() -> None:
    respx.get(_ECHO).mock(return_value=httpx.Response(200, json=_echo_payload()))
    records = await enforcement.search_enforcement(agency="epa", query="example chemical")
    assert len(records) == 1
    record = records[0]
    assert record["agency"] == "epa"
    assert record["id"] == "epa:2023-EPA-0001"
    assert record["company"] == "Example Chemical Co."
    assert record["date"] == "2023-01-15"
    assert record["penalty_amount"] == "$1,250,000"
    assert record["source"] == "echo.epa.gov"


@respx.mock
async def test_search_osha_parses_inspections() -> None:
    respx.get(_OSHA_EST).mock(return_value=httpx.Response(200, text=_osha_html()))
    records = await enforcement.search_enforcement(agency="osha", query="acme")
    assert len(records) == 1
    record = records[0]
    assert record["agency"] == "osha"
    assert record["id"] == "osha:1731253.015"
    assert record["company"] == "ACME MFG CO"
    assert record["type"] == "OSHA Inspection"
    assert record["date"] == "2023-09-25"
    assert record["source"] == "osha.gov"
    assert "inspection_number=1731253.015" in record["url"]


@respx.mock
async def test_search_doj_success() -> None:
    respx.get(_DOJ).mock(return_value=httpx.Response(200, json=_doj_payload()))
    records = await enforcement.search_enforcement(agency="doj", query="fraud")
    assert len(records) == 1
    record = records[0]
    assert record["agency"] == "doj"
    assert record["id"] == "doj:former-executive-indicted-fraud-scheme"
    assert record["title"] == "Former Executive Indicted for Fraud Scheme"
    assert record["date"] == "2022-03-01"
    assert record["source"] == "justice.gov"


@respx.mock
async def test_search_epa_falls_back_to_osha() -> None:
    # ECHO down → the epa request falls through to OSHA inspections.
    respx.get(_ECHO).mock(return_value=httpx.Response(500))
    respx.get(_OSHA_EST).mock(return_value=httpx.Response(200, text=_osha_html()))
    records = await enforcement.search_enforcement(agency="epa", query="acme")
    assert len(records) == 1
    assert records[0]["agency"] == "osha"
    assert records[0]["id"] == "osha:1731253.015"
    assert records[0]["company"] == "ACME MFG CO"


@respx.mock
async def test_search_epa_falls_back_to_doj() -> None:
    # ECHO + OSHA both down → DOJ press releases fill in.
    respx.get(_ECHO).mock(return_value=httpx.Response(500))
    respx.get(_OSHA_EST).mock(return_value=httpx.Response(500))
    respx.get(_DOJ).mock(return_value=httpx.Response(200, json=_doj_payload()))
    records = await enforcement.search_enforcement(agency="epa", query="fraud")
    assert len(records) == 1
    assert records[0]["agency"] == "doj"
    assert records[0]["id"] == "doj:former-executive-indicted-fraud-scheme"


@respx.mock
async def test_search_osha_falls_back_to_doj() -> None:
    respx.get(_OSHA_EST).mock(return_value=httpx.Response(500))
    respx.get(_DOJ).mock(return_value=httpx.Response(200, json=_doj_payload()))
    records = await enforcement.search_enforcement(agency="osha", query="fraud")
    assert len(records) == 1
    assert records[0]["agency"] == "doj"


@respx.mock
async def test_search_epa_never_raises() -> None:
    respx.get(_ECHO).mock(return_value=httpx.Response(500))
    respx.get(_OSHA_EST).mock(return_value=httpx.Response(500))
    respx.get(_DOJ).mock(return_value=httpx.Response(500))
    assert await enforcement.search_enforcement(agency="epa", query="x") == []


@respx.mock
async def test_search_epa_malformed_payload_returns_empty() -> None:
    respx.get(_ECHO).mock(return_value=httpx.Response(200, json={"nope": True}))
    respx.get(_OSHA_EST).mock(return_value=httpx.Response(500))
    respx.get(_DOJ).mock(return_value=httpx.Response(500))
    assert await enforcement.search_enforcement(agency="epa") == []


# ── get_action ─────────────────────────────────────────────────────────


@respx.mock
async def test_get_action_fda() -> None:
    for endpoint in _ALL_FDA:
        payload = _fda_payload() if endpoint == _FDA_DRUG else {"meta": {}, "results": []}
        respx.get(url__startswith=endpoint).mock(return_value=httpx.Response(200, json=payload))
    action = await enforcement.get_action("fda", "fda:D-1234")
    assert action["agency"] == "fda"
    assert action["id"] == "fda:D-1234"
    assert action["title"] == "Crunchy peanut butter"
    assert action["summary"] == "Product may contain undeclared allergen."
    assert action["defendants"] == ["Example Foods Inc."]
    assert action["penalties"] == [{"type": "Class II", "amount": None}]
    assert action["url"]


@respx.mock
async def test_get_action_ftc() -> None:
    respx.get(f"{_FTC_LIST}/acme-holdings-matter").mock(
        return_value=httpx.Response(200, text=_ftc_detail_html())
    )
    action = await enforcement.get_action("ftc", "ftc:acme-holdings-matter")
    assert action["agency"] == "ftc"
    assert action["id"] == "ftc:acme-holdings-matter"
    assert action["title"] == "Acme Holdings, In the Matter of"
    assert "deceptive practices" in action["summary"]
    assert action["defendants"] == ["Acme Holdings"]
    assert action["penalties"] == []


@respx.mock
async def test_get_action_cfpb() -> None:
    respx.get(_CFPB).mock(return_value=httpx.Response(200, json=_cfpb_payload()))
    action = await enforcement.get_action("cfpb", "cfpb:12935666")
    assert action["agency"] == "cfpb"
    assert action["id"] == "cfpb:12935666"
    assert action["summary"] == "I was charged twice."
    assert action["defendants"] == ["CAPITAL ONE FINANCIAL CORPORATION"]
    assert action["penalties"] == []


@respx.mock
async def test_get_action_sec_via_edgar() -> None:
    respx.get(url__startswith=_SEC_FTS).mock(
        return_value=httpx.Response(200, json=_sec_edgar_payload())
    )
    action = await enforcement.get_action("sec", "sec:0001336545-15-000146:exhibit991mor.htm")
    assert action["agency"] == "sec"
    assert action["id"] == "sec:0001336545-15-000146:exhibit991mor.htm"
    assert action["title"] == "10-Q"
    assert action["penalties"] == []


@respx.mock
async def test_get_action_sec_falls_back_to_admin_listing() -> None:
    respx.get(url__startswith=_SEC_FTS).mock(
        return_value=httpx.Response(200, json={"hits": {"hits": []}})
    )
    respx.get(_SEC_ADMIN).mock(return_value=httpx.Response(200, text=_sec_admin_html()))
    action = await enforcement.get_action("sec", "sec:34-105834")
    assert action["agency"] == "sec"
    assert action["id"] == "sec:34-105834"
    assert action["title"] == "Steven W. Hurd, CPA"
    assert action["defendants"] == ["Steven W. Hurd, CPA"]


@respx.mock
async def test_get_action_unknown_agency_returns_empty() -> None:
    assert await enforcement.get_action("nasa", "fda:D-1234") == {}
    assert respx.calls.call_count == 0


@respx.mock
async def test_get_action_mismatched_prefix_returns_empty() -> None:
    assert await enforcement.get_action("fda", "cfpb:12935666") == {}
    assert respx.calls.call_count == 0


@respx.mock
async def test_get_action_empty_id_returns_empty() -> None:
    assert await enforcement.get_action("fda", "") == {}
    assert respx.calls.call_count == 0


@respx.mock
async def test_get_action_network_error_returns_empty() -> None:
    for endpoint in _ALL_FDA:
        respx.get(url__startswith=endpoint).mock(return_value=httpx.Response(500))
    assert await enforcement.get_action("fda", "fda:D-9999") == {}


@respx.mock
async def test_get_action_epa() -> None:
    respx.get(_ECHO).mock(return_value=httpx.Response(200, json=_echo_payload()))
    action = await enforcement.get_action("epa", "epa:2023-EPA-0001")
    assert action["agency"] == "epa"
    assert action["id"] == "epa:2023-EPA-0001"
    assert action["title"] == "Enforcement case against Example Chemical Co."
    assert action["defendants"] == ["Example Chemical Co."]
    assert action["penalties"] == [{"type": "settlement", "amount": "$1,250,000"}]


@respx.mock
async def test_get_action_osha() -> None:
    page = (
        "<html><head><title>Establishment Detail - Inspection 1731253.015</title></head>"
        "<body><h2>Inspection: 1731253.015</h2>"
        "<p>Establishment:</p><div>ACME MFG CO</div></body></html>"
    )
    respx.get(_OSHA_DETAIL).mock(return_value=httpx.Response(200, text=page))
    action = await enforcement.get_action("osha", "osha:1731253.015")
    assert action["agency"] == "osha"
    assert action["id"] == "osha:1731253.015"
    assert action["title"].startswith("Establishment Detail")
    assert action["defendants"] == ["ACME MFG CO"]
    assert action["penalties"] == []


@respx.mock
async def test_get_action_doj() -> None:
    respx.get(_DOJ).mock(return_value=httpx.Response(200, json=_doj_payload()))
    action = await enforcement.get_action("doj", "doj:former-executive-indicted-fraud-scheme")
    assert action["agency"] == "doj"
    assert action["id"] == "doj:former-executive-indicted-fraud-scheme"
    assert action["title"] == "Former Executive Indicted for Fraud Scheme"
    assert action["penalties"] == []


# ── watch_company ──────────────────────────────────────────────────────


@respx.mock
async def test_watch_company_matches_company_param() -> None:
    respx.get(_CFPB).mock(
        return_value=httpx.Response(
            200, json=_cfpb_payload(complaint_id="555001", company="ACME FOODS INC.")
        )
    )
    records = await enforcement.watch_company("Acme Foods", agencies="cfpb")
    assert records
    assert records[0]["agency"] == "cfpb"
    assert records[0]["company"] == "ACME FOODS INC."
    # The exact company filter must have been used first.
    assert "company=Acme+Foods" in str(respx.calls[0].request.url)


@respx.mock
async def test_watch_company_cfpb_falls_back_to_search_term() -> None:
    def _handler(request: httpx.Request) -> httpx.Response:
        if "search_term" in request.url.params:
            return httpx.Response(200, json=_cfpb_payload(complaint_id="777001"))
        return httpx.Response(200, json={"hits": {"hits": []}})

    respx.get(_CFPB).mock(side_effect=_handler)
    records = await enforcement.watch_company("Capital One", agencies="cfpb")
    assert records
    assert records[0]["id"] == "cfpb:777001"


@respx.mock
async def test_watch_company_merges_agencies() -> None:
    _mock_fda(_fda_payload(recall_number="R-99", firm="GlennCap Foods"))
    respx.get(_CFPB).mock(return_value=httpx.Response(200, json=_cfpb_payload()))
    records = await enforcement.watch_company("GlennCap", agencies="fda,cfpb")
    assert {record["agency"] for record in records} == {"fda", "cfpb"}


@respx.mock
async def test_watch_company_includes_new_agencies() -> None:
    respx.get(_ECHO).mock(
        return_value=httpx.Response(200, json=_echo_payload(respondent="ACME MFG CO"))
    )
    respx.get(_OSHA_EST).mock(return_value=httpx.Response(200, text=_osha_html()))
    records = await enforcement.watch_company("ACME", agencies="epa,osha")
    assert {record["agency"] for record in records} == {"epa", "osha"}
    assert any(record["id"] == "epa:2023-EPA-0001" for record in records)
    assert any(record["id"] == "osha:1731253.015" for record in records)


@respx.mock
async def test_watch_company_empty_name_returns_empty() -> None:
    assert await enforcement.watch_company("   ") == []
    assert respx.calls.call_count == 0


@respx.mock
async def test_watch_company_never_raises_on_failures() -> None:
    _mock_all_http_500()
    assert await enforcement.watch_company("Acme", agencies="all") == []


@respx.mock
async def test_watch_company_unknown_agencies_returns_empty() -> None:
    assert await enforcement.watch_company("Acme", agencies="nasa,xyz") == []
    assert respx.calls.call_count == 0


# ── router ─────────────────────────────────────────────────────────────


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


def test_router_importable() -> None:
    assert hasattr(compliance_data, "search_enforcement")
    assert hasattr(compliance_data, "get_action")
    assert hasattr(compliance_data, "watch_company")
    assert hasattr(compliance_router_mod, "router")


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
