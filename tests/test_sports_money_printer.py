# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for the sports "money printer" upgrade.

Covers the four new modules:

* :mod:`sports_data.historical` — closing-line history from The Odds API
  historical endpoint (key-gated) + the closing-line resolver.
* :mod:`sports_data.betting_percentages` — public money/ticket % from a
  configured JSON feed (Odds-Shark/Action style), with graceful ``{}``
  degradation and never-fabricate semantics.
* :mod:`sports_data.sharp_consensus` — pure no-vig math + the composite
  sharp line from a mocked multi-book comparison.
* :mod:`sports_data.alerts` — the full alert lifecycle: set -> baseline ->
  fire -> dedup -> episode reset -> re-fire -> clear, plus webhook notify and
  optional JSON persistence.

All HTTP is mocked with respx; the odds comparison fetcher
(``sports_data.odds.get_event_odds``) is monkeypatched where the module under
test depends on it. No live network.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import httpx
import pytest
import respx

if TYPE_CHECKING:
    from collections.abc import Generator

import datasets.sports_data as sports_data
import datasets.sports_data.alerts as alerts
import datasets.sports_data.betting_percentages as betting
import datasets.sports_data.historical as historical
import datasets.sports_data.sharp_consensus as sharp

_HIST_NBA = "https://api.the-odds-api.com/v4/historical/sports/basketball_nba/odds"

# ── Fixtures / helpers ─────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _hermetic_money_printer(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    """Reset stores and env between tests so state never leaks."""
    alerts._reset_alerts()
    monkeypatch.delenv("PRY_ALERTS_JSON", raising=False)
    monkeypatch.delenv("PRY_BETTING_PERCENT_FEED", raising=False)
    monkeypatch.delenv("PRY_BETTING_PERCENT_PAGE", raising=False)
    monkeypatch.delenv("PRY_ODDS_API_KEY", raising=False)
    yield
    alerts._reset_alerts()


def _history_payload(event_id: str = "eid123") -> dict[str, Any]:
    """The Odds API historical odds response for one event."""
    return {
        "timestamp": "2026-08-15T23:59:00Z",
        "previous_timestamp": "2026-08-15T23:58:00Z",
        "data": [
            {
                "id": event_id,
                "sport_key": "basketball_nba",
                "commence_time": "2026-08-16T00:00:00Z",
                "home_team": "Los Angeles Lakers",
                "away_team": "Boston Celtics",
                "bookmakers": [
                    {
                        "key": "pinnacle",
                        "title": "Pinnacle",
                        "last_update": "2026-08-15T23:55:00Z",
                        "markets": [
                            {
                                "key": "h2h",
                                "outcomes": [
                                    {"name": "Boston Celtics", "price": 1.90},
                                    {"name": "Los Angeles Lakers", "price": 1.95},
                                ],
                            }
                        ],
                    },
                    {
                        "key": "draftkings",
                        "title": "DraftKings",
                        "last_update": "2026-08-15T23:50:00Z",
                        "markets": [
                            {
                                "key": "h2h",
                                "outcomes": [
                                    {"name": "Boston Celtics", "price": 1.85},
                                    {"name": "Los Angeles Lakers", "price": 2.00},
                                ],
                            }
                        ],
                    },
                ],
            }
        ],
    }


def _book(key: str, home_odds: float, away_odds: float) -> dict[str, Any]:
    """One bookmaker block for a comparison payload."""
    return {
        "key": key,
        "title": key.title(),
        "book": key,
        "markets": [
            {
                "key": "h2h",
                "outcomes": [
                    {"name": "Boston Celtics", "price": away_odds},
                    {"name": "Los Angeles Lakers", "price": home_odds},
                ],
            }
        ],
    }


def _comparison(
    bookmakers: list[dict[str, Any]],
    *,
    event: str = "Boston Celtics @ Los Angeles Lakers",
    event_id: str = "eid123",
    sport: str = "nba",
) -> dict[str, Any]:
    """A canned ``get_event_odds`` comparison (Away @ Home label)."""
    return {
        "event_id": event_id,
        "sport": sport,
        "event": event,
        "commence_time": "2026-08-16T00:00:00Z",
        "bookmakers": bookmakers,
        "source": "the_odds_api",
    }


