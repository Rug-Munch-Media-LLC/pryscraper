# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for the Webshare residential proxy pool loader."""

from collections.abc import Iterator

import pytest

from pry.engine import webshare_proxy
from pry.engine.proxy_manager import ProxyManager
from pry.engine.webshare_proxy import (
    WEBSHARE_PROXY_LIST_ENV,
    clear_cache,
    load_webshare_proxies,
    mask_proxy_url,
    next_webshare_proxy,
    parse_proxy_list,
    reset_rotation,
)

_SAMPLE = (
    "http://user:pass@10.0.0.1:8080 http://user:pass@10.0.0.2:8080 http://user:pass@10.0.0.3:8080"
)


@pytest.fixture(autouse=True)
def _clean_webshare_cache(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Isolate the module-level cache + rotation state per test."""
    monkeypatch.delenv(WEBSHARE_PROXY_LIST_ENV, raising=False)
    clear_cache()
    reset_rotation()
    yield
    clear_cache()
    reset_rotation()


def test_parse_proxy_list_space_separated() -> None:
    parsed = parse_proxy_list(_SAMPLE)
    assert len(parsed) == 3
    assert parsed[0] == "http://user:pass@10.0.0.1:8080"


def test_parse_proxy_list_newlines_and_whitespace() -> None:
    raw = "http://a:b@1.1.1.1:80\n\n  http://c:d@2.2.2.2:80  \n"
    expected = ["http://a:b@1.1.1.1:80", "http://c:d@2.2.2.2:80"]
    assert parse_proxy_list(raw) == expected


def test_parse_proxy_list_empty() -> None:
    assert parse_proxy_list("") == []
    assert parse_proxy_list("   \n  ") == []


def test_load_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(WEBSHARE_PROXY_LIST_ENV, _SAMPLE)
    clear_cache()
    pool = load_webshare_proxies()
    assert len(pool) == 3
    assert webshare_proxy.webshare_source() == "env"


def test_load_empty_when_unset_and_no_gopass(monkeypatch: pytest.MonkeyPatch) -> None:
    # conftest sets PRY_SECRET_BACKEND=env, so the gopass fallback is skipped.
    monkeypatch.setenv("PRY_SECRET_BACKEND", "env")
    clear_cache()
    assert load_webshare_proxies() == []
    assert webshare_proxy.webshare_source() == "none"


def test_load_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(WEBSHARE_PROXY_LIST_ENV, _SAMPLE)
    clear_cache()
    first = load_webshare_proxies()
    # Changing env after the first load must NOT refresh the cache.
    monkeypatch.setenv(WEBSHARE_PROXY_LIST_ENV, "http://x:y@9.9.9.9:80")
    assert load_webshare_proxies() == first


def test_next_proxy_round_robin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(WEBSHARE_PROXY_LIST_ENV, _SAMPLE)
    clear_cache()
    seen = [next_webshare_proxy() for _ in range(4)]
    expected = [
        "http://user:pass@10.0.0.1:8080",
        "http://user:pass@10.0.0.2:8080",
        "http://user:pass@10.0.0.3:8080",
        "http://user:pass@10.0.0.1:8080",
    ]
    assert seen == expected


def test_next_proxy_empty_pool(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRY_SECRET_BACKEND", "env")
    clear_cache()
    assert next_webshare_proxy() is None


def test_mask_proxy_url() -> None:
    assert mask_proxy_url("http://user:pass@10.0.0.1:8080") == "http://user:***@10.0.0.1:8080"
    assert mask_proxy_url("http://user@10.0.0.1:8080") == "http://user:***@10.0.0.1:8080"
    assert mask_proxy_url("http://10.0.0.1:8080") == "http://10.0.0.1:8080"


def test_proxy_manager_webshare_pool(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv(WEBSHARE_PROXY_LIST_ENV, _SAMPLE)
    clear_cache()
    pm = ProxyManager(data_dir=tmp_path)
    info = pm.webshare_pool_info()
    assert info["count"] == 3
    assert info["source"] == "env"
    # Credentials are masked in the pool metadata.
    assert all(":***@" in p for p in info["proxies"])
    assert pm.webshare_pool() == load_webshare_proxies()


def test_auto_configure_from_env_selects_webshare(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setenv(WEBSHARE_PROXY_LIST_ENV, _SAMPLE)
    clear_cache()
    pm = ProxyManager(data_dir=tmp_path)
    assert pm.active_config.provider == "webshare"
    url = pm.get_proxy_url()
    assert url == "http://user:pass@10.0.0.1:8080"


def test_auto_configure_not_triggered_without_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setenv("PRY_SECRET_BACKEND", "env")
    clear_cache()
    pm = ProxyManager(data_dir=tmp_path)
    assert pm.active_config.provider == "free"
    assert pm.get_proxy_url() is None
