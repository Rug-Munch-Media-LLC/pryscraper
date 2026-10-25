# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for the US geo-fenced sportsbook odds fetchers (sports_data.us_books).

Covers the 11-book registry, the reverse-engineered JSON parsers (DraftKings
eventgroup shape, FanDuel eventGroup + cache shapes, PointsBet featured
events, generic events), the Webshare-US-proxy transport with Tor fallback,
geo-block degrade and the never-raise contract.

All HTTP is mocked (aiohttp session mocks / monkeypatched transport) — no
live network, no real Webshare proxies, no Tor daemon.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

import datasets.sports_data.us_books as us

# ── Payload fixtures ────────────────────────────────────────────────────


def _dk_eventgroup_payload() -> dict[str, Any]:
    """DraftKings eventgroups shape: groupedMarkets with moneyline/spread/total."""
    return {
        "eventGroup": {"eventGroupId": 42648, "eventGroupName": "NBA"},
        "groupedMarkets": [
            {
                "event": {
                    "id": 37548622,
                    "name": "Celtics @ Lakers",
                    "startTime": "2026-11-01T00:00:00Z",
                },
                "moneyline": {
                    "markets": [
                        {
                            "outcomes": [
                                {"label": "Celtics", "oddsAmerican": 150},
                                {"label": "Lakers", "oddsAmerican": -180},
                            ]
                        }
                    ]
                },
                "spread": {
                    "markets": [
                        {
                            "outcomes": [
                                {"label": "Celtics", "line": 5.5, "oddsAmerican": -110},
                                {"label": "Lakers", "line": -5.5, "oddsAmerican": -110},
                            ]
                        }
                    ]
                },
                "total": {
                    "markets": [
                        {
                            "outcomes": [
                                {"label": "Over", "line": 224.5, "oddsAmerican": -110},
                                {"label": "Under", "line": 224.5, "oddsAmerican": -110},
                            ]
                        }
                    ]
                },
            }
        ],
    }


def _dk_main_array_payload() -> dict[str, Any]:
    """DraftKings alternate shape: ``main`` array with ``marketType`` blocks."""
    return {
        "groupedMarkets": [
            {
                "event": {"id": 1, "name": "Heat @ Knicks"},
                "main": [
                    {
                        "marketType": "MONEYLINE",
                        "outcomes": [
                            {"label": "Heat", "oddsAmerican": 200},
                            {"label": "Knicks", "oddsAmerican": -250},
                        ],
                    },
                    {
                        "marketType": "SPREAD",
                        "outcomes": [
                            {"label": "Heat", "line": 4.5, "oddsAmerican": -110},
                            {"label": "Knicks", "line": -4.5, "oddsAmerican": -110},
                        ],
                    },
                ],
            }
        ]
    }


def _fanduel_eventgroup_payload() -> dict[str, Any]:
    """FanDuel eventGroup shape: events[] with wrapped event + markets."""
    return {
        "eventGroup": {"id": 2, "name": "NBA", "regionCode": "US"},
        "events": [
            {
                "event": {
                    "id": 999,
                    "name": "Celtics @ Lakers",
                    "home": "Lakers",
                    "away": "Celtics",
                },
                "markets": [
                    {
                        "id": 1,
                        "name": "Moneyline",
                        "selections": [
                            {"name": "Celtics", "odds": {"american": 150, "decimal": 2.5}},
                            {"name": "Lakers", "odds": {"american": -180, "decimal": 1.56}},
                        ],
                    },
                    {
                        "id": 2,
                        "name": "Point Spread",
                        "selections": [
                            {
                                "name": "Celtics",
                                "handicap": 5.5,
                                "odds": {"american": -110, "decimal": 1.91},
                            },
                            {
                                "name": "Lakers",
                                "handicap": -5.5,
                                "odds": {"american": -110, "decimal": 1.91},
                            },
                        ],
                    },
                    {
                        "id": 3,
                        "name": "Total Points",
                        "selections": [
                            {
                                "name": "Over",
                                "handicap": 224.5,
                                "odds": {"american": -110, "decimal": 1.91},
                            },
                            {
                                "name": "Under",
                                "handicap": 224.5,
                                "odds": {"american": -110, "decimal": 1.91},
                            },
                        ],
                    },
                ],
            }
        ],
    }


