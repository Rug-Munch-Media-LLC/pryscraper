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
    _tickers_payload,
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
