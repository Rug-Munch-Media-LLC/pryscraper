# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Camoufox launch-arg construction: profile catalog, fetch config, errors."""

from unittest.mock import patch

from pry.engine import camoufox_integration
from pry.engine.camoufox_integration import CamoufoxBrowser
from tests.camoufox_support import (  # noqa: F401 - helpers and fixtures
    _mock_camoufox_browser,
    _reset_camoufox_pool,
)


def test_default_configs_launch_args_shape() -> None:
    for _name, cfg in CamoufoxBrowser.DEFAULT_CONFIGS.items():
        assert cfg["headless"] is True
        assert cfg["os"] in {"windows", "macos", "linux"}
        assert cfg["browser"] in {"chrome", "firefox"}
        assert isinstance(cfg["screen"], tuple)
        assert len(cfg["screen"]) == 2
        assert isinstance(cfg["window"], tuple)
        assert len(cfg["window"]) == 2


def test_default_profile_is_valid() -> None:
    b = CamoufoxBrowser()
    assert b.default_profile in CamoufoxBrowser.DEFAULT_CONFIGS


def test_list_profiles_matches_catalog() -> None:
    assert set(CamoufoxBrowser.list_profiles()) == set(CamoufoxBrowser.DEFAULT_CONFIGS.keys())


def test_is_available_reflects_camoufox_installed() -> None:
    with patch.object(camoufox_integration, "_has_camoufox", True):
        assert CamoufoxBrowser().is_available() is True
    with patch.object(camoufox_integration, "_has_camoufox", False):
        assert CamoufoxBrowser().is_available() is False


async def test_fetch_returns_error_when_camoufox_missing() -> None:
    with patch.object(camoufox_integration, "_has_camoufox", False):
        result = await CamoufoxBrowser().fetch("https://example.com")
    assert result["success"] is False
    assert "camoufox" in result["error"]


async def test_fetch_builds_launch_args_from_profile() -> None:
    mock_cls = _mock_camoufox_browser()
    with (
        patch.object(camoufox_integration, "_has_camoufox", True),
        patch(
            "pry.engine.camoufox_integration.AsyncCamoufox", create=True, return_value=mock_cls
        ) as mock_camoufox,
    ):
        result = await CamoufoxBrowser(default_profile="chrome_windows").fetch(
            "https://example.com"
        )

    assert result["success"] is True
    assert result["profile"] == "chrome_windows"
    assert result["title"] == "Camoufox"
    launch_kwargs = mock_camoufox.call_args.kwargs
    assert launch_kwargs["os"] == "windows"
    assert launch_kwargs["browser"] == "chrome"
    expected = (1920, 1080)
    assert launch_kwargs["screen"] == expected
    assert launch_kwargs["headless"] is True
    # No proxy → not passed through
    assert "proxy" not in launch_kwargs


async def test_fetch_adds_proxy_to_launch_args() -> None:
    mock_cls = _mock_camoufox_browser()
    with (
        patch.object(camoufox_integration, "_has_camoufox", True),
        patch(
            "pry.engine.camoufox_integration.AsyncCamoufox", create=True, return_value=mock_cls
        ) as mock_camoufox,
    ):
        result = await CamoufoxBrowser(default_profile="firefox_linux").fetch(
            "https://example.com", proxy="http://user:pass@proxy.example:8080"
        )

    assert result["success"] is True
    launch_kwargs = mock_camoufox.call_args.kwargs
    assert launch_kwargs["os"] == "linux"
    assert launch_kwargs["proxy"] == "http://user:pass@proxy.example:8080"


async def test_fetch_unknown_profile_falls_back_to_chrome_windows() -> None:
    mock_cls = _mock_camoufox_browser()
    with (
        patch.object(camoufox_integration, "_has_camoufox", True),
        patch(
            "pry.engine.camoufox_integration.AsyncCamoufox", create=True, return_value=mock_cls
        ) as mock_camoufox,
    ):
        result = await CamoufoxBrowser().fetch("https://example.com", profile="does-not-exist")

    assert result["success"] is True
    assert result["profile"] == "does-not-exist"  # echoes requested profile
    launch_kwargs = mock_camoufox.call_args.kwargs
    assert launch_kwargs["os"] == "windows"  # falls back to chrome_windows config
    assert launch_kwargs["browser"] == "chrome"
