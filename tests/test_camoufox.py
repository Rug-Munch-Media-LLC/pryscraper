# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for Camoufox integration."""

from camoufox_integration import CamoufoxBrowser


def test_camoufox_profiles() -> None:
    profiles = CamoufoxBrowser.list_profiles()
    assert "chrome_windows" in profiles
    assert "firefox_windows" in profiles
    assert "firefox_linux" in profiles
    assert len(profiles) >= 4


def test_camoufox_init() -> None:
    b = CamoufoxBrowser()
    assert b.default_profile in CamoufoxBrowser.DEFAULT_CONFIGS
    assert "screen" in CamoufoxBrowser.DEFAULT_CONFIGS["chrome_windows"]
    assert "os" in CamoufoxBrowser.DEFAULT_CONFIGS["chrome_windows"]


def test_camoufox_config_completeness() -> None:
    for _name, config in CamoufoxBrowser.DEFAULT_CONFIGS.items():
        assert "headless" in config
        assert "os" in config
        assert "browser" in config
        assert "screen" in config
        assert "window" in config
        # Screen should be realistic
        sx, sy = config["screen"]
        assert sx >= 1024
        assert sy >= 768
        wx, wy = config["window"]
        assert wx <= sx
        assert wy <= sy
