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

import json
from typing import TYPE_CHECKING, Any

import httpx
import pytest
import respx

if TYPE_CHECKING:
    from collections.abc import Generator


import datasets.sports_data.alerts as alerts

_HIST_NBA = "https://api.the-odds-api.com/v4/historical/sports/basketball_nba/odds"


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


@respx.mock
async def test_check_alerts_notifies_webhook(monkeypatch: pytest.MonkeyPatch) -> None:
    respx.post("https://hooks.example.com/alert").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    calls = {"n": 0}

    async def fake_event_odds(event_id: str) -> dict[str, Any]:
        calls["n"] += 1
        return _baseline_comparison() if calls["n"] == 1 else _moved_comparison()

    monkeypatch.setattr(alerts, "_get_event_odds", fake_event_odds)
    await alerts.set_alert(
        "eid123",
        market="h2h",
        threshold=10.0,
        notify_url="https://hooks.example.com/alert",
    )
    fired = await alerts.check_alerts()
    assert len(fired) == 1
    assert fired[0]["notified"] is True
    assert respx.calls.call_count == 1
    payload = respx.calls[0].request.content
    assert b"line_move" in payload


@respx.mock
async def test_check_alerts_notify_failure_does_not_raise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    respx.post("https://hooks.example.com/alert").mock(return_value=httpx.Response(500))
    calls = {"n": 0}

    async def fake_event_odds(event_id: str) -> dict[str, Any]:
        calls["n"] += 1
        return _baseline_comparison() if calls["n"] == 1 else _moved_comparison()

    monkeypatch.setattr(alerts, "_get_event_odds", fake_event_odds)
    await alerts.set_alert(
        "eid123", market="h2h", threshold=10.0, notify_url="https://hooks.example.com/alert"
    )
    fired = await alerts.check_alerts()
    assert len(fired) == 1
    assert fired[0]["notified"] is False


async def test_alerts_json_persistence(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "alerts.json"
    monkeypatch.setenv("PRY_ALERTS_JSON", str(path))

    async def fake_event_odds(event_id: str) -> dict[str, Any]:
        return _baseline_comparison()

    monkeypatch.setattr(alerts, "_get_event_odds", fake_event_odds)
    created = await alerts.set_alert("eid123", market="h2h", threshold=5.0)
    assert path.exists()
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert any(entry["alert_id"] == created["alert_id"] for entry in saved)

    # Simulate a bot restart: drop memory, reload from disk.
    alerts._reset_alerts()
    assert await alerts.list_alerts() == []
    alerts._load_alerts()
    assert len(await alerts.list_alerts()) == 1
    assert (await alerts.list_alerts())[0]["alert_id"] == created["alert_id"]

    # Clearing persists too.
    await alerts.clear_alert(created["alert_id"])
    assert json.loads(path.read_text(encoding="utf-8")) == []


async def test_alerts_json_persistence_corrupt_file_is_ignored(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "alerts.json"
    path.write_text("{not json", encoding="utf-8")
    monkeypatch.setenv("PRY_ALERTS_JSON", str(path))
    alerts._load_alerts()  # must not raise
    assert await alerts.list_alerts() == []
