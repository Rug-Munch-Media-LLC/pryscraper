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

import datasets.legal_docs.dockets as dockets
from pry.engine.retry import RetryConfig

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
from tests.legal._legal_docs_support2 import _ny_ecourts_html


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