def _fanduel_cache_payload() -> dict[str, Any]:
    """FanDuel cache/psevent shape: eventmarketgroups with price ratio."""
    return {
        "eventmarketgroups": [
            {
                "event": {"id": "555", "name": "Bulls @ Bucks"},
                "markets": [
                    {
                        "id": 1,
                        "name": "Moneyline",
                        "selections": [
                            {"name": "Bulls", "currentpriceup": 20, "currentpricedown": 23},
                            {"name": "Bucks", "currentpriceup": 20, "currentpricedown": 11},
                        ],
                    }
                ],
            }
        ]
    }


def _pointsbet_payload() -> dict[str, Any]:
    """PointsBet featured-events shape: events[] with markets/selections."""
    return {
        "competitionId": 5,
        "events": [
            {
                "id": 111,
                "key": "222",
                "name": "Celtics vs Lakers",
                "markets": [
                    {
                        "id": 1,
                        "name": "Moneyline",
                        "selections": [
                            {"name": "Celtics", "price": 2.5},
                            {"name": "Lakers", "price": 1.56},
                        ],
                    },
                    {
                        "id": 2,
                        "name": "Point Spread",
                        "selections": [
                            {"name": "Celtics", "price": 1.91, "point": 5.5},
                            {"name": "Lakers", "price": 1.91, "point": -5.5},
                        ],
                    },
                ],
            }
        ],
    }


def _generic_events_payload() -> dict[str, Any]:
    """Generic events shape used by the browser-tier books (FanDuel-like)."""
    return {
        "events": [
            {
                "event": {"id": "777", "name": "Heat @ Knicks", "home": "Knicks", "away": "Heat"},
                "markets": [
                    {
                        "name": "Moneyline",
                        "selections": [
                            {"name": "Heat", "odds": {"decimal": 3.0}},
                            {"name": "Knicks", "odds": {"decimal": 1.4}},
                        ],
                    }
                ],
            }
        ]
    }


# ── Test hygiene ────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _hermetic_us_books(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reset caches/health so mocked transports never leak between tests."""
    us._clear_cache()
    us._HEALTH.clear()
    us._HEALTH.update(
        {
            book_id: {
                "reachable": True,
                "blocked": False,
                "last_checked": None,
                "latency_ms": None,
                "error": None,
            }
            for book_id in us._US_BOOK_IDS
        }
    )
    # No real Webshare pool / Tor in tests.
    monkeypatch.setattr(us, "next_webshare_proxy", lambda: None)
    monkeypatch.setattr(us, "fetch_via_tor", None)


def _fake_aiohttp_session(
    *, status: int = 200, text: str = "{}", raise_error: Exception | None = None
) -> MagicMock:
    """Build a mocked aiohttp.ClientSession class.

    ``session.get(url, ...)`` is an async context manager whose ``__aenter__``
    yields a mocked response with ``status`` / ``text()``. When ``raise_error``
    is set, ``__aenter__`` raises it instead (transport never-raise path).
    """
    resp = AsyncMock()
    resp.status = status
    resp.text.return_value = text

    get_cm = AsyncMock()
    if raise_error is not None:
        get_cm.__aenter__.side_effect = raise_error
    else:
        get_cm.__aenter__.return_value = resp

    session = MagicMock()
    session.get.return_value = get_cm

    session_cm = AsyncMock()
    session_cm.__aenter__.return_value = session
    return MagicMock(return_value=session_cm)


# ── Registry ────────────────────────────────────────────────────────────


class TestRegistry:
    """US_BOOKS must carry the documented per-book contract fields."""

    REQUIRED_KEYS = (
        "id",
        "name",
        "category",
        "odds_url_template",
        "method",
        "geo_required",
        "confidence",
    )

    def test_eleven_books_registered(self) -> None:
        expected = {
            "draftkings",
            "fanduel",
            "betmgm",
            "caesars",
            "pointsbet",
            "betrivers",
            "barstool",
            "wynnbet",
            "betway_us",
            "hardrock",
            "espnbet",
        }
        assert set(us.US_BOOKS) == expected

    def test_every_book_has_contract_fields(self) -> None:
        for book_id, entry in us.US_BOOKS.items():
            for key in self.REQUIRED_KEYS:
                assert key in entry, f"{book_id} missing {key}"
            assert entry["id"] == book_id
            assert entry["category"] == "us"
            assert entry["method"] == "json"
            assert entry["geo_required"] is True
            assert 0.0 <= float(entry["confidence"]) <= 1.0
            assert "{category_id" not in entry["odds_url_template"] or book_id == "draftkings"

    def test_book_status_shape(self) -> None:
        status = us.book_status()
        assert set(status) == set(us.US_BOOKS)
        first = status["draftkings"]
        assert first["name"] == "DraftKings"
        assert first["category"] == "us"
        expected = {
            "reachable",
            "blocked",
            "last_checked",
            "latency_ms",
            "error",
        }
        assert set(first["availability"]) == expected


