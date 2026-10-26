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
    _hermetic_legal,  # noqa: F401
    _submissions_payload,
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
