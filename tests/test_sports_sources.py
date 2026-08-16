# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for multi-source sports odds redundancy.

Covers the new ``sports_data.sources`` module (source registry, OddsPortal
scrape, Bovada + BetOnline offshore feeds, cross-source ``merge_odds``) and
the odds engine integration: the ``sources`` parameter on ``get_odds`` and
``get_odds_multi`` aggregation. Every source degrades independently and
never raises — one dead source never blanks the result if another works.

All HTTP is mocked with respx — no live network.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
import respx

import sports_data.odds as odds
import sports_data.sources as sources
from retry import RetryConfig

_ODDS_NBA = "https://api.the-odds-api.com/v4/sports/basketball_nba"
_ODDS_EPL = "https://api.the-odds-api.com/v4/sports/soccer_epl"
_ODDS_NFL = "https://api.the-odds-api.com/v4/sports/americanfootball_nfl"
_SCORE_NBA = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"

_ODDSPORTAL_LISTING = "https://www.oddsportal.com/basketball/usa/nba/"
_ODDSPORTAL_DETAIL = (
    "https://www.oddsportal.com/basketball/usa/nba/los-angeles-lakers-boston-celtics-123456/"
)
_BOVADA_NBA = "https://www.bovada.lv/services/sports/event/v2/events/A/description/basketball/nba"
_BETONLINE_NBA = "https://www.betonline.ag/sportsbook/basketball/nba"

_ZERO_RETRY = RetryConfig(
    max_retries=1, base_delay=0.0, max_delay=0.0, retryable_exceptions=(httpx.HTTPError,)
)