def _baseline_comparison() -> dict[str, Any]:
    """Baseline line: home 2.00 / away 1.85."""
    return _comparison([_book("pinnacle", 2.00, 1.85)])


def _moved_comparison() -> dict[str, Any]:
    """Moved line: home 2.40 (+20%) / away 1.80."""
    return _comparison([_book("pinnacle", 2.40, 1.80)])


# ── Imports / package surface ──────────────────────────────────────────


def test_money_printer_modules_import() -> None:
    assert callable(historical.get_historical_odds)
    assert callable(historical.get_closing_line)
    assert callable(betting.get_betting_percentages)
    assert callable(sharp.get_sharp_consensus)
    assert callable(alerts.set_alert)
    assert callable(alerts.check_alerts)
    assert callable(alerts.list_alerts)
    assert callable(alerts.clear_alert)


def test_money_printer_re_exported_from_package() -> None:
    # The package __init__ re-exports sibling callables automatically.
    for name in (
        "get_historical_odds",
        "get_closing_line",
        "get_betting_percentages",
        "get_sharp_consensus",
        "set_alert",
        "check_alerts",
        "list_alerts",
        "clear_alert",
    ):
        assert hasattr(sports_data, name)


# ── historical: get_historical_odds ────────────────────────────────────


@respx.mock
async def test_get_historical_odds_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRY_ODDS_API_KEY", "test-key")
    respx.get(url__startswith=_HIST_NBA).mock(
        return_value=httpx.Response(200, json=_history_payload())
    )
    results = await historical.get_historical_odds("nba", "eid123")
    assert len(results) == 2
    by_book = {record["book"]: record for record in results}
    pinnacle = by_book["Pinnacle"]
    assert pinnacle["odds"]["home"] == 1.95  # Los Angeles Lakers
    assert pinnacle["odds"]["away"] == 1.90  # Boston Celtics
    assert pinnacle["updated_at"] == "2026-08-15T23:55:00Z"
    assert by_book["DraftKings"]["odds"]["home"] == 2.00
    assert results == sorted(results, key=lambda record: record["book"])


@respx.mock
async def test_get_historical_odds_no_key_returns_empty() -> None:
    respx.get(url__startswith=_HIST_NBA).mock(
        return_value=httpx.Response(200, json=_history_payload())
    )
    assert await historical.get_historical_odds("nba", "eid123") == []
    assert respx.calls.call_count == 0  # key-gated: no upstream request


@respx.mock
async def test_get_historical_odds_empty_ids_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PRY_ODDS_API_KEY", "test-key")
    assert await historical.get_historical_odds("nba", "  ") == []
    assert await historical.get_historical_odds("", "eid123") == []
    assert respx.calls.call_count == 0


@respx.mock
async def test_get_historical_odds_http_error_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PRY_ODDS_API_KEY", "test-key")
    respx.get(url__startswith=_HIST_NBA).mock(return_value=httpx.Response(500))
    assert await historical.get_historical_odds("nba", "eid123") == []


@respx.mock
async def test_get_historical_odds_malformed_payload_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PRY_ODDS_API_KEY", "test-key")
    respx.get(url__startswith=_HIST_NBA).mock(return_value=httpx.Response(200, json={"nope": True}))
    assert await historical.get_historical_odds("nba", "eid123") == []


@respx.mock
async def test_get_historical_odds_unknown_sport_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PRY_ODDS_API_KEY", "test-key")
    respx.get(url__startswith="https://api.the-odds-api.com/v4/historical/sports/quidditch").mock(
        return_value=httpx.Response(404)
    )
    assert await historical.get_historical_odds("quidditch", "eid123") == []


@respx.mock
async def test_get_historical_odds_event_filter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRY_ODDS_API_KEY", "test-key")
    respx.get(url__startswith=_HIST_NBA).mock(
        return_value=httpx.Response(200, json=_history_payload())
    )
    # The endpoint returns every event; the module filters client-side too.
    assert await historical.get_historical_odds("nba", "eid123") != []
    assert await historical.get_historical_odds("nba", "other-event") == []


