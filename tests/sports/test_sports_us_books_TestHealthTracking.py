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
from tests.sports._sports_us_books_support import _dk_eventgroup_payload


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
