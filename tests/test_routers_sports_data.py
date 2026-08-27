"""Tests for routers/sports_data.py — handler unit tests (no x402 middleware)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from pry.api.routers.data.sports_data import router as sports_data_router

app = FastAPI()
app.include_router(sports_data_router)
client = TestClient(app, raise_server_exceptions=False)


class _AsyncMockModule(MagicMock):
    """Magic mock that returns AsyncMock for any callable attribute lookup."""

    def __getattr__(self, name):
        if name.startswith("_"):
            return super().__getattr__(name)
        return AsyncMock(return_value=[])


def _make_sports_module():
    mod = _AsyncMockModule()
    return mod


def test_sports_odds():
    with patch("pry.api.routers.data.sports_data._sports_module", return_value=_make_sports_module()):
        r = client.get("/v1/sports/odds?event_query=celtics&sport=nba")
        assert r.status_code == 200, f"Got {r.status_code}: {r.text[:200]}"
        assert r.json().get("success") is True


def test_sports_odds_no_params():
    with patch("pry.api.routers.data.sports_data._sports_module", return_value=_make_sports_module()):
        r = client.get("/v1/sports/odds")
        assert r.status_code == 200


def test_sports_event_odds():
    with patch("pry.api.routers.data.sports_data._sports_module", return_value=_make_sports_module()):
        r = client.get("/v1/sports/odds/123")
        assert r.status_code == 200


def test_sports_stats():
    with patch("pry.api.routers.data.sports_data._sports_module", return_value=_make_sports_module()):
        r = client.get("/v1/sports/stats/lebron")
        assert r.status_code == 200


def test_scores():
    with patch("pry.api.routers.data.sports_data._sports_module", return_value=_make_sports_module()):
        r = client.get("/v1/sports/scores")
        assert r.status_code == 200


def test_arbitrage():
    with patch("pry.api.routers.data.sports_data._sports_module", return_value=_make_sports_module()):
        r = client.get("/v1/sports/arbitrage")
        assert r.status_code == 200


def test_injuries():
    with patch("pry.api.routers.data.sports_data._sports_module", return_value=_make_sports_module()):
        r = client.get("/v1/sports/injuries")
        assert r.status_code == 200


def test_live():
    with patch("pry.api.routers.data.sports_data._sports_module", return_value=_make_sports_module()):
        r = client.get("/v1/sports/live")
        assert r.status_code == 200


def test_books():
    with patch("pry.api.routers.data.sports_data._sports_module", return_value=_make_sports_module()):
        r = client.get("/v1/sports/books")
        assert r.status_code == 200


def test_sharp_consensus():
    with patch("pry.api.routers.data.sports_data._sports_module", return_value=_make_sports_module()):
        r = client.get("/v1/sports/sharp-consensus")
        assert r.status_code == 200


def test_plus_ev():
    with patch("pry.api.routers.data.sports_data._sports_module", return_value=_make_sports_module()):
        r = client.get("/v1/sports/plus-ev")
        assert r.status_code == 200


def test_alerts():
    with patch("pry.api.routers.data.sports_data._sports_module", return_value=_make_sports_module()):
        r = client.get("/v1/sports/alerts")
        assert r.status_code == 200
