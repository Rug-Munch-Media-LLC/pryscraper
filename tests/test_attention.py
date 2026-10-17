# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for the attention package (SERP / Trends / Ad Library).

Covers organic-result, AI Overview, and People-Also-Ask parsing; the
Google Trends internal-JSON flow; the Meta Ad Library embedded-JSON
extraction; the never-raise contract (HTTP errors, rate limits, bad
HTML/JSON all degrade to empty output); and the /v1/attention/* router
(200 + 502-degradation + query validation).

All HTTP is mocked (respx / monkeypatched fetch helpers) — no live
network.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
import respx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

import pry.api.client as _client_module
import pry.api.routers.data.attention as attention_router_mod
from datasets.attention import ad_intel, serp, trends
from pry.api.routers.data.attention import router as attention_router
from pry.core.errors import PryError


@pytest.fixture(autouse=True)
def _hermetic_attention(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Kill backoff sleeps + never leak a respx-bound shared client."""
    monkeypatch.setattr(serp, "RETRY_BASE", 0.0)
    monkeypatch.setattr(serp, "MAX_BACKOFF", 0.0)
    monkeypatch.setattr(trends, "RETRY_BASE", 0.0)
    monkeypatch.setattr(trends, "MAX_BACKOFF", 0.0)
    monkeypatch.setattr(ad_intel, "RETRY_BASE", 0.0)
    monkeypatch.setattr(ad_intel, "MAX_BACKOFF", 0.0)
    _client_module.http_client = None
    yield
    _client_module.http_client = None


# ── SERP HTML fixtures ─────────────────────────────────────────────────


def _serp_html() -> str:
    return """<!DOCTYPE html><html><body>
<div class="MjjYud">
  <a href="/url?q=https://example.com/bitcoin&sa=U&ved=2ahUKEwj"><h3>Bitcoin - Example</h3></a>
  <div class="VwiC3b"><span>Bitcoin is a decentralized digital currency.</span></div>
</div>
<div class="MjjYud">
  <a href="https://direct.example.org/page"><h3>Direct Link Result</h3></a>
  <div class="VwiC3b">No redirect wrapper here.</div>
</div>
<div class="MjjYud">
  <a href="/url?q=https://example.com/bitcoin&sa=U"><h3>Duplicate URL</h3></a>
  <div class="VwiC3b">Should be deduped.</div>
</div>
<div class="MjjYud">
  <a href="/url?q=https://google.com/internal"><h3>Google internal link</h3></a>
  <div class="VwiC3b">Should be skipped.</div>
</div>
</body></html>"""


def _ai_overview_class_html() -> str:
    return """<html><body>
<div class="MjjYud"><div class="ILfuVd"><span>AI Overview</span>Bitcoin price is driven by supply and demand on exchanges.</div></div>
</body></html>"""


def _ai_overview_label_html() -> str:
    return """<html><body>
<div class="answer-box"><span>AI Overview</span><div>Bitcoin uses proof of work to secure its ledger.</div></div>
</body></html>"""


def _paa_legacy_html() -> str:
    return """<html><body>
<div class="related-question-pair"><h3>What is Bitcoin?</h3></div>
<div class="related-question-pair"><h3>Who created Bitcoin?</h3></div>
</body></html>"""


def _paa_label_html() -> str:
    return """<html><body>
<div class="paa-section">
  <h3>People also ask</h3>
  <div class="paa-item"><h3>Is Bitcoin legal?</h3></div>
  <div class="paa-item"><h3>How is Bitcoin mined?</h3></div>
</div>
</body></html>"""


# ── SERP parsing unit tests ────────────────────────────────────────────


def test_clean_google_url_redirect_wrapper() -> None:
    href = "/url?q=https://example.com/bitcoin&sa=U&ved=0"
    assert serp._clean_google_url(href) == "https://example.com/bitcoin"


def test_clean_google_url_direct_and_skip() -> None:
    assert (
        serp._clean_google_url("https://direct.example.org/page")
        == "https://direct.example.org/page"
    )
    assert serp._clean_google_url("https://www.google.com/search?q=x") == ""
    assert serp._clean_google_url("") == ""
    assert serp._clean_google_url("/url?q=") == ""


def test_extract_results_organic_dedup_and_skip() -> None:
    root = serp._to_root(_serp_html())
    assert root is not None
    results = serp._extract_results(root, 10)
    assert len(results) == 2  # google.com internal link + duplicate excluded
    assert results[0]["position"] == 1
    assert results[0]["title"] == "Bitcoin - Example"
    assert results[0]["url"] == "https://example.com/bitcoin"
    assert results[0]["snippet"] == "Bitcoin is a decentralized digital currency."
    assert results[1]["url"] == "https://direct.example.org/page"
    assert results[1]["snippet"] == "No redirect wrapper here."


def test_extract_results_respects_num() -> None:
    root = serp._to_root(_serp_html())
    assert root is not None
    assert len(serp._extract_results(root, 1)) == 1


def test_extract_ai_overview_class_strategy() -> None:
    root = serp._to_root(_ai_overview_class_html())
    assert root is not None
    text = serp._extract_ai_overview(root)
    assert text is not None
    assert "AI Overview" not in text
    assert "supply and demand" in text


def test_extract_ai_overview_label_strategy() -> None:
    root = serp._to_root(_ai_overview_label_html())
    assert root is not None
    text = serp._extract_ai_overview(root)
    assert text is not None
    assert text == "Bitcoin uses proof of work to secure its ledger."


def test_extract_ai_overview_none_when_absent() -> None:
    root = serp._to_root("<html><body><p>No AI overview here.</p></body></html>")
    assert root is not None
    assert serp._extract_ai_overview(root) is None


def test_extract_paa_legacy_strategy() -> None:
    root = serp._to_root(_paa_legacy_html())
    assert root is not None
    paa = serp._extract_paa(root)
    expected = ["What is Bitcoin?", "Who created Bitcoin?"]
    assert paa == expected


def test_extract_paa_label_strategy() -> None:
    root = serp._to_root(_paa_label_html())
    assert root is not None
    paa = serp._extract_paa(root)
    assert "Is Bitcoin legal?" in paa
    assert "How is Bitcoin mined?" in paa
    assert "People also ask" not in paa


def test_extract_paa_empty_when_absent() -> None:
    root = serp._to_root("<html><body><p>No questions.</p></body></html>")
    assert root is not None
    assert serp._extract_paa(root) == []


# ── SERP async tests (mocked HTTP) ─────────────────────────────────────


@pytest.mark.parametrize(
    "html",
    [_serp_html(), "<html><body><p>blocked</p></body></html>", ""],
)
async def test_serp_never_raises(monkeypatch: pytest.MonkeyPatch, html: str) -> None:
    async def fake_fetch(query: str, num: int) -> str:
        return html

    monkeypatch.setattr(serp, "_fetch_serp", fake_fetch)
    result = await serp.serp("bitcoin", num=10)
    assert isinstance(result, dict)
    assert result["query"] == "bitcoin"
    assert isinstance(result["results"], list)
    assert isinstance(result["paa"], list)
    assert "ai_overview" in result


async def test_serp_success_mocked_fetch(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_fetch(query: str, num: int) -> str:
        assert num == 5
        return _serp_html()

    monkeypatch.setattr(serp, "_fetch_serp", fake_fetch)
    result = await serp.serp("bitcoin", num=5)
    assert "error" not in result  # no error key on success
    assert len(result["results"]) == 2
    assert result["results"][0]["url"] == "https://example.com/bitcoin"


async def test_serp_empty_query() -> None:
    result = await serp.serp("   ")
    assert result["results"] == []
    assert "error" in result


@respx.mock
async def test_serp_respx_success() -> None:
    route = respx.get(url__startswith="https://www.google.com/search").mock(
        return_value=httpx.Response(200, text=_serp_html())
    )
    result = await serp.serp("bitcoin", num=10)
    assert route.called
    assert len(result["results"]) == 2


@respx.mock
async def test_serp_rate_limited_never_raises() -> None:
    respx.get(url__startswith="https://www.google.com/search").mock(
        return_value=httpx.Response(429)
    )
    result = await serp.serp("bitcoin", num=10)
    assert result["results"] == []
    assert result["ai_overview"] is None
    assert "error" in result


# ── Trends unit tests ──────────────────────────────────────────────────


def test_strip_prefix() -> None:
    assert trends._strip_prefix(')]}\'\n{"a": 1}') == '{"a": 1}'
    assert trends._strip_prefix('{"a": 1}') == '{"a": 1}'
    assert trends._strip_prefix(")]}'   x") == "x"


def test_format_date() -> None:
    assert trends._format_date(1_750_000_000_000) == "2025-06-15"
    assert trends._format_date("2016-12-11") == "2016-12-11"
    assert trends._format_date(None) == ""
    assert trends._format_date("junk") == "junk"


# ── Trends async tests (respx) ─────────────────────────────────────────

EXPLORE_WIDGETS = {
    "widgets": [
        {
            "id": "TIMESERIES",
            "request": {"time": "today 12-m", "resolution": "MONTH"},
            "token": "TOKEN_TS",
        },
        {
            "id": "RELATED_QUERIES",
            "request": {"time": "today 12-m"},
            "token": "TOKEN_RQ",
        },
    ]
}

TIMESERIES_DATA = {
    "default": {"timelineData": []},
    "timelineData": [
        {
            "time": "2025-08-01",
            "formattedTime": "Aug 1, 2025",
            "formattedAxisTime": "Aug 1, 2025",
            "value": [100],
        },
        {
            "time": "2025-09-01",
            "formattedTime": "Sep 1, 2025",
            "formattedAxisTime": "Sep 1, 2025",
            "value": [80],
        },
        {"time": "junk", "formattedTime": "?", "formattedAxisTime": "?", "value": ["breakout"]},
    ],
}

RELATED_DATA = {
    "rankedList": [
        {
            "rankedKeyword": [
                {"query": "btc price", "value": 100},
                {"query": "bitcoin news", "value": 90},
                {"query": "bitcoin halving", "value": "Breakout"},
            ]
        }
    ]
}


@respx.mock
async def test_trend_interest_success() -> None:
    respx.get(url__startswith="https://trends.google.com/trends/api/explore").mock(
        return_value=httpx.Response(200, text=")]}'\n" + json.dumps(EXPLORE_WIDGETS))
    )
    respx.get(
        url__startswith="https://trends.google.com/trends/api/widgetdata/multiline/json"
    ).mock(return_value=httpx.Response(200, text=")]}'\n" + json.dumps(TIMESERIES_DATA)))
    respx.get(
        url__startswith="https://trends.google.com/trends/api/widgetdata/relatedsearches/json"
    ).mock(return_value=httpx.Response(200, text=")]}'\n" + json.dumps(RELATED_DATA)))
    result = await trends.trend_interest("bitcoin", timeframe="today 12-m")
    assert result["keyword"] == "bitcoin"
    assert result["timeframe"] == "today 12-m"
    expected = [
        {"date": "2025-08-01", "value": 100},
        {"date": "2025-09-01", "value": 80},
        {"date": "junk", "value": 0},
    ]
    assert result["timeline"] == expected
    expected_2 = [
        {"query": "btc price", "value": 100},
        {"query": "bitcoin news", "value": 90},
        {"query": "bitcoin halving", "value": "Breakout"},
    ]
    assert result["related"] == expected_2
    assert "error" not in result


@respx.mock
async def test_trend_interest_explore_fails_never_raises() -> None:
    respx.get(url__startswith="https://trends.google.com/trends/api/explore").mock(
        return_value=httpx.Response(500)
    )
    result = await trends.trend_interest("bitcoin")
    assert result["timeline"] == []
    assert result["related"] == []
    assert "error" in result


async def test_trend_interest_empty_keyword() -> None:
    result = await trends.trend_interest("")
    assert result["timeline"] == []
    assert "error" in result


# ── Ad intel unit tests ────────────────────────────────────────────────


def _ad_library_html() -> str:
    payload = {
        "adLibraryResults": [
            {
                "adArchiveID": "111222333",
                "pageName": "Example Brand",
                "adCreative": {
                    "body": {"text": "Buy our new product today!"},
                    "link_data": {"link": "https://example.com/shop"},
                },
                "adStartTime": "2026-01-15T00:00:00+0000",
                "publisherPlatforms": ["facebook", "instagram"],
            },
            {
                "adArchiveID": "444555666",
                "pageName": "Example Brand",
                "adCreative": {"body": {"text": "Second ad creative."}},
                "adStartTime": "2026-02-01T00:00:00+0000",
                "publisherPlatforms": ["facebook"],
            },
        ]
    }
    return (
        '<html><body><script type="application/json" data-testid="ad_library">'
        + json.dumps(payload)
        + "</script></body></html>"
    )


def test_parse_entries_embedded_json() -> None:
    entries = ad_intel._parse_entries(_ad_library_html())
    assert len(entries) == 2
    ids = {e.get("adArchiveID") for e in entries}
    expected = {"111222333", "444555666"}
    assert ids == expected


def test_parse_entries_regex_fallback() -> None:
    html = '<html><body><div data-snapshot="x">"adArchiveID":"123456789"</div></body></html>'
    entries = ad_intel._parse_entries(html)
    expected = [{"adArchiveID": "123456789"}]
    assert entries == expected


def test_parse_entries_empty_html() -> None:
    assert ad_intel._parse_entries("<html><body>nothing</body></html>") == []


def test_normalize_shape() -> None:
    raw = [
        {
            "adArchiveID": "111222333",
            "pageName": "Example Brand",
            "adCreative": {
                "body": {"text": "Buy our new product today!"},
                "link_data": {"link": "https://example.com/shop"},
            },
            "adStartTime": "2026-01-15T00:00:00+0000",
            "publisherPlatforms": ["facebook", "instagram"],
        }
    ]
    ads = ad_intel._normalize(raw)
    expected = [
        {
            "ad_id": "111222333",
            "page": "Example Brand",
            "creative_text": "Buy our new product today!",
            "link": "https://example.com/shop",
            "start_date": "2026-01-15T00:00:00+0000",
            "platforms": ["facebook", "instagram"],
        }
    ]
    assert ads == expected


def test_normalize_dedupes() -> None:
    raw = [
        {"adArchiveID": "1", "pageName": "A", "adCreative": {"body": {"text": "first"}}},
        {"adArchiveID": "1", "pageName": "A", "adCreative": {"body": {"text": "dup"}}},
        {"adArchiveID": "2", "pageName": "A", "adCreative": {"body": {"text": "second"}}},
    ]
    ads = ad_intel._normalize(raw)
    expected = ["1", "2"]
    assert [a["ad_id"] for a in ads] == expected


# ── Ad intel async tests (mocked HTTP) ─────────────────────────────────


async def test_search_ads_success_mocked_fetch(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_fetch(params: dict[str, str]) -> str:
        assert params["country"] == "US"
        assert params["q"] == "Example Brand"
        return _ad_library_html()

    monkeypatch.setattr(ad_intel, "_fetch_page", fake_fetch)
    ads = await ad_intel.search_ads("Example Brand", country="US", limit=20)
    assert len(ads) == 2
    assert ads[0]["ad_id"] == "111222333"
    assert ads[0]["page"] == "Example Brand"
    assert ads[0]["creative_text"] == "Buy our new product today!"
    expected = ["facebook", "instagram"]
    assert ads[0]["platforms"] == expected


async def test_search_ads_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_fetch(params: dict[str, str]) -> str:
        return _ad_library_html()

    monkeypatch.setattr(ad_intel, "_fetch_page", fake_fetch)
    ads = await ad_intel.search_ads("Example Brand", limit=1)
    assert len(ads) == 1


async def test_search_ads_empty_page_name() -> None:
    assert await ad_intel.search_ads("   ") == []


async def test_search_ads_fetch_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_fetch(params: dict[str, str]) -> str:
        return ""

    monkeypatch.setattr(ad_intel, "_fetch_page", fake_fetch)
    assert await ad_intel.search_ads("Example Brand") == []


@respx.mock
async def test_search_ads_rate_limited_never_raises() -> None:
    respx.get(url__startswith="https://www.facebook.com/ads/library/").mock(
        return_value=httpx.Response(429)
    )
    assert await ad_intel.search_ads("Example Brand") == []


# ── Router tests ───────────────────────────────────────────────────────


@pytest.fixture
def attention_app() -> FastAPI:
    app = FastAPI()

    @app.exception_handler(PryError)
    async def pry_error_handler(request: Request, exc: PryError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": str(exc)})

    app.include_router(attention_router)
    return app


def _client(app: FastAPI) -> TestClient:
    return TestClient(app)


def test_router_importable() -> None:
    import datasets.attention as attention
    import pry.api.routers.data.attention

    assert hasattr(attention, "__version__")
    assert hasattr(pry.api.routers.data.attention, "router")


def test_router_serp_success(attention_app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_serp(query: str, num: int = 10) -> dict[str, Any]:
        return {
            "query": query,
            "results": [{"position": 1, "title": "T", "url": "https://e.com", "snippet": "s"}],
            "ai_overview": None,
            "paa": [],
        }

    monkeypatch.setattr(serp, "serp", fake_serp)
    resp = _client(attention_app).get("/v1/attention/serp", params={"q": "bitcoin", "num": 5})
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["data"]["query"] == "bitcoin"
    assert body["data"]["results"][0]["url"] == "https://e.com"


def test_router_trends_success(attention_app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_trend(keyword: str, timeframe: str = "today 12-m") -> dict[str, Any]:
        return {
            "keyword": keyword,
            "timeframe": timeframe,
            "timeline": [{"date": "d", "value": 1}],
            "related": [],
        }

    monkeypatch.setattr(trends, "trend_interest", fake_trend)
    resp = _client(attention_app).get(
        "/v1/attention/trends", params={"keyword": "bitcoin", "timeframe": "now 7-d"}
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["timeframe"] == "now 7-d"
    expected = [{"date": "d", "value": 1}]
    assert resp.json()["data"]["timeline"] == expected


def test_router_ads_success(attention_app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_ads(
        page_name: str, country: str = "US", limit: int = 20
    ) -> list[dict[str, Any]]:
        return [
            {
                "ad_id": "1",
                "page": page_name,
                "creative_text": "c",
                "link": "",
                "start_date": "",
                "platforms": [],
            }
        ]

    monkeypatch.setattr(ad_intel, "search_ads", fake_ads)
    resp = _client(attention_app).get(
        "/v1/attention/ads", params={"page_name": "OpenAI", "country": "US", "limit": 3}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["data"][0]["page"] == "OpenAI"


def test_router_serp_502_when_module_absent(
    attention_app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(attention_router_mod, "_attention_module", lambda name: None)
    resp = _client(attention_app).get("/v1/attention/serp", params={"q": "bitcoin"})
    assert resp.status_code == 502


def test_router_trends_502_when_module_absent(
    attention_app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(attention_router_mod, "_attention_module", lambda name: None)
    resp = _client(attention_app).get("/v1/attention/trends", params={"keyword": "bitcoin"})
    assert resp.status_code == 502


def test_router_ads_502_when_module_absent(
    attention_app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(attention_router_mod, "_attention_module", lambda name: None)
    resp = _client(attention_app).get("/v1/attention/ads", params={"page_name": "OpenAI"})
    assert resp.status_code == 502


def test_router_validation_422(attention_app: FastAPI) -> None:
    resp = _client(attention_app).get("/v1/attention/serp", params={"q": "bitcoin", "num": 0})
    assert resp.status_code == 422
    resp = _client(attention_app).get("/v1/attention/serp")
    assert resp.status_code == 422
