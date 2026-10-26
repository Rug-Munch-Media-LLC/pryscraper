"""Tests for the legal_docs package (CourtListener / SEC EDGAR / OFAC SDN).

Covers docket search + lookup, SEC filing search / filing lookup / Form 4
insider trades, OFAC SDN name screening (JSON source, XML fallback, disk
cache), the never-raise contract (HTTP errors and malformed payloads all
degrade to empty output), and the /v1/legal/* router (200 + 502-degradation
+ 422 validation).

All HTTP is mocked with respx — no live network.
"""

import httpx
import respx

import datasets.legal_docs.sec_filings as sec_filings
from pry.engine.retry import RetryConfig
from tests.legal._legal_docs_support import (
    _fts_payload,
    _hermetic_legal,  # noqa: F401
    _index_payload,
)
from tests.legal._legal_docs_support2 import legal_app  # noqa: F401

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