# ── Parser fixtures ─────────────────────────────────────────────────────


class TestDraftKingsParser:
    """DraftKings eventgroup shape -> canonical records."""

    def test_parses_all_three_markets(self) -> None:
        records = us._parse_dk_eventgroup(
            _dk_eventgroup_payload(), "basketball_nba", "draftkings", "DraftKings"
        )
        assert len(records) == 3
        by_market = {record["market"]: record for record in records}
        expected = {"h2h", "spreads", "totals"}
        assert set(by_market) == expected

        h2h = by_market["h2h"]
        assert h2h["home"] == "Lakers"
        assert h2h["away"] == "Celtics"
        assert h2h["home_odds"] == 1.56  # -180 -> 1.56
        assert h2h["away_odds"] == 2.5  # +150 -> 2.5
        assert h2h["book"] == "draftkings"
        assert h2h["source"] == "us_draftkings"
        assert h2h["event_id"] == "37548622"
        assert h2h["event"] == "Celtics @ Lakers"

        spreads = by_market["spreads"]
        assert spreads["spread"] == -5.5  # home (Lakers) line
        assert spreads["home_odds"] == 1.91

        totals = by_market["totals"]
        assert totals["total"] == 224.5
        assert totals["home_odds"] == 1.91  # Over price
        assert totals["away_odds"] == 1.91  # Under price

    def test_main_array_alternate_shape(self) -> None:
        records = us._parse_dk_eventgroup(
            _dk_main_array_payload(), "basketball_nba", "draftkings", "DraftKings"
        )
        by_market = {record["market"]: record for record in records}
        expected = {"h2h", "spreads"}
        assert set(by_market) == expected
        assert by_market["h2h"]["home"] == "Knicks"
        assert by_market["h2h"]["home_odds"] == 1.4  # Knicks -250 -> 1.4
        assert by_market["h2h"]["away_odds"] == 3.0  # Heat +200 -> 3.0

    def test_never_raises_on_garbage(self) -> None:
        assert us._parse_dk_eventgroup(None, "s", "dk", "DK") == []
        assert us._parse_dk_eventgroup([], "s", "dk", "DK") == []
        assert us._parse_dk_eventgroup({"groupedMarkets": "nope"}, "s", "dk", "DK") == []
        assert us._parse_dk_eventgroup({"groupedMarkets": [{"event": {}}]}, "s", "dk", "DK") == []


class TestFanDuelParser:
    """FanDuel eventGroup shape -> canonical records."""

    def test_parses_eventgroup_shape(self) -> None:
        records = us._parse_fanduel_eventgroup(
            _fanduel_eventgroup_payload(), "basketball_nba", "fanduel", "FanDuel"
        )
        assert len(records) == 3
        by_market = {record["market"]: record for record in records}
        expected = {"h2h", "spreads", "totals"}
        assert set(by_market) == expected

        h2h = by_market["h2h"]
        assert h2h["home"] == "Lakers"
        assert h2h["away"] == "Celtics"
        assert h2h["home_odds"] == 1.56
        assert h2h["away_odds"] == 2.5
        assert h2h["source"] == "us_fanduel"
        assert by_market["spreads"]["spread"] == -5.5
        assert by_market["totals"]["total"] == 224.5

    def test_parses_cache_shape_with_price_ratio(self) -> None:
        records = us._parse_fanduel_eventgroup(
            _fanduel_cache_payload(), "basketball_nba", "fanduel", "FanDuel"
        )
        assert len(records) == 1
        h2h = records[0]
        # 20/23 -> decimal 1 + 20/23 = 1.87 ; 20/11 -> 1 + 20/11 = 2.82
        assert h2h["away_odds"] == 1.87
        assert h2h["home_odds"] == 2.82

    def test_never_raises_on_garbage(self) -> None:
        assert us._parse_fanduel_eventgroup(None, "s", "fd", "FD") == []
        assert us._parse_fanduel_eventgroup({}, "s", "fd", "FD") == []
        assert us._parse_fanduel_eventgroup({"events": "nope"}, "s", "fd", "FD") == []


