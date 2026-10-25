"""Tests for the US geo-fenced sportsbook odds fetchers (sports_data.us_books).

Covers the 11-book registry, the reverse-engineered JSON parsers (DraftKings
eventgroup shape, FanDuel eventGroup + cache shapes, PointsBet featured
events, generic events), the Webshare-US-proxy transport with Tor fallback,
geo-block degrade and the never-raise contract.

All HTTP is mocked (aiohttp session mocks / monkeypatched transport) — no
live network, no real Webshare proxies, no Tor daemon.
"""
from unittest.mock import patch

import aiohttp
import pytest

import datasets.sports_data.us_books as us
from tests.sports._sports_us_books_support2 import _fake_aiohttp_session


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
