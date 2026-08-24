# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for the news_data package (GDELT headlines + sentiment).

Covers the GDELT DOC 2.0 Article List JSON mapping, the RSS fallback, the
never-raise contract (HTTP error / malformed payload / empty query), the
full-article extraction path (reusing Pry's scraper), GDELT-tone +
keyword-fallback sentiment aggregation, the per-day entity timeline, and
the /v1/news/* router (200 + 502-degradation + 422 validation).

All HTTP is mocked with respx — no live network.
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

import datasets.news_data as news_data
import datasets.news_data.headlines as headlines
import datasets.news_data.sentiment as sentiment
import routers.news_data as news_router_mod
from pry.core.errors import PryError
from routers.news_data import router as news_router

_GDELT_URL = "https://api.gdeltproject.org/api/v2/doc/doc"


# ── fixtures ───────────────────────────────────────────────────────────


def _json_articles() -> list[dict[str, Any]]:
    return [
        {
            "url": "https://news.example.com/bitcoin-surge",
            "url_mobile": "",
            "title": "Bitcoin Surges To Record High",
            "seendate": "20260815T120000Z",
            "socialimage": "https://news.example.com/img1.jpg",
            "domain": "news.example.com",
            "language": "English",
            "sourcecountry": "United States",
        },
        {
            "url": "https://alt.example.com/crypto-update",
            "url_mobile": "",
            "title": "Crypto Market Update",
            "seendate": "20260816T090000Z",
            "socialimage": "",
            "domain": "alt.example.com",
            "language": "English",
            "sourcecountry": "United Kingdom",
        },
    ]


def _json_payload() -> str:
    return json.dumps({"articles": _json_articles()})


def _csv_payload() -> str:
    """GDELT artlist CSV with a BOM, header row and per-article Tone values.

    The ``Tone`` column is quoted and contains the 9 comma-separated tone
    components; the compound score is the first value.
    """
    rows = [
        "Seendate,DocumentIdentifier,DocumentSource,SourceCommonName,DocumentTitle,Language,Tone",
        (
            "20260815T120000Z,https://news.example.com/bitcoin-surge,news.example.com,"
            "News One,Bitcoin Surges To Record High,English,"
            '"2.5,1.0,0.0,1.0,0.0,0.0,0.0,0.0,0.0"'
        ),
        (
            "20260816T090000Z,https://news.example.com/bitcoin-crash,news.example.com,"
            "News One,Bitcoin Crashes Amid Panic,English,"
            '"-3.0,0.0,2.0,-1.0,0.0,0.0,0.0,0.0,0.0"'
        ),
        (
            "20260816T110000Z,https://alt.example.com/etf-update,alt.example.com,"
            "News Two,ETF Market Update,English,"
            '"1.0,0.5,0.0,0.5,0.0,0.0,0.0,0.0,0.0"'
        ),
    ]
    return "\ufeff" + "\n".join(rows) + "\n"


def _rss_payload() -> str:
    return """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>GDELT</title>
<item>
  <title>Bitcoin Surges To Record High</title>
  <link>https://news.example.com/bitcoin-surge</link>
  <pubDate>Sat, 15 Aug 2026 12:00:00 GMT</pubDate>
  <source>news.example.com</source>
  <enclosure url="https://news.example.com/img1.jpg" type="image/jpeg"/>
</item>
<item>
  <title>Altcoin Update</title>
  <link>https://alt.example.com/altcoin-update</link>
  <pubDate>Sun, 16 Aug 2026 09:00:00 GMT</pubDate>
  <source>alt.example.com</source>
</item>
</channel></rss>"""


def _news_app() -> FastAPI:
    app = FastAPI()

    @app.exception_handler(PryError)
    async def pry_error_handler(request: Request, exc: PryError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": str(exc)})

    app.include_router(news_router)
    return app


# ── headlines: get_headlines ───────────────────────────────────────────


@respx.mock
async def test_headlines_json_success() -> None:
    respx.get(_GDELT_URL).mock(return_value=httpx.Response(200, text=_json_payload()))

    results = await headlines.get_headlines("bitcoin", limit=10)

    assert len(results) == 2
    first = results[0]
    assert first == {
        "title": "Bitcoin Surges To Record High",
        "url": "https://news.example.com/bitcoin-surge",
        "source": "news.example.com",
        "domain": "news.example.com",
        "published": "2026-08-15T12:00:00Z",
        "image": "https://news.example.com/img1.jpg",
    }
    assert results[1]["image"] == ""
    # JSON path used — no RSS request
    assert len(respx.calls) == 1
    params = respx.calls[0].request.url.params
    assert params["mode"] == "artlist"
    assert params["format"] == "json"
    assert params["timespan"] == "24h"
    assert params["maxrecords"] == "10"


@respx.mock
async def test_headlines_limit_clamped() -> None:
    respx.get(_GDELT_URL).mock(return_value=httpx.Response(200, text=_json_payload()))

    await headlines.get_headlines("bitcoin", limit=500)

    params = respx.calls[0].request.url.params
    assert params["maxrecords"] == "250"


@respx.mock
async def test_headlines_rss_fallback() -> None:
    respx.get(_GDELT_URL).mock(
        side_effect=[
            httpx.Response(500),
            httpx.Response(200, text=_rss_payload()),
        ]
    )

    results = await headlines.get_headlines("bitcoin")

    assert len(results) == 2
    first = results[0]
    assert first["title"] == "Bitcoin Surges To Record High"
    assert first["url"] == "https://news.example.com/bitcoin-surge"
    assert first["source"] == "news.example.com"
    assert first["domain"] == "news.example.com"
    assert first["published"] == "2026-08-15T12:00:00Z"
    assert first["image"] == "https://news.example.com/img1.jpg"
    assert len(respx.calls) == 2
    assert respx.calls[1].request.url.params["format"] == "rss"


@respx.mock
async def test_headlines_malformed_json_falls_back_to_rss() -> None:
    respx.get(_GDELT_URL).mock(
        side_effect=[
            httpx.Response(200, text="not-json{"),
            httpx.Response(200, text=_rss_payload()),
        ]
    )

    results = await headlines.get_headlines("bitcoin")

    assert len(results) == 2
    assert results[0]["title"] == "Bitcoin Surges To Record High"


@respx.mock
async def test_headlines_all_paths_fail_returns_empty() -> None:
    respx.get(_GDELT_URL).mock(return_value=httpx.Response(503))

    assert await headlines.get_headlines("bitcoin") == []
    assert len(respx.calls) == 2  # json + rss


@respx.mock
async def test_headlines_empty_query_no_network() -> None:
    assert await headlines.get_headlines("   ") == []
    assert respx.calls.call_count == 0


@respx.mock
async def test_headlines_json_garbage_articles_skipped() -> None:
    payload = json.dumps({"articles": [{"url": "https://a.com/x"}, {"not": "a dict"}, "str"]})
    respx.get(_GDELT_URL).mock(return_value=httpx.Response(200, text=payload))

    results = await headlines.get_headlines("bitcoin")

    assert len(results) == 1
    assert results[0]["url"] == "https://a.com/x"


# ── headlines: get_article ─────────────────────────────────────────────


def _fake_scraper_ok() -> Any:
    class _Fake:
        async def scrape(self, url: str, options: dict | None = None) -> dict[str, Any]:
            return {
                "url": url,
                "status": "ok",
                "title": "Bitcoin Surges To Record High",
                "content": (
                    "Bitcoin hit a new record high on Tuesday. Investors piled "
                    "into the asset amid strong demand. Analysts expect the "
                    "rally to continue into next quarter. Trading volume "
                    "reached all-time levels across major exchanges."
                ),
                "raw_html": (
                    "<html><head>"
                    '<meta name="author" content="Jane Doe">'
                    '<meta property="article:published_time" content="2026-08-15T12:00:00Z">'
                    "</head><body></body></html>"
                ),
                "method": "direct",
                "quality_score": 90,
            }

    return _Fake()


def _fake_scraper_error() -> Any:
    class _Fake:
        async def scrape(self, url: str, options: dict | None = None) -> dict[str, Any]:
            return {"url": url, "status": "error", "error": "blocked", "content": ""}

    return _Fake()


def _fake_scraper_raises() -> Any:
    class _Fake:
        async def scrape(self, url: str, options: dict | None = None) -> dict[str, Any]:
            raise RuntimeError("boom")

    return _Fake()


@respx.mock
async def test_get_article_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(headlines, "_get_scraper", lambda: _fake_scraper_ok())

    article = await headlines.get_article("https://news.example.com/bitcoin-surge")

    assert article["title"] == "Bitcoin Surges To Record High"
    assert article["text"].startswith("Bitcoin hit a new record high")
    assert article["summary"]  # non-empty extractive summary
    assert article["keywords"]  # non-empty keyword list
    assert article["authors"] == ["Jane Doe"]
    assert article["published"] == "2026-08-15T12:00:00Z"


@respx.mock
async def test_get_article_invalid_url_no_scrape(monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[str] = []

    class _Fake:
        async def scrape(self, url: str, options: dict | None = None) -> dict[str, Any]:
            called.append(url)
            return {"status": "ok", "content": "x"}

    monkeypatch.setattr(headlines, "_get_scraper", lambda: _Fake())

    assert await headlines.get_article("") == {}
    assert await headlines.get_article("not-a-url") == {}
    assert called == []


@respx.mock
async def test_get_article_scraper_error_returns_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(headlines, "_get_scraper", lambda: _fake_scraper_error())

    assert await headlines.get_article("https://news.example.com/blocked") == {}


@respx.mock
async def test_get_article_scraper_raises_returns_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(headlines, "_get_scraper", lambda: _fake_scraper_raises())

    assert await headlines.get_article("https://news.example.com/boom") == {}


# ── sentiment: helpers ─────────────────────────────────────────────────


def test_keyword_tone_positive_and_negative() -> None:
    assert sentiment._keyword_tone("Bitcoin surges to record high") > 0
    assert sentiment._keyword_tone("Bitcoin crashes amid panic") < 0
    assert sentiment._keyword_tone("The market had a neutral day") == 0.0
    assert sentiment._keyword_tone("") == 0.0


def test_tone_compound_parsing() -> None:
    assert sentiment._tone_compound("2.5,1.0,0.0,1.0,0.0,0.0,0.0,0.0,0.0") == 2.5
    assert sentiment._tone_compound("-3.0,0.0,2.0,-1.0,0.0,0.0,0.0,0.0,0.0") == -3.0
    assert sentiment._tone_compound("") is None
    assert sentiment._tone_compound(None) is None
    assert sentiment._tone_compound("abc") is None


def test_parse_seendate() -> None:
    assert headlines._parse_seendate("20260815T120000Z") == "2026-08-15T12:00:00Z"
    assert headlines._parse_seendate("garbage") == ""
    assert headlines._parse_seendate("") == ""


def test_sanitize_timeframe() -> None:
    assert headlines._sanitize_timeframe("7d") == "7d"
    assert headlines._sanitize_timeframe("24h") == "24h"
    assert headlines._sanitize_timeframe("1w") == "1w"
    assert headlines._sanitize_timeframe("bogus") == "24h"
    assert headlines._sanitize_timeframe(None) == "24h"


def test_summarize_and_keywords() -> None:
    long_text = "First sentence about bitcoin. Second sentence about trading. " * 20
    summary = headlines._summarize(long_text)
    assert len(summary) <= 350
    assert summary.startswith("First sentence about bitcoin.")
    assert headlines._keywords("Bitcoin bitcoin bitcoin rally rally") == ["bitcoin", "rally"]


# ── sentiment: get_sentiment ───────────────────────────────────────────


@respx.mock
async def test_get_sentiment_csv_success() -> None:
    respx.get(_GDELT_URL).mock(return_value=httpx.Response(200, text=_csv_payload()))

    result = await sentiment.get_sentiment("bitcoin")

    assert result["query"] == "bitcoin"
    assert result["articles"] == 3
    assert result["avg_tone"] == pytest.approx(round((2.5 - 3.0 + 1.0) / 3, 2))
    assert result["positive_pct"] == pytest.approx(round(200.0 / 3, 1))
    assert result["negative_pct"] == pytest.approx(round(100.0 / 3, 1))
    assert result["mentions_timeline"] == [
        {"date": "2026-08-15", "count": 1, "avg_tone": 2.5},
        {"date": "2026-08-16", "count": 2, "avg_tone": -1.0},
    ]


@respx.mock
async def test_get_sentiment_json_keyword_fallback() -> None:
    payload = json.dumps(
        {
            "articles": [
                {
                    "url": "https://news.example.com/a",
                    "title": "Bitcoin surges to record high",
                    "seendate": "20260815T120000Z",
                    "domain": "news.example.com",
                },
                {
                    "url": "https://news.example.com/b",
                    "title": "Bitcoin crashes amid panic",
                    "seendate": "20260816T090000Z",
                    "domain": "news.example.com",
                },
            ]
        }
    )
    respx.get(_GDELT_URL).mock(
        side_effect=[
            httpx.Response(500),
            httpx.Response(200, text=payload),
        ]
    )

    result = await sentiment.get_sentiment("bitcoin")

    assert result["articles"] == 2
    assert result["avg_tone"] == 0.0  # +100 and -100 cancel out
    assert result["positive_pct"] == 50.0
    assert result["negative_pct"] == 50.0
    assert result["mentions_timeline"][0]["avg_tone"] == 100.0


@respx.mock
async def test_get_sentiment_all_paths_fail_returns_empty() -> None:
    respx.get(_GDELT_URL).mock(return_value=httpx.Response(503))

    assert await sentiment.get_sentiment("bitcoin") == {}


@respx.mock
async def test_get_sentiment_empty_query_no_network() -> None:
    assert await sentiment.get_sentiment("  ") == {}
    assert respx.calls.call_count == 0


@respx.mock
async def test_get_sentiment_malformed_csv_then_json_returns_empty() -> None:
    respx.get(_GDELT_URL).mock(
        side_effect=[
            httpx.Response(200, text="\ufeffgarbage,not,valid"),
            httpx.Response(200, text="not-json{"),
        ]
    )

    assert await sentiment.get_sentiment("bitcoin") == {}


# ── sentiment: get_entity_timeline ─────────────────────────────────────


@respx.mock
async def test_get_entity_timeline_csv_success() -> None:
    respx.get(_GDELT_URL).mock(return_value=httpx.Response(200, text=_csv_payload()))

    timeline = await sentiment.get_entity_timeline("bitcoin", timeframe="7d")

    assert timeline == [
        {
            "date": "2026-08-15",
            "articles": 1,
            "avg_tone": 2.5,
            "top_sources": [{"source": "News One", "count": 1}],
        },
        {
            "date": "2026-08-16",
            "articles": 2,
            "avg_tone": -1.0,
            "top_sources": [
                {"source": "News One", "count": 1},
                {"source": "News Two", "count": 1},
            ],
        },
    ]
    assert respx.calls[0].request.url.params["format"] == "csv"


@respx.mock
async def test_get_entity_timeline_error_returns_empty() -> None:
    respx.get(_GDELT_URL).mock(return_value=httpx.Response(503))

    assert await sentiment.get_entity_timeline("bitcoin") == []


@respx.mock
async def test_get_entity_timeline_empty_entity_no_network() -> None:
    assert await sentiment.get_entity_timeline("") == []
    assert respx.calls.call_count == 0


# ── package + router ───────────────────────────────────────────────────


def test_package_imports() -> None:
    assert hasattr(news_data, "get_headlines")
    assert hasattr(news_data, "get_article")
    assert hasattr(news_data, "get_sentiment")
    assert hasattr(news_data, "get_entity_timeline")


def test_router_importable() -> None:
    assert hasattr(news_router_mod, "router")
    assert hasattr(news_router_mod, "_news_module")


def test_router_headlines_success(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake(query: str, limit: int = 20, timeframe: str = "24h") -> list[dict[str, Any]]:
        return [
            {
                "title": query,
                "url": "https://news.example.com/a",
                "source": "news.example.com",
                "domain": "news.example.com",
                "published": "2026-08-15T12:00:00Z",
                "image": "",
            }
        ]

    monkeypatch.setattr(news_data, "get_headlines", fake)
    resp = TestClient(_news_app()).get("/v1/news/headlines", params={"query": "bitcoin"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["data"][0]["title"] == "bitcoin"
    assert body["limit"] == 20


def test_router_article_success(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake(url: str) -> dict[str, Any]:
        return {"title": "Bitcoin Surges", "text": "Body", "summary": "Body", "keywords": []}

    monkeypatch.setattr(news_data, "get_article", fake)
    resp = TestClient(_news_app()).get(
        "/v1/news/article", params={"url": "https://news.example.com/a"}
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["title"] == "Bitcoin Surges"


def test_router_sentiment_success(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake(query: str, timeframe: str = "24h", limit: int = 20) -> dict[str, Any]:
        return {
            "query": query,
            "avg_tone": 2.5,
            "positive_pct": 100.0,
            "negative_pct": 0.0,
            "articles": 1,
            "mentions_timeline": [{"date": "2026-08-15", "count": 1, "avg_tone": 2.5}],
        }

    monkeypatch.setattr(news_data, "get_sentiment", fake)
    resp = TestClient(_news_app()).get("/v1/news/sentiment", params={"query": "bitcoin"})
    assert resp.status_code == 200
    assert resp.json()["data"]["avg_tone"] == 2.5


def test_router_timeline_success(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake(entity: str, timeframe: str = "7d", limit: int = 20) -> list[dict[str, Any]]:
        return [{"date": "2026-08-15", "articles": 1, "avg_tone": 2.5, "top_sources": []}]

    monkeypatch.setattr(news_data, "get_entity_timeline", fake)
    resp = TestClient(_news_app()).get("/v1/news/timeline", params={"entity": "bitcoin"})
    assert resp.status_code == 200
    assert resp.json()["data"][0]["date"] == "2026-08-15"


def test_router_502_when_module_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(news_router_mod, "_news_module", lambda: None)
    client = TestClient(_news_app())
    assert client.get("/v1/news/headlines", params={"query": "x"}).status_code == 502
    assert (
        client.get("/v1/news/article", params={"url": "https://example.com/a"}).status_code == 502
    )
    assert client.get("/v1/news/sentiment", params={"query": "x"}).status_code == 502
    assert client.get("/v1/news/timeline", params={"entity": "x"}).status_code == 502


def test_router_validation() -> None:
    client = TestClient(_news_app())
    # empty / missing query -> 422
    assert client.get("/v1/news/headlines", params={"query": ""}).status_code == 422
    assert client.get("/v1/news/headlines").status_code == 422
    # limit out of range -> 422
    assert client.get("/v1/news/headlines", params={"query": "x", "limit": 0}).status_code == 422
    assert client.get("/v1/news/headlines", params={"query": "x", "limit": 500}).status_code == 422
    # missing url on article -> 422
    assert client.get("/v1/news/article").status_code == 422
    # missing entity on timeline -> 422
    assert client.get("/v1/news/timeline").status_code == 422