# ── historical: get_closing_line ───────────────────────────────────────


@respx.mock
async def test_get_closing_line_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRY_ODDS_API_KEY", "test-key")

    async def fake_event_odds(event_id: str) -> dict[str, Any]:
        assert event_id == "eid123"
        return _comparison([_book("pinnacle", 2.00, 1.85)], sport="nba")

    monkeypatch.setattr(historical, "_get_event_odds", fake_event_odds)
    respx.get(url__startswith=_HIST_NBA).mock(
        return_value=httpx.Response(200, json=_history_payload())
    )
    result = await historical.get_closing_line("eid123")
    assert result["event_id"] == "eid123"
    assert result["sport"] == "nba"
    expected = {"home": 1.95, "away": 1.90}
    assert result["closing"]["Pinnacle"] == expected
    expected_2 = {"home": 2.00, "away": 1.85}
    assert result["closing"]["DraftKings"] == expected_2
    expected_3 = {"book": "DraftKings", "odds": 2.00}
    assert result["best"]["home"] == expected_3
    expected_4 = {"book": "Pinnacle", "odds": 1.90}
    assert result["best"]["away"] == expected_4
    assert result["source"] == "the_odds_api"


@respx.mock
async def test_get_closing_line_no_comparison_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_event_odds(event_id: str) -> dict[str, Any]:
        return {}

    monkeypatch.setattr(historical, "_get_event_odds", fake_event_odds)
    assert await historical.get_closing_line("eid123") == {}
    assert respx.calls.call_count == 0


@respx.mock
async def test_get_closing_line_no_history_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PRY_ODDS_API_KEY", "test-key")

    async def fake_event_odds(event_id: str) -> dict[str, Any]:
        return _comparison([_book("pinnacle", 2.00, 1.85)])

    monkeypatch.setattr(historical, "_get_event_odds", fake_event_odds)
    respx.get(url__startswith=_HIST_NBA).mock(return_value=httpx.Response(500))
    assert await historical.get_closing_line("eid123") == {}


async def test_get_closing_line_empty_id_returns_empty() -> None:
    assert await historical.get_closing_line("  ") == {}


# ── betting_percentages ────────────────────────────────────────────────


@respx.mock
async def test_get_betting_percentages_json_feed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRY_BETTING_PERCENT_FEED", "https://feed.example.com/v1/money/{event_id}")
    respx.get(url__startswith="https://feed.example.com/v1/money/eid123").mock(
        return_value=httpx.Response(
            200,
            json={
                "home_money_pct": 62.5,
                "away_money_pct": 37.5,
                "home_ticket_pct": 55.0,
                "away_ticket_pct": 45.0,
                "steam_moves": 3,
            },
        )
    )
    result = await betting.get_betting_percentages("eid123")
    assert result["home_money_pct"] == 62.5
    assert result["away_money_pct"] == 37.5
    assert result["home_ticket_pct"] == 55.0
    assert result["away_ticket_pct"] == 45.0
    assert result["steam_moves"] == 3