@pytest.fixture(autouse=True)
def _hermetic_sources(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reset caches, kill backoff delays, clear the API key and health."""
    sources._clear_cache()
    odds._clear_cache()
    monkeypatch.setattr(sources, "_RETRY_CONFIG", _ZERO_RETRY)
    monkeypatch.setattr(odds, "_RETRY_CONFIG", _ZERO_RETRY)
    monkeypatch.delenv("PRY_ODDS_API_KEY", raising=False)
    sources._HEALTH.clear()
    sources._HEALTH.update(
        {
            name: {
                "reachable": True,
                "blocked": False,
                "last_checked": None,
                "latency_ms": None,
                "error": None,
            }
            for name in sources.SOURCE_NAMES
        }
    )


# ── Payload fixtures ────────────────────────────────────────────────────


def _oddsportal_listing_html() -> str:
    """Two NBA matches on the listing page (home-away slug order)."""
    return """<html><body>
<table class="table-main"><tbody>
  <tr>
    <td class="name">
      <a class="participant-name" href="/basketball/usa/nba/los-angeles-lakers-boston-celtics-123456/">Los Angeles Lakers</a>
      <span>-</span>
      <a class="participant-name" href="/basketball/usa/nba/los-angeles-lakers-boston-celtics-123456/">Boston Celtics</a>
    </td>
  </tr>
  <tr>
    <td class="name">
      <a class="participant-name" href="/basketball/usa/nba/miami-heat-new-york-knicks-654321/">Miami Heat</a>
      <span>-</span>
      <a class="participant-name" href="/basketball/usa/nba/miami-heat-new-york-knicks-654321/">New York Knicks</a>
    </td>
  </tr>
</tbody></table>
</body></html>"""


def _oddsportal_detail_html(*, three_way: bool = False) -> str:
    """Match-detail odds table (2-way by default, 3-way for soccer)."""
    if three_way:
        header = "<th>Bookmaker</th><th>1</th><th>X</th><th>2</th><th>Payout</th>"
        rows = """
  <tr class="odd"><td>Pinnacle</td><td>2.40</td><td>3.40</td><td>2.90</td><td>96.1</td></tr>
  <tr class="dark"><td>Bet365</td><td>2.35</td><td>3.50</td><td>2.95</td><td>95.4</td></tr>
"""
    else:
        header = "<th>Bookmaker</th><th>1</th><th>2</th><th>Payout</th>"
        rows = """
  <tr class="odd"><td>Pinnacle</td><td>2.10</td><td>1.85</td><td>96.3</td></tr>
  <tr class="dark"><td>Bet365</td><td>2.05</td><td>1.90</td><td>95.1</td></tr>
  <tr class="odd"><td>Average</td><td>2.07</td><td>1.88</td><td>97.0</td></tr>
"""
    return f"""<html><body>
<div id="odds-data-table"><div class="table-container">
  <table class="table-main detail-odds sortable">
    <thead><tr>{header}</tr></thead>
    <tbody>{rows}</tbody>
  </table>
</div></div>
</body></html>"""


def _bovada_payload() -> list[dict[str, Any]]:
    """One NBA event on the Bovada JSON feed (moneyline/spread/total)."""
    return [
        {
            "path": "sports/event/coupon/events",
            "events": [
                {
                    "id": "bov-1",
                    "description": "Boston Celtics at Los Angeles Lakers",
                    "startTime": "2026-08-17T00:00:00Z",
                    "lastModified": "2026-08-16T18:00:00Z",
                    "competitors": [
                        {"id": "c1", "name": "Los Angeles Lakers", "home": True},
                        {"id": "c2", "name": "Boston Celtics", "home": False},
                    ],
                    "displayGroups": [
                        {
                            "id": "g1",
                            "description": "Game Lines",
                            "markets": [
                                {
                                    "key": "2W-12",
                                    "description": "Moneyline",
                                    "outcomes": [
                                        {
                                            "type": "H",
                                            "description": "Los Angeles Lakers",
                                            "price": {"decimal": "2.10", "american": "+110"},
                                        },
                                        {
                                            "type": "A",
                                            "description": "Boston Celtics",
                                            "price": {"decimal": "1.85", "american": "-118"},
                                        },
                                    ],
                                },
                                {
                                    "key": "2W-HCAP",
                                    "description": "Point Spread",
                                    "outcomes": [
                                        {
                                            "type": "H",
                                            "description": "Los Angeles Lakers",
                                            "price": {
                                                "decimal": "1.91",
                                                "american": "-110",
                                                "handicap": "-5.5",
                                            },
                                        },
                                        {
                                            "type": "A",
                                            "description": "Boston Celtics",
                                            "price": {
                                                "decimal": "1.91",
                                                "american": "-110",
                                                "handicap": "5.5",
                                            },
                                        },
                                    ],
                                },
                                {
                                    "key": "2W-OU",
                                    "description": "Total",
                                    "outcomes": [
                                        {
                                            "type": "O",
                                            "description": "Over",
                                            "price": {
                                                "decimal": "1.90",
                                                "american": "-110",
                                                "handicap": "224.5",
                                            },
                                        },
                                        {
                                            "type": "U",
                                            "description": "Under",
                                            "price": {
                                                "decimal": "1.95",
                                                "american": "-105",
                                                "handicap": "224.5",
                                            },
                                        },
                                    ],
                                },
                            ],
                        }
                    ],
                }
            ],
        }
    ]


def _betonline_html() -> str:
    """One NBA game row on the BetOnline listing page."""
    return """<html><body>
<div class="game-row">
  <a class="game-link" href="/sportsbook/basketball/nba/game/490976637">Celtics at Lakers</a>
  <span class="team-name away">Boston Celtics</span>
  <span class="team-name home">Los Angeles Lakers</span>
  <span class="moneyline">-118</span>
  <span class="moneyline">+110</span>
</div>
</body></html>"""


def _betonline_embedded_html() -> str:
    """BetOnline page with a window.__INITIAL_STATE__ JSON blob."""
    state = {
        "games": [
            {
                "gameId": "490976637",
                "awayTeam": "Boston Celtics",
                "homeTeam": "Los Angeles Lakers",
                "wagerCutOff": "2026-08-17T00:00:00Z",
                "gameData": [
                    {
                        "name": "Match",
                        "lineType": "AwayLine",
                        "lineDict": {
                            "MoneyLine": {"point": None, "line": "-118", "decimalLine": "1.85"}
                        },
                    },
                    {
                        "name": "Match",
                        "lineType": "HomeLine",
                        "lineDict": {
                            "MoneyLine": {"point": None, "line": "+110", "decimalLine": "2.10"}
                        },
                    },
                ],
            }
        ]
    }
    return f"<html><body><script>window.__INITIAL_STATE__ = {json.dumps(state)};</script></body></html>"


def _espn_scoreboard_payload(event_id: str = "eid123") -> dict[str, Any]:
    """One NBA event on ESPN with a DraftKings moneyline block."""
    return {
        "events": [
            {
                "id": event_id,
                "competitions": [
                    {
                        "id": event_id,
                        "competitors": [
                            {
                                "homeAway": "home",
                                "team": {"displayName": "Los Angeles Lakers"},
                                "score": "100",
                            },
                            {
                                "homeAway": "away",
                                "team": {"displayName": "Boston Celtics"},
                                "score": "98",
                            },
                        ],
                        "odds": [
                            {
                                "provider": {"name": "DraftKings"},
                                "homeTeamOdds": {"moneyLine": -150},
                                "awayTeamOdds": {"moneyLine": 130},
                            }
                        ],
                    }
                ],
            }
        ]
    }


def _record(**kw: Any) -> dict[str, Any]:
    """Canonical odds record with sensible defaults."""
    base: dict[str, Any] = {
        "sport": "basketball_nba",
        "event": "Celtics @ Lakers",
        "event_id": "evt-1",
        "market": "h2h",
        "book": "draftkings",
        "bookmaker": "DraftKings",
        "home": "Los Angeles Lakers",
        "away": "Boston Celtics",
        "home_odds": 2.10,
        "away_odds": 1.85,
        "draw_odds": None,
        "spread": None,
        "total": None,
        "last_update": "2026-08-16T18:00:00Z",
        "source": "the_odds_api",
    }
    base.update(kw)
    return base


# ── Source registry ─────────────────────────────────────────────────────


def test_source_registry_has_all_five_sources() -> None:
    assert set(sources.SOURCES) == {
        "the_odds_api",
        "espn",
        "oddsportal",
        "bovada",
        "betonline",
    }
    for name, entry in sources.SOURCES.items():
        assert 0 <= entry["confidence"] <= 1
        assert entry["kind"] in {"api", "scrape"}
        assert entry["markets"]


def test_source_status_shape() -> None:
    status = sources.source_status()
    assert set(status) == set(sources.SOURCES)
    entry = status["oddsportal"]
    assert entry["name"] == "oddsportal"
    assert entry["confidence"] == sources.SOURCES["oddsportal"]["confidence"]
    assert set(entry["availability"]) == {
        "reachable",
        "blocked",
        "last_checked",
        "latency_ms",
        "error",
    }
    assert sources.source_status("bogus") == {}


def test_source_supports() -> None:
    assert sources.source_supports("oddsportal", "nba")
    assert sources.source_supports("bovada", "basketball_nba")
    assert sources.source_supports("betonline", "nfl")
    assert not sources.source_supports("espn", "nba")
    assert not sources.source_supports("bovada", "quidditch")
    assert not sources.source_supports("bogus", "nba")


# ── OddsPortal scrape ───────────────────────────────────────────────────


@respx.mock
async def test_fetch_oddsportal_happy_path() -> None:
    respx.get(_ODDSPORTAL_LISTING).mock(
        return_value=httpx.Response(200, text=_oddsportal_listing_html())
    )
    respx.get(_ODDSPORTAL_DETAIL).mock(
        return_value=httpx.Response(200, text=_oddsportal_detail_html())
    )
    # Only the first listing match has a mocked detail page; the second
    # (knicks game) fails quietly.
    records = await sources.fetch_oddsportal("nba", limit=5)
    assert records
    assert all(record["source"] == "oddsportal" for record in records)
    assert all(record["market"] == "h2h" for record in records)
    assert all("Lakers" in record["home"] for record in records)
    pinnacle = [r for r in records if r["book"] == "pinnacle"]
    assert pinnacle and pinnacle[0]["home_odds"] == 2.10 and pinnacle[0]["away_odds"] == 1.85
    assert pinnacle[0]["draw_odds"] is None
    assert any(r["book"] == "bet365" for r in records)
    # The "Average" summary row must never become a bookmaker record.
    assert not any(r["book"] == "average" for r in records)
    assert sources.source_status("oddsportal")["availability"]["reachable"]


@respx.mock
async def test_fetch_oddsportal_three_way_soccer() -> None:
    listing = "https://www.oddsportal.com/soccer/england/premier-league/"
    detail = (
        "https://www.oddsportal.com/soccer/england/premier-league/manchester-city-liverpool-999999/"
    )
    respx.get(listing).mock(
        return_value=httpx.Response(
            200,
            text="""<html><body><table class="table-main"><tbody><tr><td class="name">
<a class="participant-name" href="/soccer/england/premier-league/manchester-city-liverpool-999999/">Manchester City</a>
<span>-</span>
<a class="participant-name" href="/soccer/england/premier-league/manchester-city-liverpool-999999/">Liverpool</a>
</td></tr></tbody></table></body></html>""",
        )
    )
    respx.get(detail).mock(
        return_value=httpx.Response(200, text=_oddsportal_detail_html(three_way=True))
    )
    records = await sources.fetch_oddsportal("epl", limit=5)
    pinnacle = [r for r in records if r["book"] == "pinnacle"]
    assert pinnacle
    assert pinnacle[0]["draw_odds"] == 3.40
    assert pinnacle[0]["home_odds"] == 2.40
    assert pinnacle[0]["away_odds"] == 2.90


@respx.mock
async def test_fetch_oddsportal_blocked_flagged() -> None:
    respx.get(_ODDSPORTAL_LISTING).mock(
        return_value=httpx.Response(
            403,
            text="<html><body>Just a moment... checking your browser</body></html>",
        )
    )
    records = await sources.fetch_oddsportal("nba")
    assert records == []
    health = sources.source_status("oddsportal")["availability"]
    assert health["blocked"] is True
    assert health["reachable"] is False


@respx.mock
async def test_fetch_oddsportal_network_error_never_raises() -> None:
    respx.get(_ODDSPORTAL_LISTING).mock(side_effect=httpx.ConnectError("boom"))
    records = await sources.fetch_oddsportal("nba")
    assert records == []


async def test_fetch_oddsportal_unsupported_sport() -> None:
    records = await sources.fetch_oddsportal("quidditch")
    assert records == []


# ── Bovada public feed ──────────────────────────────────────────────────


@respx.mock
async def test_fetch_bovada_happy_path() -> None:
    respx.get(_BOVADA_NBA).mock(return_value=httpx.Response(200, json=_bovada_payload()))
    records = await sources.fetch_bovada("nba")
    assert records
    assert all(record["source"] == "bovada" for record in records)
    assert all(record["book"] == "bovada" for record in records)
    h2h = [r for r in records if r["market"] == "h2h"]
    assert h2h and h2h[0]["home_odds"] == 2.10 and h2h[0]["away_odds"] == 1.85
    spreads = [r for r in records if r["market"] == "spreads"]
    assert spreads and spreads[0]["spread"] == -5.5
    totals = [r for r in records if r["market"] == "totals"]
    assert totals and totals[0]["total"] == 224.5
    assert totals[0]["home_odds"] == 1.90 and totals[0]["away_odds"] == 1.95


@respx.mock
async def test_fetch_bovada_error_never_raises() -> None:
    respx.get(_BOVADA_NBA).mock(return_value=httpx.Response(500))
    records = await sources.fetch_bovada("nba")
    assert records == []
    assert sources.source_status("bovada")["availability"]["reachable"] is False


async def test_fetch_bovada_unsupported_sport() -> None:
    records = await sources.fetch_bovada("quidditch")
    assert records == []


# ── BetOnline listing scrape ────────────────────────────────────────────


@respx.mock
async def test_fetch_betonline_html_happy_path() -> None:
    respx.get(_BETONLINE_NBA).mock(return_value=httpx.Response(200, text=_betonline_html()))
    records = await sources.fetch_betonline("nba")
    assert records
    record = records[0]
    assert record["source"] == "betonline"
    assert record["book"] == "betonline"
    assert record["home"] == "Los Angeles Lakers"
    assert record["away"] == "Boston Celtics"
    assert record["home_odds"] == 2.10
    assert record["away_odds"] == 1.85


@respx.mock
async def test_fetch_betonline_embedded_json() -> None:
    respx.get(_BETONLINE_NBA).mock(
        return_value=httpx.Response(200, text=_betonline_embedded_html())
    )
    records = await sources.fetch_betonline("nba")
    assert records
    record = records[0]
    assert record["home_odds"] == 2.10
    assert record["away_odds"] == 1.85
    assert record["last_update"] == "2026-08-17T00:00:00Z"


@respx.mock
async def test_fetch_betonline_blocked_never_raises() -> None:
    respx.get(_BETONLINE_NBA).mock(
        return_value=httpx.Response(200, text="<html>Access denied</html>")
    )
    records = await sources.fetch_betonline("nba")
    assert records == []
    assert sources.source_status("betonline")["availability"]["blocked"] is True


async def test_fetch_betonline_unsupported_sport() -> None:
    records = await sources.fetch_betonline("quidditch")
    assert records == []


# ── merge_odds ──────────────────────────────────────────────────────────


def test_merge_odds_dedupes_same_event_market_book() -> None:
    bovada = _record(book="bovada", source="bovada", home_odds=2.05, away_odds=1.90)
    odds_api = _record(book="bovada", source="the_odds_api", home_odds=2.10, away_odds=1.85)
    merged = sources.merge_odds([bovada, odds_api])
    assert len(merged) == 1
    # Same book -> highest-confidence source (the_odds_api) wins.
    assert merged[0]["source"] == "the_odds_api"
    assert merged[0]["home_odds"] == 2.10


def test_priority_key_orders_sharp_books_first() -> None:
    pinnacle = _record(book="pinnacle", source="oddsportal")
    bovada = _record(book="bovada", source="bovada")
    assert sources._priority_key(pinnacle, 0) < sources._priority_key(bovada, 1)


def test_merge_odds_keeps_different_books() -> None:
    a = _record(book="bovada", source="bovada", home_odds=2.05)
    b = _record(book="draftkings", source="the_odds_api", home_odds=2.10)
    merged = sources.merge_odds([a, b])
    assert len(merged) == 2
    assert [r["book"] for r in merged] == ["bovada", "draftkings"]


def test_merge_odds_newer_update_wins_same_source() -> None:
    older = _record(
        source="bovada", book="bovada", home_odds=2.05, last_update="2026-08-16T18:00:00Z"
    )
    newer = _record(
        source="bovada", book="bovada", home_odds=2.10, last_update="2026-08-16T19:00:00Z"
    )
    merged = sources.merge_odds([older, newer])
    assert len(merged) == 1
    assert merged[0]["home_odds"] == 2.10


def test_merge_odds_preserves_input_order() -> None:
    a = _record(book="bovada", source="bovada")
    b = _record(book="draftkings", source="the_odds_api")
    c = _record(book="pinnacle", source="oddsportal")
    merged = sources.merge_odds([a, b, c])
    assert [r["book"] for r in merged] == ["bovada", "draftkings", "pinnacle"]


def test_merge_odds_ignores_non_dicts_and_empty() -> None:
    assert sources.merge_odds([]) == []
    assert len(sources.merge_odds(["junk", {"not": "a record"}])) == 1


# ── Event matching helpers ──────────────────────────────────────────────


def test_same_event_team_containment() -> None:
    full = _record(home="Los Angeles Lakers", away="Boston Celtics")
    short = _record(home="Lakers", away="Celtics", event="Lakers vs Celtics")
    assert sources.same_event(full, short)
    assert sources.same_event(short, full)
    other = _record(home="New York Knicks", away="Miami Heat")
    assert not sources.same_event(full, other)


def test_event_matches_label() -> None:
    record = _record(home="Los Angeles Lakers", away="Boston Celtics")
    assert sources.event_matches(record, "Celtics @ Lakers")
    assert sources.event_matches(record, "Boston Celtics at Los Angeles Lakers")
    assert not sources.event_matches(record, "Knicks @ Nets")
    assert not sources.event_matches(record, "")


# ── odds.get_odds(..., sources=...) integration ─────────────────────────


@respx.mock
async def test_get_odds_sources_bovada_only() -> None:
    route = respx.get(_BOVADA_NBA).mock(return_value=httpx.Response(200, json=_bovada_payload()))
    results = await odds.get_odds(sport="nba", sources="bovada", limit=50)
    assert route.called
    assert results
    assert all(record["source"] == "bovada" for record in results)
    assert all(record["market"] == "h2h" for record in results)  # market default h2h


@respx.mock
async def test_get_odds_sources_espn_and_bovada_merged() -> None:
    respx.get(_SCORE_NBA).mock(return_value=httpx.Response(200, json=_espn_scoreboard_payload()))
    respx.get(_BOVADA_NBA).mock(return_value=httpx.Response(200, json=_bovada_payload()))
    results = await odds.get_odds(sport="nba", sources="espn,bovada", limit=50)
    assert {record["source"] for record in results} == {"espn", "bovada"}
    # Same (event, market, book) would be deduped; different books stay.
    assert len(results) >= 2


@respx.mock
async def test_get_odds_no_sources_keeps_legacy_espn_fallback() -> None:
    respx.get(_SCORE_NBA).mock(return_value=httpx.Response(200, json=_espn_scoreboard_payload()))
    results = await odds.get_odds(sport="nba", limit=10)
    assert results
    assert all(record["source"] == "espn" for record in results)


@respx.mock
async def test_get_odds_unknown_sources_ignored() -> None:
    respx.get(_SCORE_NBA).mock(return_value=httpx.Response(200, json=_espn_scoreboard_payload()))
    results = await odds.get_odds(sport="nba", limit=10, sources="espn,bogus-source")
    assert results
    assert all(record["source"] == "espn" for record in results)


@respx.mock
async def test_get_odds_supplementary_source_down_does_not_blank_core() -> None:
    respx.get(_SCORE_NBA).mock(return_value=httpx.Response(200, json=_espn_scoreboard_payload()))
    respx.get(_BOVADA_NBA).mock(return_value=httpx.Response(500))
    respx.get(_ODDSPORTAL_LISTING).mock(side_effect=httpx.ConnectError("boom"))
    results = await odds.get_odds(sport="nba", sources="espn,bovada,oddsportal", limit=50)
    # ESPN still flows even though both supplementary sources failed.
    assert results
    assert all(record["source"] == "espn" for record in results)


# ── odds.get_odds_multi aggregation ─────────────────────────────────────


@respx.mock
async def test_get_odds_multi_aggregates_reachable_sources() -> None:
    respx.get(_SCORE_NBA).mock(return_value=httpx.Response(200, json=_espn_scoreboard_payload()))
    respx.get(_BOVADA_NBA).mock(return_value=httpx.Response(200, json=_bovada_payload()))
    respx.get(_ODDSPORTAL_LISTING).mock(
        return_value=httpx.Response(200, text=_oddsportal_listing_html())
    )
    respx.get(_ODDSPORTAL_DETAIL).mock(
        return_value=httpx.Response(200, text=_oddsportal_detail_html())
    )
    results = await odds.get_odds_multi("eid123", limit=100)
    assert results
    source_set = {record["source"] for record in results}
    assert {"espn", "bovada", "oddsportal"} <= source_set
    # Every record belongs to the same event (Lakers/Celtics).
    for record in results:
        label = f"{record.get('home')} {record.get('away')}".lower()
        assert "lakers" in label and "celtics" in label


@respx.mock
async def test_get_odds_multi_with_key_uses_odds_api_core(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PRY_ODDS_API_KEY", "test-key")
    # The odds-API core uses two different endpoints:
    #   * event resolution (get_event_odds)  -> /events/<id>/odds returns a DICT
    #   * source gathering (get_odds)        -> /odds returns a LIST of events
    event = {
        "id": "eid123",
        "sport_key": "basketball_nba",
        "commence_time": "2026-08-17T00:00:00Z",
        "home_team": "Los Angeles Lakers",
        "away_team": "Boston Celtics",
        "bookmakers": [
            {
                "key": "pinnacle",
                "title": "Pinnacle",
                "last_update": "2026-08-16T18:00:00Z",
                "markets": [
                    {
                        "key": "h2h",
                        "outcomes": [
                            {"name": "Boston Celtics", "price": 1.85},
                            {"name": "Los Angeles Lakers", "price": 2.10},
                        ],
                    }
                ],
            }
        ],
    }
    respx.get("https://api.the-odds-api.com/v4/sports/basketball_nba/events/eid123/odds").mock(
        return_value=httpx.Response(200, json=event)
    )
    respx.get("https://api.the-odds-api.com/v4/sports/basketball_nba/odds").mock(
        return_value=httpx.Response(200, json=[event])
    )
    respx.get(_BOVADA_NBA).mock(return_value=httpx.Response(200, json=_bovada_payload()))
    # OddsPortal down — must not blank the result.
    respx.get(_ODDSPORTAL_LISTING).mock(return_value=httpx.Response(500))
    # ESPN + BetOnline down too — must not blank the result.
    respx.get(_SCORE_NBA).mock(return_value=httpx.Response(500))
    respx.get(_BETONLINE_NBA).mock(return_value=httpx.Response(500))
    results = await odds.get_odds_multi("eid123", limit=100)
    assert results
    source_set = {record["source"] for record in results}
    assert "the_odds_api" in source_set
    assert "bovada" in source_set
    assert "oddsportal" not in source_set


@respx.mock
async def test_get_odds_multi_all_sources_down_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PRY_ODDS_API_KEY", "test-key")
    # Event resolution succeeds (single-event endpoint), every source fails.
    respx.get(url__startswith=_ODDS_NBA).mock(return_value=httpx.Response(500))
    respx.get(_SCORE_NBA).mock(return_value=httpx.Response(500))
    respx.get(_BOVADA_NBA).mock(return_value=httpx.Response(500))
    respx.get(_ODDSPORTAL_LISTING).mock(return_value=httpx.Response(500))
    respx.get(_BETONLINE_NBA).mock(return_value=httpx.Response(500))
    results = await odds.get_odds_multi("eid123", limit=50)
    assert results == []


@respx.mock
async def test_get_odds_multi_unknown_event_returns_empty() -> None:
    respx.get(_SCORE_NBA).mock(return_value=httpx.Response(200, json={"events": []}))
    results = await odds.get_odds_multi("no-such-event", limit=50)
    assert results == []
