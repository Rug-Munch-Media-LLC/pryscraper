# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for the sportsbook registry + generic odds scraper.

Covers ``sports_data.books``: registry integrity (unique ids, valid
categories/methods, ~110 books), generic extraction from fixture HTML/JSON
(``__NEXT_DATA__``, ``__NUXT__``, ``__INITIAL_STATE__``, plain HTML tables,
internal JSON feeds), price normalization (American/fractional/decimal), and
``get_all_books_odds`` degradation (one book down never blanks the result,
never raises).

All HTTP is mocked with respx — no live network. The UltimateScraper
escalation path is monkeypatched away so browser tiers can never launch.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
import respx

import sports_data
import sports_data.books as books

_DK_URL = "https://sportsbook.draftkings.com/leagues/nba"
_BETMGM_URL = "https://sports.betmgm.com/sports/nba"
_LOWVIG_URL = "https://lowvig.ag/sports/nba"
_BETONLINE_URL = "https://www.betonline.ag/sportsbook/nba"
_BOVADA_URL = "https://www.bovada.lv/services/sports/event/v2/events/A/description/basketball"
_FANDUEL_URL = "https://sportsbook.fanduel.com/sports/nba"
_PINNACLE_URL = "https://www.pinnacle.com/nba/odds"

_SCHEMA_FIELDS = {
    "sport",
    "event",
    "market",
    "book",
    "book_id",
    "home",
    "away",
    "home_odds",
    "away_odds",
    "draw_odds",
    "spread",
    "total",
    "last_update",
    "source",
}


@pytest.fixture(autouse=True)
def _hermetic_books(monkeypatch: pytest.MonkeyPatch) -> None:
    """Kill browser escalation + proxy secret lookups (tests are offline)."""

    async def _no_ultimate(url: str, *, browser: bool, geo_required: bool) -> str | None:
        return None

    monkeypatch.setattr(books, "_scrape_with_ultimate", _no_ultimate)
    monkeypatch.delenv("WEBSHARE_PROXY_LIST", raising=False)
    monkeypatch.setenv("PRY_SECRET_BACKEND", "env")


def _assert_schema(record: dict[str, Any]) -> None:
    assert set(record) == _SCHEMA_FIELDS
    assert record["book_id"]
    assert record["book"]
    assert record["sport"]
    assert record["market"] in ("h2h", "spreads", "totals")
    assert record["home"]
    assert record["away"]
    assert record["source"].startswith("books:")
    assert record["last_update"]


# ── Fixture payloads ─────────────────────────────────────────────────────


def _next_data_html() -> str:
    payload = {
        "props": {
            "pageProps": {
                "events": [
                    {
                        "home": "Los Angeles Lakers",
                        "away": "Boston Celtics",
                        "homeOdds": -110,
                        "awayOdds": -110,
                    }
                ]
            }
        }
    }
    return (
        f"<html><body><script>window.__NEXT_DATA__ = {json.dumps(payload)}</script></body></html>"
    )


def _init_state_html() -> str:
    state = {
        "sportsbook": {
            "events": [
                {
                    "event": "Lakers @ Celtics",
                    "markets": [
                        {
                            "key": "h2h",
                            "outcomes": [
                                {"name": "Los Angeles Lakers", "price": 1.85},
                                {"name": "Boston Celtics", "price": 2.10},
                            ],
                        }
                    ],
                }
            ]
        }
    }
    return f"<html><script>window.__INITIAL_STATE__ = {json.dumps(state)}</script></html>"


def _nuxt_html() -> str:
    state = {
        "data": [
            {
                "home": "Miami Heat",
                "away": "New York Knicks",
                "homeOdds": "-110",
                "awayOdds": "+110",
            }
        ]
    }
    return f"<html><script>window.__NUXT__ = {json.dumps(state)}</script></html>"


def _table_html() -> str:
    return """<html><body><table><tbody>
<tr><td>Miami Heat</td><td>New York Knicks</td><td>1.85</td><td>2.10</td></tr>
</tbody></table></body></html>"""


