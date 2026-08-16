# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for the local_data package (Google Maps / Yelp) and its router.

The local-data section mocks every HTTP response with respx — no live
network. It covers normalization into the shared record schema, empty-on-
failure, anti-bot/robots handling, the never-raise contract, and the
router's lazy-import / 502 degradation.
"""

import importlib
import json
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
import respx

import client as _client_module
import local_data as _local_data_pkg
import local_data.places as _places
import local_data.reviews as _reviews
import routers.local_data as _router_module
from errors import PryError

# ── URLs under test ─────────────────────────────────────────────────────
GOOGLE_SEARCH_URL_RE = r"https://www\.google\.com/maps/search/.*"
GOOGLE_CID_URL = "https://www.google.com/maps?cid=1234567890"
GOOGLE_ROBOTS_URL = "https://www.google.com/robots.txt"
YELP_PAGE_0 = "https://www.yelp.com/biz/taco-stand?sort_by=date_desc"
YELP_PAGE_1 = "https://www.yelp.com/biz/taco-stand?sort_by=date_desc&start=10"
YELP_ROBOTS_URL = "https://www.yelp.com/robots.txt"

PLACE_KEYS = {
    "place_id",
    "name",
    "address",
    "phone",
    "rating",
    "review_count",
    "category",
    "website",
    "hours",
}
REVIEW_KEYS = {"author", "rating", "text", "date", "source"}


@pytest.fixture(autouse=True)
def _hermetic_local_data(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Make local-data tests hermetic: no robots fetch, no caches, no clients."""
    monkeypatch.setenv("PRY_LOCAL_RESPECT_ROBOTS", "0")
    monkeypatch.delenv("PRY_LOCAL_YELP_MAX_PAGES", raising=False)
    _client_module.http_client = None
    _places._clear_cache()
    _reviews._clear_cache()
    yield
    _client_module.http_client = None
    _places._clear_cache()
    _reviews._clear_cache()


# ── Fixture HTML / JSON builders ────────────────────────────────────────


def _gmaps_search_html() -> str:
    return """<!DOCTYPE html><html><head>
<script type="application/ld+json">
[{
  "@type": ["Restaurant", "LocalBusiness"],
  "name": "Taco Stand",
  "address": {"streetAddress": "123 Main St", "addressLocality": "Springfield", "addressRegion": "IL", "postalCode": "62701"},
  "telephone": "+1-555-0100",
  "aggregateRating": {"ratingValue": 4.6, "reviewCount": "231 reviews"},
  "openingHoursSpecification": [{"dayOfWeek": ["Monday", "Tuesday"], "opens": "08:00", "closes": "15:00"}],
  "url": "https://www.google.com/maps?cid=1234567890",
  "sameAs": "https://tacostand.example.com"
}]
</script>
<script>window.APP_INITIALIZATION_STATE = [[["Pizza Palace","456 Oak Ave, Springfield",null,null,"+1-555-0199",null,null,null,null,[4.1,87],null,null,null,"Pizza","https://pizzapalace.example.com"]]];</script>
</head><body></body></html>"""


def _gmaps_place_html() -> str:
    popular = ",".join(
        f"[{d},[{','.join(str((i * 7 + d) % 100) for i in range(24))}]]" for d in range(7)
    )
    return f"""<!DOCTYPE html><html><head>
<script type="application/ld+json">
{{"@type": "Restaurant", "name": "Taco Stand",
  "address": {{"streetAddress": "123 Main St", "addressLocality": "Springfield"}},
  "aggregateRating": {{"ratingValue": 4.6, "reviewCount": 231}},
  "url": "https://www.google.com/maps?cid=1234567890"}}
</script>
<script>window.APP_INITIALIZATION_STATE = [[["Taco Stand","123 Main St, Springfield"], [{popular}]]];</script>
</head><body></body></html>"""