class TestPointsBetParser:
    """PointsBet featured-events shape -> canonical records."""

    def test_parses_featured_events(self) -> None:
        records = us._parse_pointsbet_events(
            _pointsbet_payload(), "basketball_nba", "pointsbet", "PointsBet"
        )
        assert len(records) == 2
        by_market = {record["market"]: record for record in records}
        assert by_market["h2h"]["home_odds"] == 1.56
        assert by_market["h2h"]["away_odds"] == 2.5
        assert by_market["spreads"]["spread"] == -5.5

    def test_never_raises_on_garbage(self) -> None:
        assert us._parse_pointsbet_events("nope", "s", "pb", "PB") == []
        assert us._parse_pointsbet_events({"events": []}, "s", "pb", "PB") == []


class TestGenericParser:
    """Best-effort parser used by the browser-tier books."""

    def test_parses_events_container(self) -> None:
        records = us._parse_generic_events(
            _generic_events_payload(), "basketball_nba", "espnbet", "ESPN BET"
        )
        assert len(records) == 1
        h2h = records[0]
        assert h2h["home"] == "Knicks"
        assert h2h["away"] == "Heat"
        assert h2h["home_odds"] == 1.4
        assert h2h["book"] == "espnbet"

    def test_never_raises_on_unknown_shapes(self) -> None:
        # A DraftKings payload has no events/fixtures container -> no records.
        assert us._parse_generic_events(_dk_eventgroup_payload(), "s", "x", "X") == []
        assert us._parse_generic_events(None, "s", "x", "X") == []
        assert us._parse_generic_events([], "s", "x", "X") == []


# ── URL building / per-book dispatch ────────────────────────────────────


class TestUrlBuilding:
    def test_draftkings_url_uses_category_id(self) -> None:
        url = us._build_url("draftkings", "basketball_nba")
        assert (
            url
            == "https://sportsbook.draftkings.com/sites/US-SB/api/v5/eventgroups?categoryId=42648"
        )

    def test_fanduel_url_uses_event_group_id(self) -> None:
        url = us._build_url("fanduel", "basketball_nba")
        assert url is not None
        assert "eventGroup/2" in url
        assert "regionCode=US" in url

    def test_pointsbet_url(self) -> None:
        url = us._build_url("pointsbet", "basketball_nba")
        assert (
            url
            == "https://api.pointsbet.com/api/v2/competitions/5/events/featured?includeLive=false"
        )

    def test_betrivers_url_uses_group_id(self) -> None:
        url = us._build_url("betrivers", "basketball_nba")
        assert url is not None
        assert "groupId=1000093652" in url

    def test_unmapped_sport_returns_none(self) -> None:
        assert us._build_url("draftkings", "soccer_spain_la_liga") is None
        assert us._build_url("pointsbet", "cricket_international_t20") is None

    def test_unbuildable_token_url_returns_none(self) -> None:
        # BetMGM needs a client-generated x-bwin-accessid -> honest None.
        assert us._build_url("betmgm", "basketball_nba") is None

    def test_generic_books_replace_sport_placeholder(self) -> None:
        url = us._build_url("caesars", "basketball_nba")
        assert url == "https://sportsbook.caesars.com/api/events/basketball_nba"

    def test_canonical_alias_resolution(self) -> None:
        assert us._canonical_sport("nba") == "basketball_nba"
        assert us._canonical_sport("basketball_nba") == "basketball_nba"


# ── Transport (Webshare proxy + Tor fallback, never raises) ─────────────