def _bovada_json() -> str:
    payload = [
        {
            "id": "evt-1",
            "description": "Lakers @ Celtics",
            "competitors": [
                {"name": "Los Angeles Lakers", "home": True},
                {"name": "Boston Celtics", "home": False},
            ],
            "displayGroups": [
                {
                    "markets": [
                        {
                            "key": "h2h",
                            "outcomes": [
                                {"name": "Los Angeles Lakers", "price": {"american": "-110"}},
                                {"name": "Boston Celtics", "price": {"american": "+100"}},
                            ],
                        },
                        {
                            "key": "spread",
                            "outcomes": [
                                {
                                    "name": "Los Angeles Lakers",
                                    "line": -4.5,
                                    "price": {"american": "-110"},
                                },
                                {
                                    "name": "Boston Celtics",
                                    "line": 4.5,
                                    "price": {"american": "-110"},
                                },
                            ],
                        },
                    ]
                }
            ],
        }
    ]
    return json.dumps(payload)


def _record(book_id: str, book_name: str) -> dict[str, Any]:
    return {
        "sport": "nba",
        "event": "Lakers @ Celtics",
        "market": "h2h",
        "book": book_name,
        "book_id": book_id,
        "home": "Los Angeles Lakers",
        "away": "Boston Celtics",
        "home_odds": 1.9,
        "away_odds": 2.0,
        "draw_odds": None,
        "spread": None,
        "total": None,
        "last_update": "2026-08-16T12:00:00Z",
        "source": f"books:{book_id}",
    }


# ── Registry integrity ───────────────────────────────────────────────────


def test_registry_is_large_enough() -> None:
    assert len(books.BOOKS) >= 100, f"expected 100+ books, got {len(books.BOOKS)}"


def test_registry_ids_and_names_unique() -> None:
    ids = [b["id"] for b in books.BOOKS.values()]
    names = [b["name"] for b in books.BOOKS.values()]
    assert len(ids) == len(set(ids))
    assert len(names) == len(set(names))


def test_registry_entry_fields_and_vocabularies() -> None:
    for book_id, book in books.BOOKS.items():
        assert book["id"] == book_id
        for field in (
            "name",
            "category",
            "region",
            "odds_url_template",
            "method",
            "confidence",
            "geo_required",
            "notes",
        ):
            assert field in book, f"{book_id} missing field {field}"
        assert book["category"] in books.CATEGORIES, f"{book_id} bad category"
        assert book["method"] in books.METHODS, f"{book_id} bad method"
        assert 0 <= book["confidence"] <= 1, f"{book_id} bad confidence"
        assert isinstance(book["geo_required"], bool), f"{book_id} geo_required not bool"
        assert book["odds_url_template"].startswith("https://"), f"{book_id} bad template"


def test_registry_validate_returns_empty() -> None:
    assert books.validate_registry() == []


def test_registry_covers_every_category_and_method() -> None:
    for category in books.CATEGORIES:
        assert any(b["category"] == category for b in books.BOOKS.values()), f"no {category} book"
    for method in books.METHODS:
        assert any(b["method"] == method for b in books.BOOKS.values()), f"no {method} book"


def test_registry_has_real_anchor_books() -> None:
    for book_id in (
        "draftkings",
        "fanduel",
        "betmgm",
        "caesars",
        "bovada",
        "betonline",
        "pinnacle",
        "william-hill",
        "unibet",
        "sbobet",
        "dafabet",
        "1xbet",
    ):
        assert book_id in books.BOOKS, f"missing anchor book {book_id}"


def test_books_coverage_counts() -> None:
    coverage = books.books_coverage()
    assert coverage["total"] == len(books.BOOKS)
    assert sum(coverage["by_category"].values()) == coverage["total"]
    assert sum(coverage["by_method"].values()) == coverage["total"]
    assert coverage["geo_required"]["true"] + coverage["geo_required"]["false"] == coverage["total"]
    assert set(coverage["categories"]) == set(books.CATEGORIES)
    assert set(coverage["methods"]) == set(books.METHODS)


