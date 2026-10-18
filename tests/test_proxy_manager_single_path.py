# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Single proxy path, credential hygiene and cookie-warmer leak regressions."""

import json
import os
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import pry.engine.proxy_manager as proxy_manager
from pry.commerce.marketplace import _retail_transport
from pry.engine import cookie_warmer
from pry.engine.cookie_warmer import CookieWarmer
from pry.engine.proxy_manager import ProxyManager
from pry.engine.webshare_proxy import clear_cache, next_webshare_proxy, reset_rotation


@pytest.fixture
def pm(tmp_path: Path) -> ProxyManager:
    return ProxyManager(data_dir=tmp_path)


def test_all_three_call_sites_resolve_through_one_manager(
    pm: ProxyManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str | None] = []

    def fake_best_proxy(self: ProxyManager, domain: str | None = None) -> str:
        calls.append(domain)
        return "http://single:8080"

    monkeypatch.setattr(ProxyManager, "get_best_proxy", fake_best_proxy)
    clear_cache()
    reset_rotation()

    assert pm.get_proxy_url() == "http://single:8080"
    assert next_webshare_proxy() == "http://single:8080"
    assert _retail_transport._next_proxy("https://www.costco.com/item") == "http://single:8080"
    assert len(calls) == 3


def _seed_creds(tmp_path: Path, mode: int) -> Path:
    path = tmp_path / "credentials.json"
    path.write_text(
        json.dumps({"brightdata": {"provider": "brightdata", "username": "u", "password": "p"}})
    )
    os.chmod(path, mode)
    return path


def test_credentials_file_forced_to_0600(tmp_path: Path) -> None:
    path = _seed_creds(tmp_path, 0o644)
    manager = ProxyManager(data_dir=tmp_path)
    assert path.stat().st_mode & 0o777 == 0o600
    assert "brightdata" in manager.credentials


def test_credentials_refused_when_permissions_cannot_be_fixed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_creds(tmp_path, 0o640)
    real_os = os

    class _UnfixableOs:
        def __getattr__(self, name: str) -> object:
            return getattr(real_os, name)

        @staticmethod
        def chmod(*args: object, **kwargs: object) -> None:
            raise OSError("chmod not permitted")

    monkeypatch.setattr(proxy_manager, "os", _UnfixableOs())
    manager = ProxyManager(data_dir=tmp_path)
    assert manager.credentials == {}


def test_affinity_sticks_then_expires(
    pm: ProxyManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(pm, "_candidate_proxies", lambda: ["http://p1:8080", "http://p2:8080"])
    pm.affinity_ttl_seconds = 0.05
    pm.record_proxy_result("http://p2:8080", True, 1.0, domain="example.com")
    pm.record_proxy_result("http://p1:8080", True, 0.1)
    pm.record_proxy_result("http://p1:8080", True, 0.1)

    assert pm.get_best_proxy("example.com") == "http://p2:8080"
    time.sleep(0.06)
    assert pm.get_best_proxy("example.com") == "http://p1:8080"


def _mock_playwright() -> MagicMock:
    pw = MagicMock()
    pw.chromium.launch = AsyncMock(return_value=pw)
    pw.new_context = AsyncMock(return_value=pw)
    pw.add_init_script = AsyncMock()
    pw.new_page = AsyncMock(return_value=pw)
    pw.goto = AsyncMock()
    pw.evaluate = AsyncMock()
    pw.wait_for_timeout = AsyncMock()
    pw.cookies = AsyncMock(return_value=[])
    pw.close = AsyncMock()
    mock_async_pw = AsyncMock()
    mock_async_pw.__aenter__.return_value = pw
    mock_async_pw.__aexit__.return_value = False
    return mock_async_pw


async def test_browser_closed_when_warming_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cookie_warmer, "WARMER_DIR", tmp_path)
    warmer = CookieWarmer()
    warmer._warm_pages = AsyncMock(side_effect=RuntimeError("blocked"))  # type: ignore[method-assign]
    mock_pw = _mock_playwright()

    with patch("playwright.async_api.async_playwright", return_value=mock_pw):
        result = await warmer.warm_for_site(
            "amazon.com", session_id="boom", min_delay=0.0, max_delay=0.0
        )

    assert result["success"] is False
    mock_pw.__aenter__.return_value.close.assert_awaited()


async def test_user_agent_matches_the_render_tier(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pry.engine.methods import _common

    monkeypatch.setattr(_common, "_DEFAULT_USER_AGENT", "UA-FROM-THE-TIER")
    monkeypatch.setattr(cookie_warmer, "WARMER_DIR", tmp_path)
    mock_pw = _mock_playwright()

    with patch("playwright.async_api.async_playwright", return_value=mock_pw):
        result = await CookieWarmer().warm_for_site(
            "amazon.com", session_id="ua", pages_to_visit=1, min_delay=0.0, max_delay=0.0
        )

    assert result["success"] is True
    browser = mock_pw.__aenter__.return_value
    assert browser.new_context.await_args.kwargs["user_agent"] == "UA-FROM-THE-TIER"
    saved = json.loads((tmp_path / "ua.json").read_text())
    assert saved["user_agent"] == "UA-FROM-THE-TIER"