class TestTransport:
    """_fetch_json_via_proxy: proxy success, geo-block degrade, never-raise."""

    @pytest.mark.anyio
    async def test_proxy_success_returns_parsed_json(self) -> None:
        with (
            patch(
                "datasets.sports_data.us_books.next_webshare_proxy",
                return_value="http://u:p@1.2.3.4:8080",
            ),
            patch("aiohttp.ClientSession", _fake_aiohttp_session(status=200, text='{"ok": 1}')),
        ):
            payload = await us._fetch_json_via_proxy(
                "https://x.test/odds", referer="https://x.test/"
            )
        expected = {"ok": 1}
        assert payload == expected

    @pytest.mark.anyio
    async def test_geo_block_403_degrades_to_none(self) -> None:
        with (
            patch(
                "datasets.sports_data.us_books.next_webshare_proxy",
                return_value="http://u:p@1.2.3.4:8080",
            ),
            patch("aiohttp.ClientSession", _fake_aiohttp_session(status=403, text="forbidden")),
        ):
            payload = await us._fetch_json_via_proxy(
                "https://x.test/odds", referer="https://x.test/"
            )
        assert payload is None

    @pytest.mark.anyio
    async def test_anti_bot_interstitial_degrades_to_none(self) -> None:
        body = "<html>Checking your browser before accessing this site...</html>"
        with (
            patch(
                "datasets.sports_data.us_books.next_webshare_proxy",
                return_value="http://u:p@1.2.3.4:8080",
            ),
            patch("aiohttp.ClientSession", _fake_aiohttp_session(status=200, text=body)),
        ):
            payload = await us._fetch_json_via_proxy(
                "https://x.test/odds", referer="https://x.test/"
            )
        assert payload is None

    @pytest.mark.anyio
    async def test_transport_error_never_raises(self) -> None:
        with (
            patch(
                "datasets.sports_data.us_books.next_webshare_proxy",
                return_value="http://u:p@1.2.3.4:8080",
            ),
            patch(
                "aiohttp.ClientSession",
                _fake_aiohttp_session(raise_error=aiohttp.ClientConnectionError("proxy dead")),
            ),
        ):
            payload = await us._fetch_json_via_proxy(
                "https://x.test/odds", referer="https://x.test/"
            )
        assert payload is None

    @pytest.mark.anyio
    async def test_malformed_json_never_raises(self) -> None:
        with (
            patch(
                "datasets.sports_data.us_books.next_webshare_proxy",
                return_value="http://u:p@1.2.3.4:8080",
            ),
            patch("aiohttp.ClientSession", _fake_aiohttp_session(status=200, text="not json {{{")),
        ):
            payload = await us._fetch_json_via_proxy(
                "https://x.test/odds", referer="https://x.test/"
            )
        assert payload is None

    @pytest.mark.anyio
    async def test_no_proxy_no_tor_degrades_to_none(self) -> None:
        # _hermetic_us_books fixture already nulled both tiers.
        payload = await us._fetch_json_via_proxy("https://x.test/odds", referer="https://x.test/")
        assert payload is None


# ── Per-book fetchers + orchestrator (mocked transport) ────────────────


