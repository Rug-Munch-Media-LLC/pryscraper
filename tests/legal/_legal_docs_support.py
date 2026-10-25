from __future__ import annotations

from typing import Any

import pytest

import datasets.legal_docs.dockets as dockets
import datasets.legal_docs.sanctions as sanctions
import datasets.legal_docs.sec_filings as sec_filings


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