@respx.mock
async def test_get_betting_percentages_feed_normalizes_pair(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PRY_BETTING_PERCENT_FEED", "https://feed.example.com/money")
    respx.get(url__startswith="https://feed.example.com/money/eid123").mock(
        return_value=httpx.Response(
            200,
            json={
                "home_money_pct": 40.0,
                "away_money_pct": 40.0,  # sums to 80 -> normalized to 50/50
                "steam_moves": "1",
            },
        )
    )
    result = await betting.get_betting_percentages("eid123")
    assert result["home_money_pct"] == 50.0
    assert result["away_money_pct"] == 50.0
    assert result["steam_moves"] == 1


@respx.mock
async def test_get_betting_percentages_feed_alternate_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PRY_BETTING_PERCENT_FEED", "https://feed.example.com/money")
    respx.get(url__startswith="https://feed.example.com/money/eid123").mock(
        return_value=httpx.Response(
            200,
            json={"homeMoneyPct": 70.0, "awayMoneyPct": 30.0, "steamMovesCount": 2},
        )
    )
    result = await betting.get_betting_percentages("eid123")
    assert result["home_money_pct"] == 70.0
    assert result["away_money_pct"] == 30.0
    assert result["steam_moves"] == 2


@respx.mock
async def test_get_betting_percentages_no_feed_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_event_odds(event_id: str) -> dict[str, Any]:
        return {}

    monkeypatch.setattr(betting, "_get_event_odds", fake_event_odds)
    # The default page fallback is mocked to fail so the function degrades.
    respx.get(url__startswith="https://www.covers.com").mock(return_value=httpx.Response(404))
    assert await betting.get_betting_percentages("eid123") == {}


@respx.mock
async def test_get_betting_percentages_feed_error_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PRY_BETTING_PERCENT_FEED", "https://feed.example.com/money")
    respx.get(url__startswith="https://feed.example.com/money/eid123").mock(
        return_value=httpx.Response(500)
    )
    # Second/third sources are skipped by the 404 default-page mock.
    respx.get(url__startswith="https://www.covers.com").mock(return_value=httpx.Response(404))
    assert await betting.get_betting_percentages("eid123") == {}


@respx.mock
async def test_get_betting_percentages_never_fabricates_on_garbage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PRY_BETTING_PERCENT_FEED", "https://feed.example.com/money")
    respx.get(url__startswith="https://feed.example.com/money/eid123").mock(
        return_value=httpx.Response(200, json={"unrelated": "data"})
    )
    respx.get(url__startswith="https://www.covers.com").mock(
        return_value=httpx.Response(200, text="<html>no percentages here</html>")
    )
    assert await betting.get_betting_percentages("eid123") == {}


@respx.mock
async def test_get_betting_percentages_empty_id_returns_empty() -> None:
    assert await betting.get_betting_percentages("  ") == {}
    assert respx.calls.call_count == 0


# ── sharp_consensus: pure math ─────────────────────────────────────────


def test_no_vig_pure_math() -> None:
    fair = sharp._no_vig(1.90, 2.10)
    assert fair is not None
    home_prob, away_prob = fair
    assert home_prob == pytest.approx(0.5251, abs=0.001)
    assert away_prob == pytest.approx(0.4749, abs=0.001)
    assert home_prob + away_prob == pytest.approx(1.0)
    assert sharp._no_vig(0.5, 2.0) is None  # odds must exceed 1
    assert sharp._no_vig("garbage", 2.0) is None
    assert sharp._no_vig(None, None) is None


def test_no_vig_even_line_is_fair() -> None:
    fair = sharp._no_vig(2.0, 2.0)
    expected = (0.5, 0.5)
    assert fair == expected


def test_teams_from_label() -> None:
    expected = (
        "Los Angeles Lakers",
        "Boston Celtics",
    )
    assert sharp._teams_from_label("Boston Celtics @ Los Angeles Lakers") == expected
    expected_2 = (None, None)
    assert sharp._teams_from_label("no separator") == expected_2
    expected_3 = (None, None)
    assert sharp._teams_from_label("") == expected_3


# ── sharp_consensus: composite line ────────────────────────────────────


async def test_get_sharp_consensus_three_books(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_event_odds(event_id: str) -> dict[str, Any]:
        return _comparison(
            [
                _book("pinnacle", 1.95, 1.90),
                _book("betcris", 1.94, 1.91),
                _book("circa", 1.96, 1.89),
                _book("draftkings", 2.00, 1.85),  # retail book, ignored
            ]
        )

    monkeypatch.setattr(sharp, "_get_event_odds", fake_event_odds)
    result = await sharp.get_sharp_consensus("eid123")
    assert result["event_id"] == "eid123"
    assert result["market"] == "h2h"
    expected = ["betcris", "circa", "pinnacle"]
    assert result["consensus_books"] == expected
    expected_2 = ["betcris", "circa", "pinnacle"]
    assert result["books_used"] == expected_2
    # p_home for (home, away) = (1/home)/(1/home + 1/away); mean over the
    # three sharp books: pinnacle 0.493506, betcris 0.495872, circa 0.490911.
    assert result["no_vig_prob"]["home"] == pytest.approx(0.4934, abs=0.002)
    assert result["no_vig_prob"]["away"] == pytest.approx(0.5066, abs=0.002)
    assert result["fair_line"]["home"] == pytest.approx(2.03, abs=0.02)
    assert result["confidence"] >= 0.7  # three agreeing sharp books


async def test_get_sharp_consensus_single_book_low_confidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_event_odds(event_id: str) -> dict[str, Any]:
        return _comparison([_book("pinnacle", 1.95, 1.90)])

    monkeypatch.setattr(sharp, "_get_event_odds", fake_event_odds)
    result = await sharp.get_sharp_consensus("eid123")
    expected = ["pinnacle"]
    assert result["consensus_books"] == expected
    assert result["confidence"] < 0.5


async def test_get_sharp_consensus_custom_books(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_event_odds(event_id: str) -> dict[str, Any]:
        return _comparison(
            [
                _book("pinnacle", 1.95, 1.90),
                _book("draftkings", 2.00, 1.85),
            ]
        )

    monkeypatch.setattr(sharp, "_get_event_odds", fake_event_odds)
    result = await sharp.get_sharp_consensus("eid123", books=("draftkings",))
    expected = ["draftkings"]
    assert result["consensus_books"] == expected


async def test_get_sharp_consensus_no_sharp_books_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_event_odds(event_id: str) -> dict[str, Any]:
        return _comparison([_book("draftkings", 2.00, 1.85)])

    monkeypatch.setattr(sharp, "_get_event_odds", fake_event_odds)
    assert await sharp.get_sharp_consensus("eid123") == {}


async def test_get_sharp_consensus_odds_failure_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_event_odds(event_id: str) -> dict[str, Any]:
        return {}

    monkeypatch.setattr(sharp, "_get_event_odds", fake_event_odds)
    assert await sharp.get_sharp_consensus("eid123") == {}


async def test_get_sharp_consensus_empty_id_returns_empty() -> None:
    assert await sharp.get_sharp_consensus("  ") == {}


async def test_get_sharp_consensus_empty_books_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_event_odds(event_id: str) -> dict[str, Any]:
        return _comparison([_book("pinnacle", 1.95, 1.90)])

    monkeypatch.setattr(sharp, "_get_event_odds", fake_event_odds)
    assert await sharp.get_sharp_consensus("eid123", books=()) == {}


# ── alerts: lifecycle ──────────────────────────────────────────────────


async def test_set_alert_and_list(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_event_odds(event_id: str) -> dict[str, Any]:
        return _baseline_comparison()

    monkeypatch.setattr(alerts, "_get_event_odds", fake_event_odds)
    created = await alerts.set_alert("eid123", market="h2h", threshold=10.0)
    assert created["status"] == "active"
    assert created["alert_id"]
    listed = await alerts.list_alerts()
    assert len(listed) == 1
    assert listed[0]["alert_id"] == created["alert_id"]
    assert listed[0]["threshold"] == 10.0


async def test_set_alert_invalid_input(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_event_odds(event_id: str) -> dict[str, Any]:
        return {}

    monkeypatch.setattr(alerts, "_get_event_odds", fake_event_odds)
    expected = {"alert_id": "", "status": "error"}
    assert await alerts.set_alert("", "h2h", 5.0) == expected
    expected_2 = {
        "alert_id": "",
        "status": "error",
    }
    assert await alerts.set_alert("eid123", "nonsense", 5.0) == expected_2
    expected_3 = {
        "alert_id": "",
        "status": "error",
    }
    assert await alerts.set_alert("eid123", "h2h", 0.0) == expected_3
    expected_4 = {  # type: ignore[arg-type]
        "alert_id": "",
        "status": "error",
    }
    assert await alerts.set_alert("eid123", "h2h", "garbage") == expected_4
    assert await alerts.list_alerts() == []


async def test_check_alerts_fires_line_move(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}

    async def fake_event_odds(event_id: str) -> dict[str, Any]:
        calls["n"] += 1
        return _baseline_comparison() if calls["n"] == 1 else _moved_comparison()

    monkeypatch.setattr(alerts, "_get_event_odds", fake_event_odds)
    created = await alerts.set_alert("eid123", market="h2h", threshold=10.0)
    fired = await alerts.check_alerts()
    assert len(fired) == 1
    event = fired[0]
    assert event["alert_id"] == created["alert_id"]
    assert event["kind"] == "line_move"
    assert event["edge"] == pytest.approx(20.0, abs=0.5)  # home 2.00 -> 2.40
    assert "home" in event["message"]
    assert event["notified"] is False
    listed = await alerts.list_alerts()
    assert listed[0]["triggered_count"] == 1
    assert listed[0]["last_signal_key"] == event["signal_key"]


async def test_check_alerts_dedup_and_episode_reset(monkeypatch: pytest.MonkeyPatch) -> None:
    sequence = [
        _baseline_comparison(),
        _moved_comparison(),
        _moved_comparison(),
        _baseline_comparison(),
        _moved_comparison(),
    ]
    calls = {"n": 0}

    async def fake_event_odds(event_id: str) -> dict[str, Any]:
        idx = min(calls["n"], len(sequence) - 1)
        calls["n"] += 1
        return sequence[idx]

    monkeypatch.setattr(alerts, "_get_event_odds", fake_event_odds)
    await alerts.set_alert("eid123", market="h2h", threshold=10.0)

    assert len(await alerts.check_alerts()) == 1  # move fires
    assert len(await alerts.check_alerts()) == 0  # same move deduped
    assert len(await alerts.check_alerts()) == 0  # back to baseline: reset, no fire
    refired = await alerts.check_alerts()  # moved again: new episode
    assert len(refired) == 1
    listed = await alerts.list_alerts()
    assert listed[0]["triggered_count"] == 2


async def test_check_alerts_baseline_established_on_first_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # set_alert baseline fetch fails ({}), so the first check establishes it.
    async def fake_event_odds(event_id: str) -> dict[str, Any]:
        return {}

    monkeypatch.setattr(alerts, "_get_event_odds", fake_event_odds)
    await alerts.set_alert("eid123", market="h2h", threshold=10.0)
    assert await alerts.check_alerts() == []  # nothing fires without a baseline


async def test_check_alerts_arb(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_event_odds(event_id: str) -> dict[str, Any]:
        # home 2.10 @ pinnacle, away 2.10 @ draftkings -> implied 0.9524 (5% arb)
        return _comparison(
            [
                _book("pinnacle", 2.10, 1.90),
                _book("draftkings", 1.85, 2.10),
            ]
        )

    monkeypatch.setattr(alerts, "_get_event_odds", fake_event_odds)
    created = await alerts.set_alert("eid123", market="arb", threshold=2.0)
    fired = await alerts.check_alerts()
    assert len(fired) == 1
    event = fired[0]
    assert event["kind"] == "arb"
    assert event["edge"] == pytest.approx(5.0, abs=0.3)
    assert event["alert_id"] == created["alert_id"]
    # Dedup: the same edge does not re-fire on the next cycle.
    assert await alerts.check_alerts() == []


async def test_check_alerts_arb_no_edge_does_not_fire(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_event_odds(event_id: str) -> dict[str, Any]:
        return _comparison([_book("pinnacle", 1.95, 1.90)])  # no arb

    monkeypatch.setattr(alerts, "_get_event_odds", fake_event_odds)
    await alerts.set_alert("eid123", market="arb", threshold=2.0)
    assert await alerts.check_alerts() == []


async def test_clear_alert(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_event_odds(event_id: str) -> dict[str, Any]:
        return {}

    monkeypatch.setattr(alerts, "_get_event_odds", fake_event_odds)
    created = await alerts.set_alert("eid123", market="h2h", threshold=5.0)
    assert (await alerts.clear_alert(created["alert_id"]))["status"] == "cleared"
    assert await alerts.list_alerts() == []
    assert (await alerts.clear_alert(created["alert_id"]))["status"] == "not_found"