def _gmaps_reviews_blob_html() -> str:
    return """<!DOCTYPE html><html><head>
<script>window.APP_INITIALIZATION_STATE = [[
  ["Taco Stand","123 Main St, Springfield"],
  [
    ["Alice Johnson","https://maps.google.com/maps/contrib/111","https://lh3.googleusercontent.com/photo",5,"Best tacos in the city, super fresh ingredients and fast service. Highly recommend the al pastor.","2 months ago",12,null],
    ["Bob Kim","https://maps.google.com/maps/contrib/222","https://lh3.googleusercontent.com/photo",4,"Great spot, though it gets crowded at lunch. The salsa bar is fantastic and the staff is friendly.","3 months ago",4,null]
  ]
]];</script>
</head><body></body></html>"""


def _gmaps_reviews_ld_html() -> str:
    return """<!DOCTYPE html><html><head>
<script type="application/ld+json">
{"@type": "Restaurant", "name": "Taco Stand",
 "review": [
   {"@type": "Review", "author": {"@type": "Person", "name": "Carol M."}, "reviewRating": {"@type": "Rating", "ratingValue": 5}, "reviewBody": "Amazing al pastor and a great salsa bar. Definitely coming back.", "datePublished": "2026-05-01"},
   {"@type": "Review", "author": {"@type": "Person", "name": "Dan P."}, "reviewRating": {"@type": "Rating", "ratingValue": 3}, "reviewBody": "Decent tacos but the wait was long and the tables were sticky.", "datePublished": "2026-04-18"}
 ]}
</script>
</head><body></body></html>"""


def _yelp_json_html() -> str:
    payload = json.dumps(
        {
            "business": {"name": "Taco Stand", "rating": 4.5},
            "reviews": [
                {
                    "id": "r1",
                    "rating": 5,
                    "text": "Best tacos in town! Great salsa bar and fast service.",
                    "time_created": "2024-03-15 10:00:00",
                    "user": {"name": "Alice J."},
                },
                {
                    "id": "r2",
                    "rating": 4,
                    "text": "Good but busy on weekends, order ahead to skip the line.",
                    "time_created": "2024-02-01 09:00:00",
                    "user": {"name": "Bob K."},
                },
            ],
            "reviewFeed": [
                {
                    "id": "r3",
                    "rating": 5,
                    "text": "Came back again, still the best al pastor in town.",
                    "time_created": "2023-12-01 08:00:00",
                    "user": {"name": "Carol M."},
                }
            ],
        }
    )
    return (
        '<html><body><script type="application/json" '
        f'data-hydrated-app-id="yelp-biz-page">{payload}</script></body></html>'
    )


def _yelp_html_cards() -> str:
    return """<html><body>
<div class="review" aria-label="review by Alice J.">
  <div class="user-passport-stats"><div class="user-display-name">Alice J.</div></div>
  <div class="i-stars" title="5.0 star rating"></div>
  <div class="review-content"><p lang="en">Amazing tacos, great salsa bar, friendly staff!</p></div>
  <meta itemprop="datePublished" content="2024-03-15">
</div>
<div class="review" aria-label="review by Bob K.">
  <div class="user-passport-stats"><div class="user-display-name">Bob K.</div></div>
  <div class="i-stars" title="4.0 star rating"></div>
  <div class="review-content"><p lang="en">Solid food but the line was long on Saturday.</p></div>
  <meta itemprop="datePublished" content="2024-01-20">
</div>
</body></html>"""


# ── Package surface ─────────────────────────────────────────────────────


def test_local_data_package_exports() -> None:
    assert set(_local_data_pkg.__all__) == {"get_place", "get_reviews", "search_places"}
    assert callable(_local_data_pkg.search_places)
    assert callable(_local_data_pkg.get_place)
    assert callable(_local_data_pkg.get_reviews)


def test_router_import_safe() -> None:
    mod = importlib.import_module("routers.local_data")
    assert mod.router is not None
    assert len(mod.router.routes) == 3