class TestFetchers:
    """fetch_* + fetch_us_odds with the transport monkeypatched to fixtures."""

    @staticmethod
    def _patch_transport(payload: Any):
        return patch(
            "datasets.sports_data.us_books._fetch_json_via_proxy",
            new=AsyncMock(return_value=payload),
        )

    @pytest.mark.anyio
    async def test_fetch_draftkings_returns_normalized_records(self) -> None:
        with self._patch_transport(_dk_eventgroup_payload()):
            records = await us.fetch_draftkings("nba")
        assert len(records) == 3
        expected = {"h2h", "spreads", "totals"}
        assert {record["market"] for record in records} == expected
        assert all(record["source"] == "us_draftkings" for record in records)
        # Alias and canonical sport both resolve.
        with self._patch_transport(_dk_eventgroup_payload()):
            assert len(await us.fetch_draftkings("basketball_nba")) == 3

    @pytest.mark.anyio
    async def test_fetch_fanduel_returns_normalized_records(self) -> None:
        with self._patch_transport(_fanduel_eventgroup_payload()):
            records = await us.fetch_fanduel("nba")
        assert len(records) == 3
        expected = {"fanduel"}
        assert {record["book"] for record in records} == expected

    @pytest.mark.anyio
    async def test_fetch_pointsbet_returns_normalized_records(self) -> None:
        with self._patch_transport(_pointsbet_payload()):
            records = await us.fetch_pointsbet("nba")
        assert len(records) == 2
        expected = {"pointsbet"}
        assert {record["book"] for record in records} == expected

    @pytest.mark.anyio
    async def test_fetch_betmgm_returns_empty_without_token(self) -> None:
        # URL cannot be built -> honest [] even with a working transport.
        with self._patch_transport(_generic_events_payload()):
            records = await us.fetch_betmgm("nba")
        assert records == []

    @pytest.mark.anyio
    async def test_geo_block_degrades_to_empty_and_marks_blocked(self) -> None:
        with self._patch_transport(None):
            records = await us.fetch_draftkings("nba")
        assert records == []
        assert us._HEALTH["draftkings"]["blocked"] is True
        assert us._HEALTH["draftkings"]["reachable"] is False

    @pytest.mark.anyio
    async def test_unsupported_sport_returns_empty(self) -> None:
        with self._patch_transport(_dk_eventgroup_payload()):
            records = await us.fetch_draftkings("not_a_sport")
        assert records == []

    @pytest.mark.anyio
    async def test_malformed_payload_never_raises(self) -> None:
        with self._patch_transport("this is not json") as mocked:
            records = await us.fetch_draftkings("nba")
        assert records == []
        mocked.assert_awaited_once()

    @pytest.mark.anyio
    async def test_limit_truncates(self) -> None:
        with self._patch_transport(_dk_eventgroup_payload()):
            records = await us.fetch_draftkings("nba", limit=2)
        assert len(records) == 2

    @pytest.mark.anyio
    async def test_fetch_us_odds_merges_across_books(self) -> None:
        async def by_url(url: str, referer: str) -> Any:
            if "draftkings.com" in url:
                return _dk_eventgroup_payload()
            if "fanduel.com" in url:
                return _fanduel_eventgroup_payload()
            if "pointsbet.com" in url:
                return _pointsbet_payload()
            return _generic_events_payload()

        with patch("datasets.sports_data.us_books._fetch_json_via_proxy", side_effect=by_url):
            records = await us.fetch_us_odds("nba", limit=50)
        assert len(records) >= 3
        books = {record["book"] for record in records}
        assert "draftkings" in books
        assert "fanduel" in books
        assert "pointsbet" in books
        assert all(record["source"].startswith("us_") for record in records)

    @pytest.mark.anyio
    async def test_fetch_us_odds_limit_truncates_total(self) -> None:
        async def by_url(url: str, referer: str) -> Any:
            return _generic_events_payload()

        with patch("datasets.sports_data.us_books._fetch_json_via_proxy", side_effect=by_url):
            records = await us.fetch_us_odds("nba", limit=2)
        assert len(records) == 2

    @pytest.mark.anyio
    async def test_fetch_us_odds_all_geo_blocked_returns_empty(self) -> None:
        with self._patch_transport(None):
            records = await us.fetch_us_odds("nba")
        assert records == []

    @pytest.mark.anyio
    async def test_fetch_us_odds_invalid_sport_returns_empty(self) -> None:
        with self._patch_transport(_dk_eventgroup_payload()):
            records = await us.fetch_us_odds("zzz_invalid")
        assert records == []

    @pytest.mark.anyio
    async def test_fetch_us_odds_never_raises_on_transport_explosion(self) -> None:
        async def boom(url: str, referer: str) -> Any:
            raise RuntimeError("unexpected")

        with patch("datasets.sports_data.us_books._fetch_json_via_proxy", side_effect=boom):
            records = await us.fetch_us_odds("nba")
        assert records == []


class TestHealthTracking:
    """book_status reflects what the last fetch saw."""

    @pytest.mark.anyio
    async def test_success_marks_reachable(self) -> None:
        async def by_url(url: str, referer: str) -> Any:
            return _dk_eventgroup_payload()

        with patch("datasets.sports_data.us_books._fetch_json_via_proxy", side_effect=by_url):
            await us.fetch_draftkings("nba")
        status = us.book_status()["draftkings"]["availability"]
        assert status["reachable"] is True
        assert status["blocked"] is False
        assert status["last_checked"] is not None

    @pytest.mark.anyio
    async def test_failure_marks_blocked(self) -> None:
        with patch(
            "datasets.sports_data.us_books._fetch_json_via_proxy", new=AsyncMock(return_value=None)
        ):
            await us.fetch_caesars("nba")
        status = us.book_status()["caesars"]["availability"]
        assert status["blocked"] is True
        assert status["reachable"] is False
        assert status["error"] is not None
