"""Tests for the legal_docs package (CourtListener / SEC EDGAR / OFAC SDN).

Covers docket search + lookup, SEC filing search / filing lookup / Form 4
insider trades, OFAC SDN name screening (JSON source, XML fallback, disk
cache), the never-raise contract (HTTP errors and malformed payloads all
degrade to empty output), and the /v1/legal/* router (200 + 502-degradation
+ 422 validation).

All HTTP is mocked with respx — no live network.
"""
import json
from typing import TYPE_CHECKING

import httpx
import pytest
import respx

import datasets.legal_docs.sanctions as sanctions
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
from tests.legal._legal_docs_support import _sdn_json_payload, _sdn_xml


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
