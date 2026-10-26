"""Hermetic tests for the API-backed Webshare pool (no network, temp cache)."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC

from __future__ import annotations

import pytest

from pry.engine import webshare_api as wapi, webshare_cache as wcache, webshare_pool as wp


class FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def row(i, host=None):
    return {
        "proxy_address": host or f"10.0.0.{i}",
        "port": 6000 + i,
        "username": f"u{i}",
        "password": f"pw{i}",
        "valid": True,
    }


def _reset():
    wp.reset_cache()


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(wcache, "CACHE_PATH", tmp_path / "pool.json")
    monkeypatch.setattr(wapi, "KEY_FILE", tmp_path / "absent.env")
    monkeypatch.setattr(wp, "TTL_S", 3600.0)
    monkeypatch.setenv("WEBSHARE_API_KEY", "sk_test_SECRET_123")
    _reset()
    yield
    _reset()


def test_paginates_to_completion(monkeypatch):
    pages = {
        1: {"count": 150, "results": [row(i) for i in range(100)]},
        2: {"count": 150, "results": [row(i) for i in range(100, 150)]},
    }
    seen = []

    def fake_get(url, **kwargs):
        seen.append(kwargs["params"]["page"])
        return FakeResp(pages[kwargs["params"]["page"]])

    monkeypatch.setattr(wapi.httpx, "get", fake_get)
    assert wp.pool_size() == 150
    assert seen == [1, 2]


def test_cache_ttl_serves_without_network(monkeypatch):
    calls = []
    monkeypatch.setattr(
        wp, "fetch_proxies", lambda key, timeout: calls.append(key) or [row(1), row(2)]
    )
    assert wp.pool_size() == 2
    assert wp.pool_size() == 2
    assert len(calls) == 1
    _reset()  # a new process over the same disk cache
    assert wp.pool_size() == 2
    assert len(calls) == 1


def test_expired_cache_refetches(monkeypatch):
    monkeypatch.setattr(wp, "fetch_proxies", lambda key, timeout: [row(1)])
    assert wp.pool_size() == 1
    wp._STATE["fetched_at"] = 0.0
    monkeypatch.setattr(wp, "fetch_proxies", lambda key, timeout: [row(1), row(2)])
    assert wp.pool_size() == 2


def test_mark_bad_skips_for_ttl(monkeypatch):
    monkeypatch.setattr(wp, "fetch_proxies", lambda key, timeout: [row(1), row(2)])
    wp.pool_size()
    host = wp.next_proxy().split("@")[-1].split(":")[0]
    wp.mark_bad(host, ttl_s=60)
    assert all(host not in wp.next_proxy() for _ in range(4))
    wp._STATE["bad"][host] = 0.0  # cooldown lapsed
    assert any(host in wp.next_proxy() for _ in range(2))


def test_tight_budget_never_hits_the_network(monkeypatch):
    monkeypatch.setattr(wp, "fetch_proxies", lambda key, timeout: [row(1)])
    assert wp.pool_size() == 1
    wp._STATE["fetched_at"] = 0.0

    def boom(*_a, **_k):
        raise AssertionError("network call under a tight budget")

    monkeypatch.setattr(wp, "fetch_proxies", boom)
    assert wp.pool_size(budget_s=0.5) == 1


def test_no_secret_in_logs(monkeypatch, caplog):
    caplog.set_level("DEBUG")
    monkeypatch.setattr(wp, "fetch_proxies", lambda key, timeout: [row(7, host="192.0.2.7")])
    wp.pool_size()
    wp.mark_bad("192.0.2.7")
    text = caplog.text
    assert "sk_test_SECRET_123" not in text
    assert "pw7" not in text
    assert "192.0.2.7" not in text


def test_api_key_absent_is_not_an_error(monkeypatch):
    monkeypatch.delenv("WEBSHARE_API_KEY", raising=False)
    monkeypatch.setattr(wp, "fetch_proxies", lambda key, timeout: [row(1)])
    assert wp.pool_size() == 0
    assert wp.next_proxy() is None