def test_package_reexports_books_api() -> None:
    assert callable(sports_data.scrape_book_odds)
    assert callable(sports_data.get_all_books_odds)
    assert callable(sports_data.books_coverage)


# ── Price normalization ──────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("-110", 1.91),
        ("+120", 2.2),
        ("100", 2.0),
        ("5/2", 3.5),
        ("11/10", 2.1),
        (1.85, 1.85),
        (2.10, 2.1),
        (110, 2.1),
        ("1.91", 1.91),
        ("abc", None),
        ("", None),
        (None, None),
        (True, None),
    ],
)
def test_decimal_odds(raw: Any, expected: float | None) -> None:
    assert books._decimal_odds(raw) == expected


def test_render_url() -> None:
    template = "https://www.pinnacle.com/{sport}/odds"
    assert books._render_url(template, "NBA") == "https://www.pinnacle.com/nba/odds"
    assert (
        books._render_url(template, "basketball_nba")
        == "https://www.pinnacle.com/basketball_nba/odds"
    )
    assert (
        books._render_url("https://example.com/no-placeholder", "nba")
        == "https://example.com/no-placeholder"
    )


# ── Generic extraction (mocked HTTP — no live network) ──────────────────


async def test_scrape_next_data() -> None:
    with respx.mock:
        respx.get(_DK_URL).mock(return_value=httpx.Response(200, text=_next_data_html()))
        result = await books.scrape_book_odds("draftkings", "nba")
    assert len(result) == 1
    record = result[0]
    _assert_schema(record)
    assert record["book_id"] == "draftkings"
    assert record["home"] == "Los Angeles Lakers"
    assert record["away"] == "Boston Celtics"
    assert record["home_odds"] == 1.91
    assert record["away_odds"] == 1.91


async def test_scrape_init_state() -> None:
    with respx.mock:
        respx.get(_BETMGM_URL).mock(return_value=httpx.Response(200, text=_init_state_html()))
        result = await books.scrape_book_odds("betmgm", "nba")
    assert len(result) == 1
    record = result[0]
    _assert_schema(record)
    assert record["book_id"] == "betmgm"
    assert record["home"] == "Los Angeles Lakers"
    assert record["away"] == "Boston Celtics"
    assert record["home_odds"] == 1.85
    assert record["away_odds"] == 2.1
    assert record["draw_odds"] is None


async def test_scrape_nuxt() -> None:
    with respx.mock:
        respx.get(_LOWVIG_URL).mock(return_value=httpx.Response(200, text=_nuxt_html()))
        result = await books.scrape_book_odds("lowvig", "nba")
    assert len(result) == 1
    record = result[0]
    _assert_schema(record)
    assert record["book_id"] == "lowvig"
    assert record["home"] == "Miami Heat"
    assert record["away"] == "New York Knicks"
    assert record["home_odds"] == 1.91
    assert record["away_odds"] == 2.1


async def test_scrape_html_table() -> None:
    with respx.mock:
        respx.get(_BETONLINE_URL).mock(return_value=httpx.Response(200, text=_table_html()))
        result = await books.scrape_book_odds("betonline", "nba")
    assert len(result) == 1
    record = result[0]
    _assert_schema(record)
    assert record["book_id"] == "betonline"
    assert record["home"] == "Miami Heat"
    assert record["away"] == "New York Knicks"
    assert record["home_odds"] == 1.85
    assert record["away_odds"] == 2.1


async def test_scrape_json_feed_h2h() -> None:
    with respx.mock:
        respx.get(_BOVADA_URL).mock(return_value=httpx.Response(200, text=_bovada_json()))
        result = await books.scrape_book_odds("bovada", "basketball")
    assert len(result) == 1
    record = result[0]
    _assert_schema(record)
    assert record["book_id"] == "bovada"
    assert record["market"] == "h2h"
    assert record["home"] == "Los Angeles Lakers"
    assert record["away"] == "Boston Celtics"
    assert record["home_odds"] == 1.91
    assert record["away_odds"] == 2.0