def test_router_routes_present() -> None:
    routes = {route.path: route.methods for route in _router_module.router.routes}
    assert routes["/v1/local/places/search"] == {"GET"}
    assert routes["/v1/local/places/{place_id}"] == {"GET"}
    assert routes["/v1/local/reviews/{place_id}"] == {"GET"}


# ── places.search_places ────────────────────────────────────────────────


async def test_search_places_normalization() -> None:
    async with respx.mock:
        respx.get(url__regex=GOOGLE_SEARCH_URL_RE).mock(
            return_value=httpx.Response(200, text=_gmaps_search_html())
        )
        results = await _places.search_places("taco", location="Austin TX")
    assert len(results) == 2
    first, second = results[0], results[1]
    assert set(first) == PLACE_KEYS
    assert first["name"] == "Taco Stand"
    assert first["place_id"] == "1234567890"
    assert first["address"] == "123 Main St, Springfield, IL, 62701"
    assert first["phone"] == "+1-555-0100"
    assert first["rating"] == 4.6
    assert first["review_count"] == 231
    assert first["category"] == "Restaurant"
    assert first["website"] == "https://tacostand.example.com"
    assert first["hours"] == "Mon, Tue: 08:00-15:00"
    assert set(second) == PLACE_KEYS
    assert second["name"] == "Pizza Palace"
    assert second["phone"] == "+1-555-0199"
    assert second["rating"] == 4.1
    assert second["review_count"] == 87
    assert second["category"] == "Pizza"


async def test_search_places_limit() -> None:
    async with respx.mock:
        respx.get(url__regex=GOOGLE_SEARCH_URL_RE).mock(
            return_value=httpx.Response(200, text=_gmaps_search_html())
        )
        results = await _places.search_places("taco", location="Austin TX", limit=1)
    assert len(results) == 1
    assert results[0]["name"] == "Taco Stand"


async def test_search_places_empty_query() -> None:
    assert await _places.search_places("") == []
    async with respx.mock:
        respx.get(url__regex=GOOGLE_SEARCH_URL_RE).mock(
            return_value=httpx.Response(200, text="<html><body></body></html>")
        )
        assert await _places.search_places("  ", location="x") == []


async def test_search_places_empty_page() -> None:
    async with respx.mock:
        respx.get(url__regex=GOOGLE_SEARCH_URL_RE).mock(
            return_value=httpx.Response(200, text="<html><body>nothing here</body></html>")
        )
        assert await _places.search_places("zzzz") == []


async def test_search_places_http_500() -> None:
    async with respx.mock:
        respx.get(url__regex=GOOGLE_SEARCH_URL_RE).mock(
            return_value=httpx.Response(500, text="boom")
        )
        assert await _places.search_places("taco") == []


async def test_search_places_transport_error() -> None:
    async with respx.mock:
        respx.get(url__regex=GOOGLE_SEARCH_URL_RE).mock(side_effect=httpx.ConnectError("boom"))
        assert await _places.search_places("taco") == []


async def test_search_places_anti_bot() -> None:
    async with respx.mock:
        respx.get(url__regex=GOOGLE_SEARCH_URL_RE).mock(
            return_value=httpx.Response(200, text="<html>unusual traffic detected, captcha</html>")
        )
        assert await _places.search_places("taco") == []


