"""Tests for the legal_docs package (CourtListener / SEC EDGAR / OFAC SDN).

Covers docket search + lookup, SEC filing search / filing lookup / Form 4
insider trades, OFAC SDN name screening (JSON source, XML fallback, disk
cache), the never-raise contract (HTTP errors and malformed payloads all
degrade to empty output), and the /v1/legal/* router (200 + 502-degradation
+ 422 validation).

All HTTP is mocked with respx — no live network.
"""
import re

import httpx
import respx

import datasets.legal_docs.dockets as dockets
from pry.engine.retry import RetryConfig
from tests.legal._legal_docs_support import _hermetic_legal  # noqa: F401
from tests.legal._legal_docs_support2 import (
    _justia_search_html,
    _ny_ecourts_html,
    _pacer_payload,
    legal_app,  # noqa: F401
)

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
