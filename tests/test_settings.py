# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for unified Pry settings."""

import json
from pathlib import Path

import pytest

from settings import _NESTED_KEY_MAP, PrySettings


@pytest.fixture
def isolated_settings(tmp_path: Path) -> PrySettings:
    """Return a fresh settings instance with a temp config file."""
    config_file = tmp_path / "config.json"
    return PrySettings(config_file=config_file)


def test_settings_get_default(isolated_settings: PrySettings) -> None:
    assert isolated_settings.max_retries == 3
    assert isolated_settings.rate_limit_rpm == 120


def test_settings_proxy_resolution(isolated_settings: PrySettings) -> None:
    assert isolated_settings.resolved_proxy_url is None
    isolated_settings.proxy_enabled = True
    isolated_settings.proxy_url = "http://proxy.example:8080"
    assert isolated_settings.resolved_proxy_url == "http://proxy.example:8080"


def test_settings_tor_chain(isolated_settings: PrySettings) -> None:
    isolated_settings.tor_enabled = True
    isolated_settings.proxy_enabled = True
    isolated_settings.proxy_url = "http://proxy.example:8080"
    chain = isolated_settings.resolved_proxy_chain
    assert len(chain) == 2
    assert chain[0].startswith("socks5://")


def test_settings_to_api_dict_excludes_private(isolated_settings: PrySettings) -> None:
    data = isolated_settings.to_api_dict()
    assert "_proxy_chain" not in data
    assert "proxy" in data
    assert isinstance(data["proxy"]["enabled"], bool)


def test_settings_update_and_persist(isolated_settings: PrySettings) -> None:
    result = isolated_settings.update({"retry": {"max_attempts": 5}})
    assert result["status"] == "ok"
    assert isolated_settings.max_retries == 5
    assert isolated_settings.config_file.exists()
    saved = json.loads(isolated_settings.config_file.read_text(encoding="utf-8"))
    assert saved["retry"]["max_attempts"] == 5


def test_settings_load_config_file(tmp_path: Path) -> None:
    config_file = tmp_path / "config.json"
    config_file.write_text(
        json.dumps({"retry": {"max_attempts": 7}, "tor": {"enabled": True}}),
        encoding="utf-8",
    )
    s = PrySettings(config_file=config_file)
    assert s.max_retries == 7
    assert s.tor_enabled is True


def test_settings_legacy_env_vars(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("PROXY_URL", "http://legacy-proxy:8080")
    monkeypatch.setenv("TOR_ENABLED", "true")
    monkeypatch.setenv("MAX_RETRIES", "9")
    config_file = tmp_path / "config.json"
    s = PrySettings(config_file=config_file)
    assert s.proxy_url == "http://legacy-proxy:8080"
    assert s.tor_enabled is True
    assert s.max_retries == 9


def test_settings_enable_tor(isolated_settings: PrySettings) -> None:
    result = isolated_settings.enable_tor()
    assert result["status"] == "ok"
    assert isolated_settings.tor_enabled is True
    assert isolated_settings.proxy_enabled is True
    assert isolated_settings.proxy_url == "socks5://tor:9050"


def test_nested_key_map_complete() -> None:
    """Ensure every API-facing nested key maps to a settings attribute."""
    for attr in _NESTED_KEY_MAP.values():
        assert attr in PrySettings.model_fields, f"PrySettings missing {attr}"
