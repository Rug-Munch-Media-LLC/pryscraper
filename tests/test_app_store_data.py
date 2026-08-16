# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for the app_store_data package (Apple App Store + Google Play).

Covers the iTunes Search/Lookup/RSS mappings (search, details, reviews,
single-entry feed handling), the Google Play embedded-JSON scraper
(search, details, getreviews POST), anti-bot detection/flagging, the
never-raise degradation contract, and the /v1/appstore/* routers
(200 + 502-degradation + 422 validation).

All HTTP is mocked with respx — no live network.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

import app_store_data.apple as apple
import app_store_data.google_play as google_play
import routers.app_store_data as appstore_router_mod
from errors import PryError
from retry import RetryConfig
from routers.app_store_data import router as appstore_router

_APPLE_SEARCH = "https://itunes.apple.com/search"
_APPLE_LOOKUP = "https://itunes.apple.com/lookup"
_APPLE_RSS = "https://itunes.apple.com/us/rss/customerreviews/"
_PLAY_SEARCH = "https://play.google.com/store/search"
_PLAY_DETAILS = "https://play.google.com/store/apps/details"
_PLAY_REVIEWS = "https://play.google.com/store/getreviews"

_ZERO_RETRY = RetryConfig(
    max_retries=1, base_delay=0.0, max_delay=0.0, retryable_exceptions=(httpx.HTTPError,)
)


@pytest.fixture(autouse=True)
def _hermetic_appstore(monkeypatch: pytest.MonkeyPatch) -> None:
    """Kill backoff delays and reset the anti-bot flag between tests."""
    monkeypatch.setattr(apple, "_RETRY_CONFIG", _ZERO_RETRY)
    monkeypatch.setattr(google_play, "_RETRY_CONFIG", _ZERO_RETRY)
    google_play.last_anti_bot = False


# ── Payload fixtures ───────────────────────────────────────────────────


def _apple_search_payload() -> dict[str, Any]:
    return {
        "resultCount": 2,
        "results": [
            {
                "trackId": 284882215,
                "trackName": "Facebook",
                "artistName": "Meta",
                "primaryGenreName": "Social Networking",
                "averageUserRating": 4.3,
                "userRatingCount": 20568113,
                "formattedPrice": "Free",
                "version": "472.0",
                "trackViewUrl": "https://apps.apple.com/us/app/facebook/id284882215",
            },
            {
                "trackId": 123456,
                "trackName": "Widget Pro",
                "artistName": "Acme Inc",
                "primaryGenreName": "Productivity",
                "averageUserRating": 3.5,
                "userRatingCount": 100,
                "formattedPrice": "$1.99",
                "version": "1.0",
                "trackViewUrl": "https://apps.apple.com/us/app/widget-pro/id123456",
            },
        ],
    }


def _apple_lookup_payload() -> dict[str, Any]:
    return {
        "resultCount": 1,
        "results": [
            {
                "trackId": 284882215,
                "trackName": "Facebook",
                "artistName": "Meta",
                "primaryGenreName": "Social Networking",
                "averageUserRating": 4.3,
                "userRatingCount": 20568113,
                "formattedPrice": "Free",
                "version": "472.0",
                "trackViewUrl": "https://apps.apple.com/us/app/facebook/id284882215",
                "description": "Connect with friends and the world.",
                "sellerName": "Meta Platforms, Inc.",
                "releaseDate": "2009-02-04T21:29:05Z",
                "minimumOsVersion": "16.0",
                "fileSizeBytes": "123456789",
                "screenshotUrls": ["https://is1-ssl.mzstatic.com/image/1.png"],
                "currency": "USD",
            }
        ],
    }


def _apple_rss_payload() -> dict[str, Any]:
    return {
        "feed": {
            "entry": [
                {
                    "author": {"name": {"label": "AppUser99"}},
                    "rating": {"label": "5"},
                    "title": {"label": "Love it"},
                    "content": {"label": "The best app"},
                    "updated": {"label": "2026-08-15T12:00:00-07:00"},
                    "im:version": {"label": "472.0"},
                },
                {
                    "author": {"name": {"label": "MehUser"}},
                    "rating": {"label": "2"},
                    "title": {"label": "Meh"},
                    "content": {"label": "Too many bugs"},
                    "updated": {"label": "2026-08-14T10:00:00-07:00"},
                    "im:version": {"label": "471.0"},
                },
            ]
        }
    }


def _play_search_html() -> str:
    payload = {
        "props": {
            "pageProps": {
                "clusters": [
                    {
                        "appId": "com.instagram.android",
                        "title": "Instagram",
                        "appName": "Instagram",
                        "developer": "Instagram",
                        "appRating": 4.0,
                        "appRatingCount": 16253401,
                        "price": None,
                        "priceValue": 0,
                    },
                    {
                        "appId": "com.example.wallet",
                        "title": "Wallet Pro",
                        "developer": "Acme Inc",
                        "appRating": 4.7,
                        "appRatingCount": 1234,
                        "price": "$2.99",
                        "priceValue": 2.99,
                    },
                ]
            }
        }
    }
    import json

    blob = json.dumps(payload)
    return (
        '<html><head><script id="__NEXT_DATA__" type="application/json">'
        f"{blob}</script></head><body>search page</body></html>"
    )


def _play_details_html() -> str:
    payload = {
        "props": {
            "pageProps": {
                "appId": "com.instagram.android",
                "title": "Instagram",
                "developer": "Instagram",
                "appRating": 4.0,
                "appRatingCount": 16253401,
                "appReviews": 16253401,
                "price": None,
                "priceValue": 0,
                "appInstalls": "1,000,000,000+",
                "appVersion": "330.0.0",
                "appSize": "58M",
                "updated": "August 12, 2026",
                "appDescription": "Share moments with friends.",
                "containsAds": False,
            }
        }
    }
    import json

    blob = json.dumps(payload)
    return (
        '<html><head><script id="__NEXT_DATA__" type="application/json">'
        f"{blob}</script></head><body>details page</body></html>"
    )


def _play_reviews_body() -> str:
    import json

    rows = [
        [
            "rev1",
            "PlayUser42",
            "",
            "August 15, 2026",
            1755273600000,
            "Works great",
            None,
            ["5"],
            None,
            None,
            None,
            "330.0.0",
            "3300000",
            12,
        ],
        [
            "rev2",
            "Skeptic",
            "",
            "August 14, 2026",
            1755187200000,
            "Crashes on login",
            None,
            ["2"],
            None,
            None,
            None,
            "330.0.0",
            "3300000",
            3,
        ],
    ]
    return ")]}'\n" + json.dumps([None, [[None, [[rows]]]]])


# ── apple: iTunes Search API ───────────────────────────────────────────


@respx.mock
async def test_apple_search_maps_results() -> None:
    respx.get(url__startswith=_APPLE_SEARCH).mock(
        return_value=httpx.Response(200, json=_apple_search_payload())
    )
    result = await apple.search_apps("facebook", limit=5)
    assert len(result) == 2
    first = result[0]
    assert first["app_id"] == 284882215
    assert first["title"] == "Facebook"
    assert first["developer"] == "Meta"
    assert first["genre"] == "Social Networking"
    assert first["rating"] == 4.3
    assert first["rating_count"] == 20568113
    assert first["price"] == "Free"
    assert first["version"] == "472.0"
    assert first["url"].startswith("https://apps.apple.com/")


async def test_apple_search_blank_query_returns_empty() -> None:
    assert await apple.search_apps("") == []
    assert await apple.search_apps("   ") == []


@respx.mock
async def test_apple_search_http_error_returns_empty() -> None:
    respx.get(url__startswith=_APPLE_SEARCH).mock(return_value=httpx.Response(500, text="boom"))
    assert await apple.search_apps("facebook") == []


@respx.mock
async def test_apple_search_malformed_payload_returns_empty() -> None:
    respx.get(url__startswith=_APPLE_SEARCH).mock(
        return_value=httpx.Response(200, json={"nope": True})
    )
    assert await apple.search_apps("facebook") == []


@respx.mock
async def test_apple_details_maps_record() -> None:
    respx.get(url__startswith=_APPLE_LOOKUP).mock(
        return_value=httpx.Response(200, json=_apple_lookup_payload())
    )
    result = await apple.get_app_details(284882215)
    assert result["app_id"] == 284882215
    assert result["description"] == "Connect with friends and the world."
    assert result["seller_name"] == "Meta Platforms, Inc."
    assert result["min_os"] == "16.0"
    assert result["size_bytes"] == 123456789
    assert result["screenshots"] == ["https://is1-ssl.mzstatic.com/image/1.png"]
    assert result["currency"] == "USD"


@respx.mock
async def test_apple_details_unknown_id_returns_empty() -> None:
    respx.get(url__startswith=_APPLE_LOOKUP).mock(
        return_value=httpx.Response(200, json={"resultCount": 0, "results": []})
    )
    assert await apple.get_app_details(999999999) == {}


@respx.mock
async def test_apple_reviews_maps_entries() -> None:
    respx.get(url__startswith=_APPLE_RSS).mock(
        return_value=httpx.Response(200, json=_apple_rss_payload())
    )
    result = await apple.get_reviews(284882215, limit=10)
    assert len(result) == 2
    first = result[0]
    assert first["author"] == "AppUser99"
    assert first["rating"] == 5.0
    assert first["title"] == "Love it"
    assert first["body"] == "The best app"
    assert first["date"] == "2026-08-15T12:00:00-07:00"
    assert first["version"] == "472.0"
    assert result[1]["rating"] == 2.0


@respx.mock
async def test_apple_reviews_single_entry_feed() -> None:
    single = {"feed": {"entry": _apple_rss_payload()["feed"]["entry"][0]}}
    respx.get(url__startswith=_APPLE_RSS).mock(return_value=httpx.Response(200, json=single))
    result = await apple.get_reviews(284882215, limit=10)
    assert len(result) == 1
    assert result[0]["author"] == "AppUser99"


@respx.mock
async def test_apple_reviews_http_error_returns_empty() -> None:
    respx.get(url__startswith=_APPLE_RSS).mock(return_value=httpx.Response(403, text="nope"))
    assert await apple.get_reviews(284882215) == []


# ── google_play: store-page scraping ───────────────────────────────────


@respx.mock
async def test_play_search_maps_next_data() -> None:
    respx.get(url__startswith=_PLAY_SEARCH).mock(
        return_value=httpx.Response(200, text=_play_search_html())
    )
    result = await google_play.search_apps("instagram", limit=10)
    assert len(result) == 2
    first = result[0]
    assert first["package"] == "com.instagram.android"
    assert first["title"] == "Instagram"
    assert first["developer"] == "Instagram"
    assert first["rating"] == 4.0
    assert first["rating_count"] == 16253401
    assert first["price"] == ""
    assert first["url"].startswith("https://play.google.com/store/apps/details?id=")
    paid = result[1]
    assert paid["package"] == "com.example.wallet"
    assert paid["price"] == "$2.99"


@respx.mock
async def test_play_search_anti_bot_403_returns_empty_and_flags() -> None:
    respx.get(url__startswith=_PLAY_SEARCH).mock(
        return_value=httpx.Response(403, text="<html>Enable JavaScript and cookies</html>")
    )
    result = await google_play.search_apps("instagram")
    assert result == []
    assert google_play.last_anti_bot is True


@respx.mock
async def test_play_search_captcha_markers_return_empty_and_flag() -> None:
    respx.get(url__startswith=_PLAY_SEARCH).mock(
        return_value=httpx.Response(
            200, text="<html>Please verify you are human to continue (recaptcha)</html>"
        )
    )
    result = await google_play.search_apps("instagram")
    assert result == []
    assert google_play.last_anti_bot is True


@respx.mock
async def test_play_search_malformed_html_returns_empty() -> None:
    respx.get(url__startswith=_PLAY_SEARCH).mock(
        return_value=httpx.Response(200, text="<html><body>no embedded json</body></html>")
    )
    assert await google_play.search_apps("instagram") == []
    assert google_play.last_anti_bot is False


@respx.mock
async def test_play_details_maps_next_data() -> None:
    respx.get(url__startswith=_PLAY_DETAILS).mock(
        return_value=httpx.Response(200, text=_play_details_html())
    )
    result = await google_play.get_app_details("com.instagram.android")
    assert result["package"] == "com.instagram.android"
    assert result["title"] == "Instagram"
    assert result["rating"] == 4.0
    assert result["installs"] == "1,000,000,000+"
    assert result["version"] == "330.0.0"
    assert result["size"] == "58M"
    assert result["description"] == "Share moments with friends."
    assert result["contains_ads"] is False


@respx.mock
async def test_play_details_unknown_returns_empty() -> None:
    respx.get(url__startswith=_PLAY_DETAILS).mock(
        return_value=httpx.Response(200, text="<html><body>Not Found</body></html>")
    )
    assert await google_play.get_app_details("com.does.not.exist") == {}


@respx.mock
async def test_play_reviews_maps_rows() -> None:
    respx.post(url__startswith=_PLAY_REVIEWS).mock(
        return_value=httpx.Response(200, text=_play_reviews_body())
    )
    result = await google_play.get_reviews("com.instagram.android", limit=10)
    assert len(result) == 2
    first = result[0]
    assert first["author"] == "PlayUser42"
    assert first["rating"] == 5.0
    assert first["body"] == "Works great"
    assert first["date"] == "August 15, 2026"
    assert first["version"] == "330.0.0"
    assert result[1]["rating"] == 2.0


@respx.mock
async def test_play_reviews_malformed_body_returns_empty() -> None:
    respx.post(url__startswith=_PLAY_REVIEWS).mock(
        return_value=httpx.Response(200, text=")]}'\nnot json at all")
    )
    assert await google_play.get_reviews("com.instagram.android") == []


@respx.mock
async def test_play_reviews_anti_bot_returns_empty() -> None:
    respx.post(url__startswith=_PLAY_REVIEWS).mock(
        return_value=httpx.Response(200, text="<html>unusual traffic detected</html>")
    )
    assert await google_play.get_reviews("com.instagram.android") == []
    assert google_play.last_anti_bot is True


# ── routers ────────────────────────────────────────────────────────────


@pytest.fixture
def appstore_app() -> FastAPI:
    app = FastAPI()

    @app.exception_handler(PryError)
    async def pry_error_handler(request: Request, exc: PryError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": str(exc)})

    app.include_router(appstore_router)
    return app


def _client(app: FastAPI) -> TestClient:
    return TestClient(app)


def test_appstore_router_search_success(
    appstore_app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_apple(query: str, limit: int = 20) -> list[dict[str, Any]]:
        return [{"app_id": 284882215, "title": query, "developer": "Meta", "rating": 4.3}]

    async def fake_play(query: str, limit: int = 20) -> list[dict[str, Any]]:
        return [
            {
                "package": "com.example." + query,
                "title": query,
                "developer": "Acme",
                "rating": 4.0,
            }
        ]

    monkeypatch.setattr(apple, "search_apps", fake_apple)
    monkeypatch.setattr(google_play, "search_apps", fake_play)
    resp = _client(appstore_app).get("/v1/appstore/search", params={"query": "wallet", "limit": 5})
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["query"] == "wallet"
    assert body["store"] == "auto"
    assert len(body["data"]) == 2
    assert body["data"][0]["store"] == "apple"
    assert body["data"][1]["store"] == "play"


def test_appstore_router_search_store_filter(
    appstore_app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_apple(query: str, limit: int = 20) -> list[dict[str, Any]]:
        return [{"app_id": 1, "title": query}]

    monkeypatch.setattr(apple, "search_apps", fake_apple)
    resp = _client(appstore_app).get(
        "/v1/appstore/search", params={"query": "wallet", "store": "apple"}
    )
    assert resp.status_code == 200
    assert len(resp.json()["data"]) == 1


def test_appstore_router_apple_details_success(
    appstore_app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake(app_id: int | str) -> dict[str, Any]:
        return {"app_id": int(app_id), "title": "Facebook", "rating": 4.3}

    monkeypatch.setattr(apple, "get_app_details", fake)
    resp = _client(appstore_app).get("/v1/appstore/apple/284882215")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["app_id"] == "284882215"
    assert body["data"]["title"] == "Facebook"


def test_appstore_router_apple_reviews_success(
    appstore_app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake(app_id: int | str, limit: int = 50) -> list[dict[str, Any]]:
        return [{"author": "AppUser99", "rating": 5, "body": "Great"}]

    monkeypatch.setattr(apple, "get_reviews", fake)
    resp = _client(appstore_app).get("/v1/appstore/apple/284882215/reviews", params={"limit": 5})
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["limit"] == 5
    assert body["data"][0]["author"] == "AppUser99"


def test_appstore_router_play_details_success(
    appstore_app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake(package: str) -> dict[str, Any]:
        return {"package": package, "title": "Instagram", "rating": 4.0}

    monkeypatch.setattr(google_play, "get_app_details", fake)
    resp = _client(appstore_app).get("/v1/appstore/play/com.instagram.android")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["package"] == "com.instagram.android"
    assert body["data"]["title"] == "Instagram"


def test_appstore_router_502_when_modules_absent(
    appstore_app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(appstore_router_mod, "_appstore_module", lambda name: None)
    assert (
        _client(appstore_app).get("/v1/appstore/search", params={"query": "wallet"}).status_code
        == 502
    )
    assert _client(appstore_app).get("/v1/appstore/apple/284882215").status_code == 502
    assert _client(appstore_app).get("/v1/appstore/apple/284882215/reviews").status_code == 502
    assert _client(appstore_app).get("/v1/appstore/play/com.instagram.android").status_code == 502


def test_appstore_router_validation(appstore_app: FastAPI) -> None:
    assert _client(appstore_app).get("/v1/appstore/search").status_code == 422
    assert _client(appstore_app).get("/v1/appstore/apple/not-a-number").status_code == 400
    assert _client(appstore_app).get("/v1/appstore/play/nodots").status_code == 400
