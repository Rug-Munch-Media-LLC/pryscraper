"""Tests for the US geo-fenced sportsbook odds fetchers (sports_data.us_books).

Covers the 11-book registry, the reverse-engineered JSON parsers (DraftKings
eventgroup shape, FanDuel eventGroup + cache shapes, PointsBet featured
events, generic events), the Webshare-US-proxy transport with Tor fallback,
geo-block degrade and the never-raise contract.

All HTTP is mocked (aiohttp session mocks / monkeypatched transport) — no
live network, no real Webshare proxies, no Tor daemon.
"""
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

import datasets.sports_data.us_books as us
from tests.sports._sports_us_books_support import (
    _dk_eventgroup_payload,
    _fanduel_eventgroup_payload,
)
from tests.sports._sports_us_books_support2 import _generic_events_payload, _pointsbet_payload


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