async def test_scrape_json_feed_spreads() -> None:
    with respx.mock:
        respx.get(_BOVADA_URL).mock(return_value=httpx.Response(200, text=_bovada_json()))
        result = await books.scrape_book_odds("bovada", "basketball", market="spreads")
    assert len(result) == 1
    record = result[0]
    _assert_schema(record)
    assert record["market"] == "spreads"
    assert record["spread"] == -4.5
    assert record["home_odds"] == 1.91
    assert record["away_odds"] == 1.91


async def test_scrape_limit_respected() -> None:
    events = {
        "props": {
            "pageProps": {
                "events": [
                    {
                        "home": f"Team {i} A",
                        "away": f"Team {i} B",
                        "homeOdds": -110,
                        "awayOdds": -110,
                    }
                    for i in range(5)
                ]
            }
        }
    }
    html = f"<html><script>window.__NEXT_DATA__ = {json.dumps(events)}</script></html>"
    with respx.mock:
        respx.get(_DK_URL).mock(return_value=httpx.Response(200, text=html))
        result = await books.scrape_book_odds("draftkings", "nba", limit=2)
    assert len(result) == 2


# ── Degradation / never-raise ────────────────────────────────────────────


async def test_scrape_unknown_book_returns_empty() -> None:
    assert await books.scrape_book_odds("not-a-real-book", "nba") == []


async def test_scrape_fetch_failure_returns_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _no_fetch(url: str, proxy: str | None = None) -> str | None:
        return None

    monkeypatch.setattr(books, "_plain_fetch", _no_fetch)
    assert await books.scrape_book_odds("draftkings", "nba") == []


async def test_scrape_blocked_page_returns_empty() -> None:
    blocked = "<html><body>cloudflare just a moment, checking your browser...</body></html>"
    with respx.mock:
        respx.get(_DK_URL).mock(return_value=httpx.Response(200, text=blocked))
        result = await books.scrape_book_odds("draftkings", "nba")
    assert result == []


async def test_get_all_books_odds_one_down_not_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_scrape(
        book_id: str, sport: str, market: str = "h2h", limit: int = 20
    ) -> list[dict[str, Any]]:
        if book_id == "draftkings":
            raise RuntimeError("boom")
        if book_id == "fanduel":
            return [_record("fanduel", "FanDuel")]
        return []

    monkeypatch.setattr(books, "scrape_book_odds", fake_scrape)
    result = await books.get_all_books_odds("nba", limit=100)
    assert result
    assert all(r["book_id"] == "fanduel" for r in result)


async def test_get_all_books_odds_all_down_returns_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_scrape(
        book_id: str, sport: str, market: str = "h2h", limit: int = 20
    ) -> list[dict[str, Any]]:
        raise RuntimeError("boom")

    monkeypatch.setattr(books, "scrape_book_odds", fake_scrape)
    assert await books.get_all_books_odds("nba") == []


async def test_get_all_books_odds_real_fetch_degradation(monkeypatch: pytest.MonkeyPatch) -> None:
    """One reachable book + one blocked book via the actual fetch pipeline."""
    monkeypatch.setattr(
        books,
        "BOOKS",
        {
            "fanduel": books.BOOKS["fanduel"],
            "pinnacle": books.BOOKS["pinnacle"],
        },
    )
    blocked = "<html><body>access denied, captcha challenge...</body></html>"
    with respx.mock:
        respx.get(_FANDUEL_URL).mock(return_value=httpx.Response(200, text=_next_data_html()))
        respx.get(_PINNACLE_URL).mock(return_value=httpx.Response(200, text=blocked))
        result = await books.get_all_books_odds("nba")
    assert result
    assert all(r["book_id"] == "fanduel" for r in result)
