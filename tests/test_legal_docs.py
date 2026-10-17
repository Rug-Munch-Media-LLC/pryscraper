# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for the legal_docs package (CourtListener / SEC EDGAR / OFAC SDN).

Covers docket search + lookup, SEC filing search / filing lookup / Form 4
insider trades, OFAC SDN name screening (JSON source, XML fallback, disk
cache), the never-raise contract (HTTP errors and malformed payloads all
degrade to empty output), and the /v1/legal/* router (200 + 502-degradation
+ 422 validation).

All HTTP is mocked with respx — no live network.
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any

import httpx
import pytest
import respx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

import datasets.legal_docs as legal_docs
import datasets.legal_docs.dockets as dockets
import datasets.legal_docs.sanctions as sanctions
import datasets.legal_docs.sec_filings as sec_filings
import pry.api.routers.data.legal_docs as legal_router_mod
from pry.api.routers.data.legal_docs import router as legal_router
from pry.core.errors import PryError
from pry.engine.retry import RetryConfig

if TYPE_CHECKING:
    from pathlib import Path

_CL_BASE = "https://www.courtlistener.com/api/rest/v4"
_PACER_FETCH = f"{_CL_BASE}/pacer-fetch/"
_JUSTIA = "https://dockets.justia.com"
_NY_ECOURTS = "https://iapps.courts.state.ny.us/webcivil/FCASSearch"
_FTS = "https://efts.sec.gov/LATEST/search-index"
_TICKERS = "https://www.sec.gov/files/company_tickers.json"
_SUBMISSIONS = "https://data.sec.gov/submissions/CIK0000320193.json"
_INDEX = "https://www.sec.gov/Archives/edgar/data/320193/000032019324000005/"
_OFAC_JSON = "https://www.treasury.gov/ofac/downloads/sdn.json"
_OFAC_XML = "https://www.treasury.gov/ofac/downloads/sdn.xml"
_OFAC_CSV = "https://www.treasury.gov/ofac/downloads/sdn.csv"

_ZERO_RETRY = RetryConfig(
    max_retries=1, base_delay=0.0, max_delay=0.0, retryable_exceptions=(httpx.HTTPError,)
)


@pytest.fixture(autouse=True)
def _hermetic_legal(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Kill backoff delays and reset caches without patching module internals."""
    previous_dockets = dockets.configure_retries(_ZERO_RETRY)
    previous_sec = sec_filings.configure_retries(_ZERO_RETRY)
    previous_sanctions = sanctions.configure_retries(_ZERO_RETRY)
    for env_name in ("PRY_COURTLISTENER_API_KEY", "PRY_LEGAL_OFAC_CACHE_PATH"):
        monkeypatch.delenv(env_name, raising=False)
    sec_filings.reset_ticker_cache()
    sanctions.reset_cache()
    yield
    dockets.configure_retries(previous_dockets)
    sec_filings.configure_retries(previous_sec)
    sanctions.configure_retries(previous_sanctions)
    sec_filings.reset_ticker_cache()
    sanctions.reset_cache()


# ── Payload fixtures ───────────────────────────────────────────────────


def _cl_search_payload() -> dict[str, Any]:
    return {
        "count": 1,
        "next": None,
        "previous": None,
        "results": [
            {
                "id": 42,
                "case_name": "SEC v. Example Corp.",
                "docket_number": "1:22-cv-00001",
                "court": "dcd",
                "date_filed": "2022-01-15",
                "date_terminated": None,
                "nature_of_suit": "Contract",
                "cause": "15:78j",
            }
        ],
    }


def _cl_detail_payload() -> dict[str, Any]:
    return {
        **_cl_search_payload()["results"][0],
        "description": "Securities fraud",
        "jury_demand": "None",
        "jurisdiction_type": "Federal Question",
        "date_argued": None,
        "date_reargued": None,
        "date_last_filing": "2022-03-01",
        "appeal_from": "dcd",
        "panel": None,
    }


def _fts_payload() -> dict[str, Any]:
    return {
        "hits": {
            "total": {"value": 1},
            "hits": [
                {
                    "_id": "0000320193-24-000005:aapl-20240201.htm",
                    "_source": {
                        "adsh": "0000320193-24-000005",
                        "form": "8-K",
                        "file_date": "2024-02-01",
                        "display_names": ["Apple Inc.  (AAPL)  (CIK 0000320193)"],
                        "ciks": ["0000320193"],
                        "items": ["8.01", "9.01"],
                    },
                }
            ],
        }
    }


def _tickers_payload() -> dict[str, Any]:
    return {"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}}


def _submissions_payload() -> dict[str, Any]:
    return {
        "cik": "0000320193",
        "name": "Apple Inc.",
        "tickers": ["AAPL"],
        "filings": {
            "recent": {
                "form": ["4", "10-Q", "4", "8-K"],
                "filingDate": ["2026-08-13", "2026-07-31", "2026-07-01", "2026-06-30"],
                "reportDate": ["2026-08-11", "2026-06-27", "2026-06-29", "2026-06-29"],
                "accessionNumber": [
                    "0001140361-26-032884",
                    "0000320193-26-000077",
                    "0001140361-26-030000",
                    "0000320193-26-000078",
                ],
                "primaryDocument": [
                    "xslF345X06/form4.xml",
                    "aapl-20260731.htm",
                    "xslF345X06/form4b.xml",
                    "aapl-20260630.htm",
                ],
            }
        },
    }


def _index_payload() -> dict[str, Any]:
    return {
        "directory": {
            "name": "000032019324000005",
            "item": [
                {"name": "aapl-20240201.htm", "type": "8-K"},
                {"name": "FilingSummary.xml", "type": "XML"},
            ],
        }
    }


def _sdn_json_payload() -> dict[str, Any]:
    return {
        "data": {
            "sdnList": {
                "publshInformation": {},
                "sdnEntry": [
                    {
                        "uid": "36",
                        "lastName": "AEROCARIBBEAN AIRLINES",
                        "sdnType": "Entity",
                        "programs": ["CUBA"],
                    },
                    {
                        "uid": "12345",
                        "firstName": "JOHN",
                        "lastName": "SMITH",
                        "sdnType": "Individual",
                        "programs": ["SDGT"],
                    },
                ],
            }
        }
    }


def _sdn_xml() -> str:
    return """<?xml version="1.0" standalone="yes"?>
<sdnList xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns="https://sanctionslistservice.ofac.treas.gov/api/PublicationPreview/exports/XML">
  <publshInformation><Publish_Date>08/07/2026</Publish_Date><Record_Count>2</Record_Count></publshInformation>
  <sdnEntry>
    <uid>36</uid>
    <lastName>AEROCARIBBEAN AIRLINES</lastName>
    <sdnType>Entity</sdnType>
    <programList><program>CUBA</program></programList>
    <akaList><aka><uid>12</uid><type>a.k.a.</type><category>strong</category><lastName>AERO-CARIBBEAN</lastName></aka></akaList>
  </sdnEntry>
  <sdnEntry>
    <uid>12345</uid>
    <firstName>JOHN</firstName>
    <lastName>SMITH</lastName>
    <sdnType>Individual</sdnType>
    <programList><program>SDGT</program></programList>
  </sdnEntry>
</sdnList>"""


# ── CourtListener dockets ──────────────────────────────────────────────


@respx.mock
async def test_dockets_search_success() -> None:
    respx.get(url__startswith=f"{_CL_BASE}/dockets/?").mock(
        return_value=httpx.Response(200, json=_cl_search_payload())
    )
    out = await dockets.search_dockets("example fraud", limit=5)
    assert len(out) == 1
    assert out[0]["id"] == 42
    assert out[0]["case_name"] == "SEC v. Example Corp."
    assert out[0]["court"] == "dcd"
    assert out[0]["date_filed"] == "2022-01-15"
    assert out[0]["url"] == "https://www.courtlistener.com/docket/42/"
    assert out[0]["source"] == "courtlistener"


@respx.mock
async def test_dockets_search_sends_token_when_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRY_COURTLISTENER_API_KEY", "test-token")
    route = respx.get(url__startswith=f"{_CL_BASE}/dockets/?").mock(
        return_value=httpx.Response(200, json=_cl_search_payload())
    )
    await dockets.search_dockets("bitcoin")
    request = route.calls.last.request
    assert request.headers.get("authorization") == "Token test-token"


@respx.mock
async def test_dockets_search_never_raises_on_401() -> None:
    respx.get(url__startswith=f"{_CL_BASE}/dockets/?").mock(
        return_value=httpx.Response(
            401, json={"detail": "Authentication credentials were not provided."}
        )
    )
    respx.get(url__startswith=f"{_CL_BASE}/search/?").mock(return_value=httpx.Response(401))
    respx.get(url__startswith=f"{_JUSTIA}/search").mock(return_value=httpx.Response(403))
    respx.post(_NY_ECOURTS).mock(return_value=httpx.Response(403))
    assert await dockets.search_dockets("bitcoin") == []
    assert respx.calls.call_count == 8


async def test_dockets_search_blank_query() -> None:
    assert await dockets.search_dockets("   ") == []
    assert respx.calls.call_count == 0


@respx.mock
async def test_dockets_get_success() -> None:
    respx.get(url__regex=rf"{re.escape(_CL_BASE)}/dockets/42/$").mock(
        return_value=httpx.Response(200, json=_cl_detail_payload())
    )
    out = await dockets.get_docket(42)
    assert out["id"] == 42
    assert out["description"] == "Securities fraud"
    assert out["jurisdiction_type"] == "Federal Question"
    assert out["date_last_filing"] == "2022-03-01"


@respx.mock
async def test_dockets_get_never_raises_on_404() -> None:
    respx.get(url__regex=rf"{re.escape(_CL_BASE)}/dockets/999/$").mock(
        return_value=httpx.Response(404, json={})
    )
    respx.post(_PACER_FETCH).mock(return_value=httpx.Response(404, json={}))
    assert await dockets.get_docket(999) == {}
    assert respx.calls.call_count == 4


async def test_dockets_get_invalid_id() -> None:
    assert await dockets.get_docket("") == {}
    assert respx.calls.call_count == 0


@respx.mock
async def test_dockets_get_invalid_slug_degrades() -> None:
    # A non-numeric id is treated as a Justia slug; when the scrape fails
    # (404 / network) and the NY eCourts lookup also misses, the lookup
    # degrades to {}.
    respx.get(url__startswith=f"{_JUSTIA}/docket/").mock(return_value=httpx.Response(404))
    respx.post(_NY_ECOURTS).mock(return_value=httpx.Response(404))
    assert await dockets.get_docket("not-an-int") == {}
    assert respx.calls.call_count == 4


# ── RECAP search source ────────────────────────────────────────────────


def _recap_payload() -> dict[str, Any]:
    return {
        "count": 1,
        "next": None,
        "previous": None,
        "results": [
            {
                "id": 77,
                "caseName": "In re Example Corp.",
                "docketNumber": "3:23-bk-00099",
                "court": "ca9",
                "dateFiled": "2023-04-01",
                "natureOfSuit": "Bankruptcy",
                "source": "RECAP",
                "absoluteURL": "https://www.courtlistener.com/docket/77/example/",
            }
        ],
    }


@respx.mock
async def test_dockets_search_recap_fallback() -> None:
    # CourtListener dockets search returns nothing -> RECAP search fills in.
    respx.get(url__startswith=f"{_CL_BASE}/dockets/?").mock(
        return_value=httpx.Response(200, json={"results": []})
    )
    respx.get(url__startswith=f"{_CL_BASE}/search/?").mock(
        return_value=httpx.Response(200, json=_recap_payload())
    )
    out = await dockets.search_dockets("bankruptcy", limit=5)
    assert len(out) == 1
    assert out[0]["id"] == 77
    assert out[0]["case_name"] == "In re Example Corp."
    assert out[0]["docket_number"] == "3:23-bk-00099"
    assert out[0]["court"] == "ca9"
    assert out[0]["date_filed"] == "2023-04-01"
    assert out[0]["url"] == "https://www.courtlistener.com/docket/77/example/"
    assert out[0]["source"] == "recap"


@respx.mock
async def test_dockets_search_recap_never_raises_on_error() -> None:
    respx.get(url__startswith=f"{_CL_BASE}/dockets/?").mock(
        return_value=httpx.Response(200, json={"results": []})
    )
    respx.get(url__startswith=f"{_CL_BASE}/search/?").mock(return_value=httpx.Response(500))
    respx.get(url__startswith=f"{_JUSTIA}/search").mock(return_value=httpx.Response(500))
    respx.post(_NY_ECOURTS).mock(return_value=httpx.Response(500))
    assert await dockets.search_dockets("bankruptcy") == []
    assert respx.calls.call_count == 7


# ── Justia scrape source ───────────────────────────────────────────────


def _justia_search_html() -> str:
    return """<html><body>
<div class="case-block">
  <h2><a href="/docket/new-york-southern-district-court/example-1">SEC v. Example Corp.</a></h2>
  <div class="meta">1:22-cv-00001 &middot; Southern District of New York &middot; filed 2022-01-15</div>
</div>
<div class="case-block">
  <h2><a href="/docket/texas-southern-district-court/example-2">Doe v. Fictitious LLC</a></h2>
  <div class="meta">4:21-cv-00420 &middot; Southern District of Texas &middot; filed 2021-06-30</div>
</div>
</body></html>"""


@respx.mock
async def test_dockets_search_justia_fallback() -> None:
    # CourtListener + RECAP both empty -> Justia scrape.
    respx.get(url__startswith=f"{_CL_BASE}/dockets/?").mock(
        return_value=httpx.Response(200, json={"results": []})
    )
    respx.get(url__startswith=f"{_CL_BASE}/search/?").mock(
        return_value=httpx.Response(200, json={"results": []})
    )
    respx.get(url__startswith=f"{_JUSTIA}/search").mock(
        return_value=httpx.Response(200, text=_justia_search_html())
    )
    out = await dockets.search_dockets("example", limit=5)
    assert len(out) == 2
    first = out[0]
    assert first["source"] == "justia"
    assert first["case_name"] == "SEC v. Example Corp."
    assert first["docket_number"] == "1:22-cv-00001"
    assert "Southern District of New York" in first["court"]
    assert first["date_filed"] == "2022-01-15"
    assert (
        first["url"]
        == "https://dockets.justia.com/docket/new-york-southern-district-court/example-1"
    )
    assert first["id"] == "example-1"


@respx.mock
async def test_dockets_search_justia_scrape_never_raises() -> None:
    respx.get(url__startswith=f"{_CL_BASE}/dockets/?").mock(
        return_value=httpx.Response(200, json={"results": []})
    )
    respx.get(url__startswith=f"{_CL_BASE}/search/?").mock(
        return_value=httpx.Response(200, json={"results": []})
    )
    respx.get(url__startswith=f"{_JUSTIA}/search").mock(return_value=httpx.Response(403))
    respx.post(_NY_ECOURTS).mock(return_value=httpx.Response(403))
    assert await dockets.search_dockets("example") == []
    assert respx.calls.call_count == 6


@respx.mock
async def test_dockets_get_justia_slug_fallback() -> None:
    page = """<html><head><title>SEC v. Example Corp. - Docket</title></head><body>
<h1>SEC v. Example Corp.</h1>
<div>1:22-cv-00001 &middot; Southern District of New York</div>
<div class="date">filed 2022-01-15</div>
</body></html>"""
    respx.get(url__startswith=f"{_JUSTIA}/docket/").mock(
        return_value=httpx.Response(200, text=page)
    )
    out = await dockets.get_docket("new-york-southern-district-court/example-1")
    assert out["source"] == "justia"
    assert out["case_name"] == "SEC v. Example Corp."
    assert out["docket_number"] == "1:22-cv-00001"
    assert "Southern District of New York" in out["court"]
    assert out["date_filed"] == "2022-01-15"
    assert (
        out["url"] == "https://dockets.justia.com/docket/new-york-southern-district-court/example-1"
    )


# ── PACER docket lookup (CourtListener pacer-fetch) ────────────────────


def _pacer_payload() -> dict[str, Any]:
    return {
        "id": 999,
        "case_name": "In re PACER Corp.",
        "docket_number": "1:24-bk-00099",
        "court": "nyb",
        "date_filed": "2024-05-01",
        "date_terminated": None,
        "nature_of_suit": "Bankruptcy",
        "cause": None,
        "description": "PACER-fetched bankruptcy docket",
        "jury_demand": "None",
        "jurisdiction_type": "Federal Question",
        "date_argued": None,
        "date_reargued": None,
        "date_last_filing": None,
        "appeal_from": None,
        "panel": None,
    }


@respx.mock
async def test_dockets_get_pacer_fallback() -> None:
    # CourtListener detail misses (not in RECAP archive) → pacer-fetch POST.
    respx.get(url__regex=rf"{re.escape(_CL_BASE)}/dockets/999/$").mock(
        return_value=httpx.Response(404, json={})
    )
    respx.post(_PACER_FETCH).mock(return_value=httpx.Response(201, json=_pacer_payload()))
    out = await dockets.get_docket(999)
    assert out["id"] == 999
    assert out["case_name"] == "In re PACER Corp."
    assert out["docket_number"] == "1:24-bk-00099"
    assert out["description"] == "PACER-fetched bankruptcy docket"
    assert out["source"] == "pacer"


@respx.mock
async def test_dockets_get_pacer_never_raises() -> None:
    respx.get(url__regex=rf"{re.escape(_CL_BASE)}/dockets/42/$").mock(
        return_value=httpx.Response(404, json={})
    )
    respx.post(_PACER_FETCH).mock(return_value=httpx.Response(401, json={}))
    assert await dockets.get_docket(42) == {}
    assert respx.calls.call_count == 4


# ── NY eCourts (state civil) source ────────────────────────────────────


def _ny_ecourts_html() -> str:
    return """<html><body><table>
<tr class="data">
  <td>651256/2023</td><td>Contract</td><td>11/08/2023</td>
  <td>&nbsp;</td><td>ACME CORP</td><td>EXAMPLE LLC</td>
</tr>
<tr class="data">
  <td>650001/2022</td><td>Tort</td><td>02/14/2022</td>
  <td>HON JUDGE</td><td>JANE DOE</td><td>GLOBEX INC</td>
</tr>
</table></body></html>"""


@respx.mock
async def test_dockets_search_state_fallback() -> None:
    # CourtListener + RECAP + Justia all empty → NY eCourts state search.
    respx.get(url__startswith=f"{_CL_BASE}/dockets/?").mock(
        return_value=httpx.Response(200, json={"results": []})
    )
    respx.get(url__startswith=f"{_CL_BASE}/search/?").mock(
        return_value=httpx.Response(200, json={"results": []})
    )
    respx.get(url__startswith=f"{_JUSTIA}/search").mock(
        return_value=httpx.Response(200, json={"results": []}),
        # Justia scrape returns a page with no case blocks → parser yields [].
    )
    respx.post(_NY_ECOURTS).mock(return_value=httpx.Response(200, text=_ny_ecourts_html()))
    out = await dockets.search_dockets("example llc", limit=5)
    assert len(out) == 2
    first = out[0]
    assert first["source"] == "state_ny"
    assert first["case_name"] == "EXAMPLE LLC"
    assert first["docket_number"] == "651256/2023"
    assert first["id"] == "651256/2023"
    assert first["date_filed"] == "2023-11-08"
    assert first["nature_of_suit"] == "Contract"
    assert "New York" in first["court"]
    assert _NY_ECOURTS in first["url"]


@respx.mock
async def test_dockets_search_state_never_raises() -> None:
    respx.get(url__startswith=f"{_CL_BASE}/dockets/?").mock(
        return_value=httpx.Response(200, json={"results": []})
    )
    respx.get(url__startswith=f"{_CL_BASE}/search/?").mock(
        return_value=httpx.Response(200, json={"results": []})
    )
    respx.get(url__startswith=f"{_JUSTIA}/search").mock(
        return_value=httpx.Response(200, text="<html></html>")
    )
    respx.post(_NY_ECOURTS).mock(return_value=httpx.Response(500))
    assert await dockets.search_dockets("example") == []
    assert respx.calls.call_count == 5


@respx.mock
async def test_dockets_get_state_fallback() -> None:
    # Justia docket scrape misses → NY eCourts index-number lookup.
    respx.get(url__startswith=f"{_JUSTIA}/docket/").mock(return_value=httpx.Response(404))
    respx.post(_NY_ECOURTS).mock(return_value=httpx.Response(200, text=_ny_ecourts_html()))
    out = await dockets.get_docket("651256/2023")
    assert out["source"] == "state_ny"
    assert out["case_name"] == "EXAMPLE LLC"
    assert out["docket_number"] == "651256/2023"
    assert out["date_filed"] == "2023-11-08"
    # Detail shape: the lookup fills the extended keys with None.
    assert out["description"] is None
    assert out["panel"] is None


# ── SEC EDGAR filings ──────────────────────────────────────────────────


@respx.mock
async def test_sec_search_success() -> None:
    respx.get(url=_TICKERS).mock(return_value=httpx.Response(200, json=_tickers_payload()))
    respx.get(url__startswith=_FTS).mock(return_value=httpx.Response(200, json=_fts_payload()))
    out = await sec_filings.search_filings("aapl", form_type="8-K", limit=5)
    assert len(out) == 1
    assert out[0]["accession_number"] == "0000320193-24-000005"
    assert out[0]["filing_date"] == "2024-02-01"
    assert out[0]["form_type"] == "8-K"
    assert out[0]["ticker"] == "AAPL"
    assert out[0]["cik"] == "0000320193"
    assert out[0]["company_names"][0].startswith("Apple Inc.")
    assert out[0]["documents"][0]["url"] == (
        "https://www.sec.gov/Archives/edgar/data/320193/000032019324000005/aapl-20240201.htm"
    )
    assert out[0]["source"] == "sec_edgar"


@respx.mock
async def test_sec_search_unknown_ticker() -> None:
    respx.get(url=_TICKERS).mock(return_value=httpx.Response(200, json=_tickers_payload()))
    assert await sec_filings.search_filings("NOPE") == []
    assert respx.calls.call_count == 1


@respx.mock
async def test_sec_search_never_raises_network_error() -> None:
    respx.get(url=_TICKERS).mock(return_value=httpx.Response(500))
    respx.get(url__startswith=_FTS).mock(return_value=httpx.Response(500))
    assert await sec_filings.search_filings("aapl") == []
    assert respx.calls.call_count == 4


async def test_sec_search_blank_ticker() -> None:
    assert await sec_filings.search_filings("  ") == []
    assert respx.calls.call_count == 0


@respx.mock
async def test_get_filing_success() -> None:
    respx.get(url__startswith=_FTS).mock(return_value=httpx.Response(200, json=_fts_payload()))
    respx.get(url__startswith=_INDEX).mock(return_value=httpx.Response(200, json=_index_payload()))
    out = await sec_filings.get_filing("0000320193-24-000005")
    assert out["accession_number"] == "0000320193-24-000005"
    expected = ["aapl-20240201.htm", "FilingSummary.xml"]
    assert out["files"] == expected
    assert out["filing_index"] == _INDEX + "index.json"


@respx.mock
async def test_get_filing_unknown_accession() -> None:
    respx.get(url__startswith=_FTS).mock(
        return_value=httpx.Response(200, json={"hits": {"hits": []}})
    )
    assert await sec_filings.get_filing("0000320193-24-999999") == {}
    assert respx.calls.call_count == 1


@respx.mock
async def test_get_filing_never_raises() -> None:
    respx.get(url__startswith=_FTS).mock(return_value=httpx.Response(500))
    assert await sec_filings.get_filing("0000320193-24-000005") == {}
    assert respx.calls.call_count == 2


@respx.mock
async def test_insider_trades_success() -> None:
    respx.get(url=_TICKERS).mock(return_value=httpx.Response(200, json=_tickers_payload()))
    respx.get(url=_SUBMISSIONS).mock(return_value=httpx.Response(200, json=_submissions_payload()))
    respx.get(url__startswith=_FTS).mock(
        return_value=httpx.Response(
            200,
            json={
                "hits": {
                    "hits": [
                        {
                            "_id": "0001140361-26-032884:xslF345X06/form4.xml",
                            "_source": {
                                "adsh": "0001140361-26-032884",
                                "form": "4",
                                "file_date": "2026-08-13",
                                "display_names": ["SMITH JOHN"],
                                "ciks": ["0001140361"],
                            },
                        }
                    ]
                }
            },
        )
    )
    out = await sec_filings.insider_trades("aapl", limit=5)
    assert len(out) == 2
    assert out[0]["ticker"] == "AAPL"
    assert out[0]["company_name"] == "Apple Inc."
    assert out[0]["form_type"] == "4"
    assert out[0]["accession_number"] == "0001140361-26-032884"
    assert out[0]["owner"] == "SMITH JOHN"
    assert out[0]["document_url"] == (
        "https://www.sec.gov/Archives/edgar/data/1140361/000114036126032884/xslF345X06/form4.xml"
    )
    assert out[1]["owner"] is None


@respx.mock
async def test_insider_trades_never_raises_network_error() -> None:
    respx.get(url=_TICKERS).mock(return_value=httpx.Response(500))
    assert await sec_filings.insider_trades("aapl") == []
    assert respx.calls.call_count == 2


@respx.mock
async def test_insider_trades_no_form4_filings() -> None:
    respx.get(url=_TICKERS).mock(return_value=httpx.Response(200, json=_tickers_payload()))
    payload = _submissions_payload()
    payload["filings"]["recent"]["form"] = ["10-Q", "8-K", "10-K"]
    respx.get(url=_SUBMISSIONS).mock(return_value=httpx.Response(200, json=payload))
    assert await sec_filings.insider_trades("aapl") == []
    assert respx.calls.call_count == 2


# ── OFAC SDN sanctions ────────────────────────────────────────────────


@respx.mock
async def test_screen_name_json_source() -> None:
    respx.get(url__startswith=_OFAC_JSON).mock(
        return_value=httpx.Response(200, json=_sdn_json_payload())
    )
    out = await sanctions.screen_name("john smith")
    assert len(out) == 1
    assert out[0]["uid"] == "12345"
    assert out[0]["name"] == "JOHN SMITH"
    assert out[0]["sdn_type"] == "Individual"
    expected = ["SDGT"]
    assert out[0]["programs"] == expected
    expected_2 = ["primary"]
    assert out[0]["matched_fields"] == expected_2
    assert out[0]["source"] == "ofac_sdn"


@respx.mock
async def test_screen_name_xml_fallback() -> None:
    respx.get(url__startswith=_OFAC_JSON).mock(return_value=httpx.Response(404))
    respx.get(url__startswith=_OFAC_XML).mock(return_value=httpx.Response(200, text=_sdn_xml()))
    out = await sanctions.screen_name("aerocaribbean")
    assert len(out) == 1
    assert out[0]["uid"] == "36"
    expected = ["CUBA"]
    assert out[0]["programs"] == expected
    expected_2 = ["AERO-CARIBBEAN"]
    assert out[0]["akas"] == expected_2


@respx.mock
async def test_screen_name_csv_fallback() -> None:
    csv_body = '36,"AEROCARIBBEAN AIRLINES",-0- ,"CUBA",-0- ,-0- ,-0- ,-0- ,-0- ,-0- ,-0- ,-0- \n'
    respx.get(url__startswith=_OFAC_JSON).mock(return_value=httpx.Response(404))
    respx.get(url__startswith=_OFAC_XML).mock(return_value=httpx.Response(500))
    respx.get(url__startswith=_OFAC_CSV).mock(return_value=httpx.Response(200, text=csv_body))
    out = await sanctions.screen_name("aerocaribbean")
    assert len(out) == 1
    assert out[0]["uid"] == "36"
    expected = ["CUBA"]
    assert out[0]["programs"] == expected


@respx.mock
async def test_screen_name_no_match() -> None:
    respx.get(url__startswith=_OFAC_JSON).mock(
        return_value=httpx.Response(200, json=_sdn_json_payload())
    )
    assert await sanctions.screen_name("nobody here") == []
    assert respx.calls.call_count == 1


@respx.mock
async def test_screen_name_never_raises() -> None:
    for url in (_OFAC_JSON, _OFAC_XML, _OFAC_CSV):
        respx.get(url__startswith=url).mock(return_value=httpx.Response(500))
    assert await sanctions.screen_name("john smith") == []
    assert respx.calls.call_count == 6


async def test_screen_name_blank_name() -> None:
    assert await sanctions.screen_name("   ") == []
    assert respx.calls.call_count == 0


@respx.mock
async def test_screen_name_disk_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cache_file = tmp_path / "sdn_cache.json"
    monkeypatch.setenv("PRY_LEGAL_OFAC_CACHE_PATH", str(cache_file))
    respx.get(url__startswith=_OFAC_JSON).mock(
        return_value=httpx.Response(200, json=_sdn_json_payload())
    )
    out = await sanctions.screen_name("john smith")
    assert out
    assert cache_file.exists()
    cached = json.loads(cache_file.read_text(encoding="utf-8"))
    assert isinstance(cached.get("entries"), list)
    assert len(cached["entries"]) == 2

    # Break the network; the disk cache must still serve entries.
    sanctions.reset_cache()
    for url in (_OFAC_JSON, _OFAC_XML, _OFAC_CSV):
        respx.get(url__startswith=url).mock(return_value=httpx.Response(500))
    out2 = await sanctions.screen_name("john smith")
    assert out2
    assert out2[0]["uid"] == "12345"


# ── Router tests ───────────────────────────────────────────────────────


@pytest.fixture
def legal_app() -> FastAPI:
    app = FastAPI()

    @app.exception_handler(PryError)
    async def pry_error_handler(request: Request, exc: PryError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": str(exc)})

    app.include_router(legal_router)
    return app


def _client(app: FastAPI) -> TestClient:
    return TestClient(app)


def test_router_importable() -> None:
    assert hasattr(legal_docs, "search_dockets")
    assert hasattr(legal_docs, "get_docket")
    assert hasattr(legal_docs, "search_filings")
    assert hasattr(legal_docs, "get_filing")
    assert hasattr(legal_docs, "insider_trades")
    assert hasattr(legal_docs, "screen_name")
    assert hasattr(legal_router_mod, "router")


def test_router_dockets_search_success(legal_app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake(query: str, limit: int = 20) -> list[dict[str, Any]]:
        return [{"id": 42, "case_name": f"match for {query}", "source": "courtlistener"}]

    monkeypatch.setattr(dockets, "search_dockets", fake)
    resp = _client(legal_app).get(
        "/v1/legal/dockets/search", params={"query": "example fraud", "limit": 5}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["query"] == "example fraud"
    assert body["data"][0]["id"] == 42


def test_router_dockets_get_success(legal_app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake(docket_id: int) -> dict[str, Any]:
        return {"id": docket_id, "case_name": "SEC v. Example Corp.", "source": "courtlistener"}

    monkeypatch.setattr(dockets, "get_docket", fake)
    resp = _client(legal_app).get("/v1/legal/dockets/42")
    assert resp.status_code == 200
    assert resp.json()["data"]["id"] == 42


def test_router_sec_search_success(legal_app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake(ticker: str, form_type: str = "8-K", limit: int = 20) -> list[dict[str, Any]]:
        return [{"accession_number": "a", "form_type": form_type, "ticker": ticker.upper()}]

    monkeypatch.setattr(sec_filings, "search_filings", fake)
    resp = _client(legal_app).get(
        "/v1/legal/sec/search", params={"ticker": "aapl", "form_type": "10-Q"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["data"][0]["form_type"] == "10-Q"
    assert body["ticker"] == "AAPL"


def test_router_sec_insider_success(legal_app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake(ticker: str, limit: int = 20) -> list[dict[str, Any]]:
        return [{"ticker": ticker.upper(), "owner": "SMITH JOHN", "form_type": "4"}]

    monkeypatch.setattr(sec_filings, "insider_trades", fake)
    resp = _client(legal_app).get("/v1/legal/sec/insider/aapl")
    assert resp.status_code == 200
    assert resp.json()["data"][0]["owner"] == "SMITH JOHN"


def test_router_sanctions_success(legal_app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake(name: str) -> list[dict[str, Any]]:
        return [{"uid": "12345", "name": "JOHN SMITH", "source": "ofac_sdn"}]

    monkeypatch.setattr(sanctions, "screen_name", fake)
    resp = _client(legal_app).get("/v1/legal/sanctions/john%20smith")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["data"][0]["name"] == "JOHN SMITH"
    assert body["name"] == "john smith"


def test_router_502_when_module_absent(legal_app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(legal_router_mod, "_legal_module", lambda name: None)
    assert (
        _client(legal_app).get("/v1/legal/dockets/search", params={"query": "x"}).status_code == 502
    )
    assert _client(legal_app).get("/v1/legal/dockets/42").status_code == 502
    assert (
        _client(legal_app).get("/v1/legal/sec/search", params={"ticker": "aapl"}).status_code == 502
    )
    assert _client(legal_app).get("/v1/legal/sec/insider/aapl").status_code == 502
    assert _client(legal_app).get("/v1/legal/sanctions/x").status_code == 502


def test_router_validation_422(legal_app: FastAPI) -> None:
    assert (
        _client(legal_app).get("/v1/legal/dockets/search", params={"query": ""}).status_code == 422
    )
    assert _client(legal_app).get("/v1/legal/dockets/abc").status_code == 422
    assert _client(legal_app).get("/v1/legal/sec/search", params={"ticker": ""}).status_code == 422
    assert (
        _client(legal_app)
        .get("/v1/legal/sec/search", params={"ticker": "aapl", "limit": 0})
        .status_code
        == 422
    )
    assert (
        _client(legal_app).get("/v1/legal/sec/insider/aapl", params={"limit": 101}).status_code
        == 422
    )
