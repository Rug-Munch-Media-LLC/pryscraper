# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for wiring the 112-book scrapers into the odds pipeline.

Covers the pieces that make the odds endpoint actually aggregate from all
112 books (not just The Odds API + 5 sources):

* ``sports_data.books`` — the 30s TTL cache around ``scrape_book_odds`` /
  ``get_all_books_odds`` (second call served from cache, ``clear_books_cache``
  resets) so 112-book polls don't re-scrape every call.
* ``sports_data.odds`` — ``sources="books"`` / ``sources="all"`` pulls the
  112-book records and merges them via ``sources.merge_odds`` with
  ``source="books"``; the default (no ``sources``) behavior is unchanged.
* Never-raise guarantees: a missing/raising books module degrades to
  ``[]`` and never blanks the other sources.

All HTTP and the scraper imports are mocked — no live network, no real
112-book scrape.
"""

from __future__ import annotations

import json
import sys
from typing import Any

import pytest

import datasets.sports_data as sports_data
import datasets.sports_data.books as books
import datasets.sports_data.odds as odds
import datasets.sports_data.sources as sources

_DK_URL = "https://sportsbook.draftkings.com/leagues/nba"
_ESPN_RECORD = {
    "sport": "nba",
    "event": "Lakers @ Celtics",
    "event_id": "eid123",
    "market": "h2h",
    "book": "espn",
    "home": "Los Angeles Lakers",
    "away": "Boston Celtics",
    "home_odds": 1.85,
    "away_odds": 2.10,
    "draw_odds": None,
    "spread": None,
    "total": None,
    "last_update": "2026-08-16T12:00:00Z",
    "source": "espn",
}


@pytest.fixture(autouse=True)
def _hermetic_pipeline(monkeypatch: pytest.MonkeyPatch) -> None:
    """Clear caches, kill browser escalation and proxy secrets (offline)."""

    async def _no_ultimate(url: str, *, browser: bool, geo_required: bool) -> str | None:
        return None

    books.clear_books_cache()
    odds._clear_cache()
    sources._clear_cache()
    monkeypatch.setattr(books, "_scrape_with_ultimate", _no_ultimate)
    monkeypatch.delenv("WEBSHARE_PROXY_LIST", raising=False)
    monkeypatch.delenv("PRY_ODDS_API_KEY", raising=False)
    monkeypatch.setenv("PRY_SECRET_BACKEND", "env")


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


def _book_record(
    book_id: str, book_name: str, *, sport: str = "nba", market: str = "h2h"
) -> dict[str, Any]:
    return {
        "sport": sport,
        "event": "Lakers @ Celtics",
        "market": market,
        "book": book_name,
        "book_id": book_id,
        "home": "Los Angeles Lakers",
        "away": "Boston Celtics",
        "home_odds": 1.91,
        "away_odds": 2.10,
        "draw_odds": None,
        "spread": None,
        "total": None,
        "last_update": "2026-08-16T12:00:00Z",
        "source": f"books:{book_id}",
    }


def _fake_espn(records: list[dict[str, Any]] | None = None) -> Any:
    async def fake_espn(
        espn: tuple[str, str] | None,
        sport_slug: str,
        markets: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        return records or [_ESPN_RECORD]

    return fake_espn


def _fake_books(calls: dict[str, int], records: list[dict[str, Any]] | None = None) -> Any:
    async def fake_books(sport: str, market: str = "h2h", limit: int = 100) -> list[dict[str, Any]]:
        calls["books"] += 1
        return records if records is not None else [_book_record("draftkings", "DraftKings")]

    return fake_books


# ── books: 30s TTL cache ─────────────────────────────────────────────────


async def test_scrape_book_odds_second_call_served_from_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = {"fetch": 0}

    async def fake_fetch(book: dict[str, Any], url: str) -> tuple[str | None, str]:
        calls["fetch"] += 1
        return _next_data_html(), "html"

    monkeypatch.setattr(books, "_fetch_payload", fake_fetch)
    first = await books.scrape_book_odds("draftkings", "nba")
    second = await books.scrape_book_odds("draftkings", "nba")
    assert first == second
    assert calls["fetch"] == 1, "second call must be served from the TTL cache"
    assert first
    assert first[0]["book_id"] == "draftkings"


async def test_scrape_book_odds_clear_books_cache_resets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = {"fetch": 0}

    async def fake_fetch(book: dict[str, Any], url: str) -> tuple[str | None, str]:
        calls["fetch"] += 1
        return _next_data_html(), "html"

    monkeypatch.setattr(books, "_fetch_payload", fake_fetch)
    await books.scrape_book_odds("draftkings", "nba")
    await books.scrape_book_odds("draftkings", "nba")
    assert calls["fetch"] == 1
    books.clear_books_cache()
    await books.scrape_book_odds("draftkings", "nba")
    assert calls["fetch"] == 2, "clear_books_cache() must reset the TTL cache"


async def test_get_all_books_odds_ttl_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        books,
        "BOOKS",
        {"fanduel": books.BOOKS["fanduel"], "pinnacle": books.BOOKS["pinnacle"]},
    )
    calls = {"fetch": 0}

    async def fake_fetch(book: dict[str, Any], url: str) -> tuple[str | None, str]:
        calls["fetch"] += 1
        return _next_data_html(), "html"

    monkeypatch.setattr(books, "_fetch_payload", fake_fetch)
    first = await books.get_all_books_odds("nba", limit=10)
    second = await books.get_all_books_odds("nba", limit=10)
    assert first
    assert second
    assert calls["fetch"] == 2, "two books fetched once total across both polls"
    books.clear_books_cache()
    await books.get_all_books_odds("nba", limit=10)
    assert calls["fetch"] == 4, "clear resets the aggregate cache too"


# ── odds: get_odds pulls from the 112-book scrapers ──────────────────────


async def test_get_odds_sources_books_pulls_books_records(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: dict[str, int] = {"books": 0}
    monkeypatch.setattr(books, "get_all_books_odds", _fake_books(calls))
    results = await odds.get_odds(sport="nba", sources="books", limit=10)
    assert calls["books"] == 1
    assert results
    assert all(record["source"] == "books" for record in results)
    assert results[0]["book_id"] == "draftkings"
    assert results[0]["sport"] == "nba"


async def test_get_odds_sources_all_merges_books(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: dict[str, int] = {"books": 0}
    monkeypatch.setattr(odds, "_espn_odds_for_league", _fake_espn())
    monkeypatch.setattr(books, "get_all_books_odds", _fake_books(calls))
    monkeypatch.setattr(sources, "source_supports", lambda name, sport: False)
    results = await odds.get_odds(sport="nba", sources="all", limit=50)
    source_set = {record["source"] for record in results}
    assert calls["books"] == 1
    assert "espn" in source_set
    assert "books" in source_set
    assert any(record.get("book_id") == "draftkings" for record in results)


async def test_get_odds_default_does_not_call_books(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: dict[str, int] = {"books": 0, "espn": 0}
    monkeypatch.setattr(odds, "_espn_odds_for_league", _fake_espn())
    monkeypatch.setattr(books, "get_all_books_odds", _fake_books(calls))
    results = await odds.get_odds(sport="nba", limit=10)
    assert calls["books"] == 0, "default get_odds must not touch the 112-book scrapers"
    assert calls["espn"] == 0
    assert results
    assert all(record["source"] == "espn" for record in results)


# ── odds: get_odds_multi sources="all" aggregates books ──────────────────


async def test_get_odds_multi_sources_all_merges_books(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_event_odds(event_id: str, market: str, book: str | None) -> dict[str, Any]:
        return {"event": "Lakers @ Celtics", "sport": "nba", "event_id": "eid123"}

    calls: dict[str, int] = {"books": 0}
    monkeypatch.setattr(odds, "_get_event_odds", fake_event_odds)
    monkeypatch.setattr(odds, "_espn_odds_for_league", _fake_espn())
    monkeypatch.setattr(books, "get_all_books_odds", _fake_books(calls))
    monkeypatch.setattr(sources, "source_supports", lambda name, sport: False)
    results = await odds.get_odds_multi("eid123", sources="all", limit=100)
    assert calls["books"] == 1
    source_set = {record["source"] for record in results}
    assert "espn" in source_set
    assert "books" in source_set
    books_records = [record for record in results if record["source"] == "books"]
    assert books_records
    assert books_records[0]["book_id"] == "draftkings"


async def test_get_odds_multi_default_does_not_call_books(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_event_odds(event_id: str, market: str, book: str | None) -> dict[str, Any]:
        return {"event": "Lakers @ Celtics", "sport": "nba", "event_id": "eid123"}

    calls: dict[str, int] = {"books": 0}
    monkeypatch.setattr(odds, "_get_event_odds", fake_event_odds)
    monkeypatch.setattr(odds, "_espn_odds_for_league", _fake_espn())
    monkeypatch.setattr(books, "get_all_books_odds", _fake_books(calls))
    monkeypatch.setattr(sources, "source_supports", lambda name, sport: False)
    results = await odds.get_odds_multi("eid123", limit=50)
    assert calls["books"] == 0, "default get_odds_multi must not pull the 112-book scrapers"
    assert results
    assert all(record["source"] == "espn" for record in results)


# ── odds: _books_odds_for_sport tagging / filtering ──────────────────────


async def test_books_odds_for_sport_tags_copy_not_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = _book_record("fanduel", "FanDuel")

    async def fake_books(sport: str, market: str = "h2h", limit: int = 100) -> list[dict[str, Any]]:
        return [record]

    monkeypatch.setattr(books, "get_all_books_odds", fake_books)
    tagged = await odds._books_odds_for_sport("nba", ["h2h"], None, limit=50)
    assert len(tagged) == 1
    assert tagged[0]["source"] == "books"
    assert tagged[0]["sport"] == "nba"
    assert tagged[0] is not record, "records must be copied, never mutated (books cache)"
    assert record["source"] == "books:fanduel", "original record must stay untagged"


async def test_books_odds_for_sport_filters_markets_and_book(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records = [
        _book_record("draftkings", "DraftKings", market="spreads"),
        _book_record("fanduel", "FanDuel", market="h2h"),
    ]

    async def fake_books(sport: str, market: str = "h2h", limit: int = 100) -> list[dict[str, Any]]:
        return records

    monkeypatch.setattr(books, "get_all_books_odds", fake_books)
    tagged = await odds._books_odds_for_sport("nba", ["h2h"], None)
    assert len(tagged) == 1
    assert tagged[0]["book_id"] == "fanduel"
    filtered = await odds._books_odds_for_sport("nba", ["h2h"], "draftkings")
    assert filtered == []


# ── never-raise: books unavailable or raising ────────────────────────────


async def test_books_odds_for_sport_module_unavailable_never_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Simulate the books module not being importable yet (parallel edit).
    # The package attribute must be killed too — ``sports_data.books`` is
    # already imported, so ``from sports_data import books`` would otherwise
    # resolve via the existing attribute and run a real scrape.
    monkeypatch.setitem(sys.modules, "sports_data.books", None)
    monkeypatch.setattr(sports_data, "books", None)
    assert await odds._books_odds_for_sport("nba", ["h2h"], None) == []


async def test_get_odds_sources_books_unavailable_never_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "sports_data.books", None)
    monkeypatch.setattr(sports_data, "books", None)
    results = await odds.get_odds(sport="nba", sources="books", limit=10)
    assert results == []


async def test_get_odds_books_fetch_raises_never_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def boom(sport: str, market: str = "h2h", limit: int = 100) -> list[dict[str, Any]]:
        raise RuntimeError("scraper down")

    monkeypatch.setattr(books, "get_all_books_odds", boom)
    results = await odds.get_odds(sport="nba", sources="books", limit=10)
    assert results == []


async def test_get_odds_multi_books_fetch_raises_never_blanks_others(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_event_odds(event_id: str, market: str, book: str | None) -> dict[str, Any]:
        return {"event": "Lakers @ Celtics", "sport": "nba", "event_id": "eid123"}

    async def boom(sport: str, market: str = "h2h", limit: int = 100) -> list[dict[str, Any]]:
        raise RuntimeError("scraper down")

    monkeypatch.setattr(odds, "_get_event_odds", fake_event_odds)
    monkeypatch.setattr(odds, "_espn_odds_for_league", _fake_espn())
    monkeypatch.setattr(books, "get_all_books_odds", boom)
    monkeypatch.setattr(sources, "source_supports", lambda name, sport: False)
    results = await odds.get_odds_multi("eid123", sources="all", limit=100)
    assert results
    assert all(record["source"] == "espn" for record in results)
