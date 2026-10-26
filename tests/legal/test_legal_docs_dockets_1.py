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
import pytest
import respx

import datasets.legal_docs.dockets as dockets
from pry.engine.retry import RetryConfig
from tests.legal._legal_docs_support import (
    _cl_detail_payload,
    _cl_search_payload,
    _hermetic_legal,  # noqa: F401
)
from tests.legal._legal_docs_support2 import (
    _recap_payload,
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