async def test_search_places_robots_disallow(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRY_LOCAL_RESPECT_ROBOTS", "1")
    async with respx.mock:
        respx.get(GOOGLE_ROBOTS_URL).mock(
            return_value=httpx.Response(200, text="User-agent: *\nDisallow: /maps\n")
        )
        search_route = respx.get(url__regex=GOOGLE_SEARCH_URL_RE).mock(
            return_value=httpx.Response(200, text=_gmaps_search_html())
        )
        assert await _places.search_places("taco") == []
        assert not search_route.called  # search page never fetched


# ── places.get_place ────────────────────────────────────────────────────


async def test_get_place_detail_with_popular_times() -> None:
    async with respx.mock:
        respx.get(GOOGLE_CID_URL).mock(return_value=httpx.Response(200, text=_gmaps_place_html()))
        result = await _places.get_place("1234567890")
    assert result["name"] == "Taco Stand"
    assert result["place_id"] == "1234567890"
    assert result["rating"] == 4.6
    assert result["source"] == "google"
    popular = result["popular_times"]
    assert len(popular) == 7
    assert popular[0]["day"] == "Sunday"
    assert popular[0]["day_index"] == 0
    assert len(popular[0]["hours"]) == 24


async def test_get_place_empty_id() -> None:
    assert await _places.get_place("") == {}
    assert await _places.get_place(None) == {}  # type: ignore[arg-type]


async def test_get_place_http_error() -> None:
    async with respx.mock:
        respx.get(GOOGLE_CID_URL).mock(return_value=httpx.Response(404, text="missing"))
        assert await _places.get_place("1234567890") == {}


async def test_get_place_transport_error() -> None:
    async with respx.mock:
        respx.get(GOOGLE_CID_URL).mock(side_effect=httpx.ConnectError("boom"))
        assert await _places.get_place("1234567890") == {}


# ── reviews.get_reviews — Google ─────────────────────────────────────────


async def test_get_reviews_google_blob() -> None:
    async with respx.mock:
        respx.get(GOOGLE_CID_URL).mock(
            return_value=httpx.Response(200, text=_gmaps_reviews_blob_html())
        )
        results = await _reviews.get_reviews("1234567890", source="google")
    assert len(results) == 2
    for rec in results:
        assert set(rec) == REVIEW_KEYS
        assert rec["source"] == "google"
    assert results[0]["author"] == "Alice Johnson"
    assert results[0]["rating"] == 5.0
    assert "al pastor" in results[0]["text"]
    assert results[0]["date"] == "2 months ago"
    assert results[1]["author"] == "Bob Kim"
    assert results[1]["rating"] == 4.0


async def test_get_reviews_google_jsonld() -> None:
    async with respx.mock:
        respx.get(GOOGLE_CID_URL).mock(
            return_value=httpx.Response(200, text=_gmaps_reviews_ld_html())
        )
        results = await _reviews.get_reviews("1234567890", source="google")
    assert len(results) == 2
    assert results[0]["author"] == "Carol M."
    assert results[0]["rating"] == 5.0
    assert results[0]["date"] == "2026-05-01"
    assert results[1]["author"] == "Dan P."
    assert results[1]["rating"] == 3.0


async def test_get_reviews_google_limit() -> None:
    async with respx.mock:
        respx.get(GOOGLE_CID_URL).mock(
            return_value=httpx.Response(200, text=_gmaps_reviews_blob_html())
        )
        results = await _reviews.get_reviews("1234567890", source="google", limit=1)
    assert len(results) == 1
    assert results[0]["author"] == "Alice Johnson"


async def test_get_reviews_google_anti_bot() -> None:
    async with respx.mock:
        respx.get(GOOGLE_CID_URL).mock(
            return_value=httpx.Response(200, text="<html>enable javascript to continue</html>")
        )
        assert await _reviews.get_reviews("1234567890", source="google") == []


async def test_get_reviews_google_http_error() -> None:
    async with respx.mock:
        respx.get(GOOGLE_CID_URL).mock(return_value=httpx.Response(503, text="down"))
        assert await _reviews.get_reviews("1234567890", source="google") == []


# ── reviews.get_reviews — Yelp ───────────────────────────────────────────


async def test_get_reviews_yelp_json() -> None:
    async with respx.mock:
        respx.get(YELP_PAGE_0).mock(return_value=httpx.Response(200, text=_yelp_json_html()))
        respx.get(YELP_PAGE_1).mock(
            return_value=httpx.Response(200, text="<html><body>no more reviews</body></html>")
        )
        results = await _reviews.get_reviews("taco-stand", source="yelp")
    assert len(results) == 3
    for rec in results:
        assert set(rec) == REVIEW_KEYS
        assert rec["source"] == "yelp"
    assert results[0]["author"] == "Alice J."
    assert results[0]["rating"] == 5.0
    assert results[0]["date"] == "2024-03-15"  # ISO datetime trimmed to date
    assert results[2]["author"] == "Carol M."


async def test_get_reviews_yelp_html_fallback() -> None:
    async with respx.mock:
        respx.get(YELP_PAGE_0).mock(return_value=httpx.Response(200, text=_yelp_html_cards()))
        respx.get(YELP_PAGE_1).mock(
            return_value=httpx.Response(200, text="<html><body>no more reviews</body></html>")
        )
        results = await _reviews.get_reviews("taco-stand", source="yelp")
    assert len(results) == 2
    assert results[0]["author"] == "Alice J."
    assert results[0]["rating"] == 5.0
    assert "salsa bar" in results[0]["text"]
    assert results[0]["date"] == "2024-03-15"
    assert results[1]["author"] == "Bob K."
    assert results[1]["rating"] == 4.0


async def test_get_reviews_yelp_pagination() -> None:
    async with respx.mock:
        page_0 = respx.get(YELP_PAGE_0).mock(
            return_value=httpx.Response(200, text=_yelp_json_html())
        )
        page_1 = respx.get(YELP_PAGE_1).mock(
            return_value=httpx.Response(200, text="<html><body>no more reviews</body></html>")
        )
        results = await _reviews.get_reviews("taco-stand", source="yelp", limit=20)
    assert len(results) == 3
    assert page_0.called
    assert page_1.called  # pagination swept to the next page before exhausting


async def test_get_reviews_yelp_limit() -> None:
    async with respx.mock:
        page_0 = respx.get(YELP_PAGE_0).mock(
            return_value=httpx.Response(200, text=_yelp_json_html())
        )
        page_1 = respx.get(YELP_PAGE_1).mock(
            return_value=httpx.Response(200, text=_yelp_json_html())
        )
        results = await _reviews.get_reviews("taco-stand", source="yelp", limit=2)
    assert len(results) == 2
    assert page_0.called
    assert not page_1.called  # limit reached on page 0


async def test_get_reviews_yelp_anti_bot() -> None:
    async with respx.mock:
        respx.get(YELP_PAGE_0).mock(
            return_value=httpx.Response(200, text="<html>are you a robot? captcha</html>")
        )
        assert await _reviews.get_reviews("taco-stand", source="yelp") == []


# ── reviews.get_reviews — validation & failure paths ─────────────────────


async def test_get_reviews_unknown_source() -> None:
    assert await _reviews.get_reviews("123", source="tripadvisor") == []
    assert await _reviews.get_reviews("123", source="") == []


async def test_get_reviews_empty_place_id() -> None:
    assert await _reviews.get_reviews("") == []
    assert await _reviews.get_reviews(None, source="yelp") == []  # type: ignore[arg-type]


async def test_get_reviews_transport_error() -> None:
    async with respx.mock:
        respx.get(GOOGLE_CID_URL).mock(side_effect=httpx.ConnectError("boom"))
        assert await _reviews.get_reviews("1234567890") == []


async def test_get_reviews_dedupe() -> None:
    # Same review (author + text) twice inside one blob → deduped.
    html_text = """<html><head>
    <script>window.APP_INITIALIZATION_STATE = [[
      ["Alice Johnson","u1","p1",5,"Truly outstanding food, fresh ingredients, quick service, fair prices. A neighborhood gem.","2 months ago"],
      ["Alice Johnson","u1","p1",5,"Truly outstanding food, fresh ingredients, quick service, fair prices. A neighborhood gem.","2 months ago"]
    ]];</script>
    </head><body></body></html>"""
    async with respx.mock:
        respx.get(GOOGLE_CID_URL).mock(return_value=httpx.Response(200, text=html_text))
        results = await _reviews.get_reviews("1234567890", source="google")
    assert len(results) == 1


# ── routers/local_data.py ────────────────────────────────────────────────


def _standalone_app() -> Any:
    """A minimal FastAPI app with only the local_data router + PryError handler."""
    from fastapi import FastAPI, Request
    from fastapi.responses import JSONResponse

    app = FastAPI()
    app.include_router(_router_module.router)

    @app.exception_handler(PryError)
    async def _pry_error_handler(request: Request, exc: PryError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": str(exc), "code": getattr(exc, "code", "error")},
        )

    return app


def _fake_module(**funcs: Any) -> Any:
    return SimpleNamespace(**funcs)


async def _fake_search(query: str, location: str = "", limit: int = 20) -> list[dict[str, Any]]:
    return [{"name": query, "location": location, "limit": limit}]


async def _fake_get_place(place_id: str) -> dict[str, Any]:
    return {"name": "Taco Stand", "place_id": place_id}


async def _fake_get_reviews(
    place_id: str, source: str = "google", limit: int = 20
) -> list[dict[str, Any]]:
    return [
        {
            "author": "Alice J.",
            "rating": 5.0,
            "text": "Great!",
            "date": "2024-03-15",
            "source": source,
        }
    ]


def test_router_places_search_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        _router_module,
        "_local_data_module",
        lambda name: _fake_module(search_places=_fake_search),
    )
    from fastapi.testclient import TestClient

    with TestClient(_standalone_app()) as c:
        resp = c.get("/v1/local/places/search", params={"query": "taco", "location": "Austin TX"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["data"][0]["name"] == "taco"
    assert body["query"] == "taco"
    assert body["location"] == "Austin TX"


def test_router_places_get_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        _router_module,
        "_local_data_module",
        lambda name: _fake_module(get_place=_fake_get_place),
    )
    from fastapi.testclient import TestClient

    with TestClient(_standalone_app()) as c:
        resp = c.get("/v1/local/places/1234567890")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["data"]["name"] == "Taco Stand"
    assert body["place_id"] == "1234567890"


def test_router_reviews_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        _router_module,
        "_local_data_module",
        lambda name: _fake_module(get_reviews=_fake_get_reviews),
    )
    from fastapi.testclient import TestClient

    with TestClient(_standalone_app()) as c:
        resp = c.get("/v1/local/reviews/taco-stand", params={"source": "yelp"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["data"][0]["source"] == "yelp"
    assert body["source"] == "yelp"


def test_router_reviews_bad_source_param(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        _router_module,
        "_local_data_module",
        lambda name: _fake_module(get_reviews=_fake_get_reviews),
    )
    from fastapi.testclient import TestClient

    with TestClient(_standalone_app()) as c:
        resp = c.get("/v1/local/reviews/taco-stand", params={"source": "tripadvisor"})
    assert resp.status_code == 422  # Query pattern rejects unknown source


def test_router_module_unavailable_502(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_router_module, "_local_data_module", lambda name: None)
    from fastapi.testclient import TestClient

    with TestClient(_standalone_app()) as c:
        resp = c.get("/v1/local/places/search", params={"query": "taco"})
    assert resp.status_code == 502
    assert "external_service_error" in resp.json()["code"]


def test_router_real_module_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    # End-to-end through the real import path: stub the module function only.
    monkeypatch.setattr(_places, "search_places", _fake_search)
    from fastapi.testclient import TestClient

    with TestClient(_standalone_app()) as c:
        resp = c.get("/v1/local/places/search", params={"query": "pizza", "limit": 5})
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["data"][0]["limit"] == 5
