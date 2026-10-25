"""SERP fetch tier: query building, pagination, 429/blocked paths, redirects.

Fixture-only — every HTTP call is respx-mocked and the browser ladder is a
fake, so nothing here touches the network.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

import sys
from typing import Any

import httpx
import pytest
import respx

import pry.api.client as _client_module
from datasets.attention import serp
from datasets.attention.serp import browser, fetch

_USABLE = "x" * 20001 + "<h3>result</h3>"
_SEARCH = "https://www.google.com/search"


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setattr(fetch, "RETRY_BASE", 0.0)
    monkeypatch.setattr(fetch, "MAX_BACKOFF", 0.0)
    _client_module.http_client = None
    yield
    _client_module.http_client = None


# ── query building + pagination ────────────────────────────────────────


def test_params_clamp_and_region() -> None:
    assert fetch._serp_params("q", 0)["num"] == "1"
    assert fetch._serp_params("q", 500)["num"] == "100"
    assert fetch._serp_params("q", 10) == {
        "q": "q",
        "num": "10",
        "hl": "en",
        "gl": "us",
        "pws": "0",
    }


def test_serp_url_encodes_query_and_clamps() -> None:
    url = serp._serp_url("bitcoin price", 250)
    assert url.startswith(_SEARCH + "?")
    assert "q=bitcoin+price" in url
    assert "num=100" in url


@respx.mock
async def test_fetch_sends_query_params_and_returns_html() -> None:
    route = respx.get(url__startswith=_SEARCH).mock(
        return_value=httpx.Response(200, text="<html>ok</html>")
    )
    assert await fetch._fetch_serp("bitcoin", 5) == "<html>ok</html>"
    params = route.calls[0].request.url.params
    assert params["q"] == "bitcoin"
    assert params["num"] == "5"
    assert params["pws"] == "0"


@respx.mock
async def test_fetch_429_retries_then_succeeds() -> None:
    route = respx.get(url__startswith=_SEARCH).mock(
        side_effect=[httpx.Response(429), httpx.Response(200, text="ok")]
    )
    assert await fetch._fetch_serp("bitcoin", 10) == "ok"
    assert route.call_count == 2


@respx.mock
async def test_fetch_429_exhausts_budget() -> None:
    route = respx.get(url__startswith=_SEARCH).mock(return_value=httpx.Response(429))
    assert await fetch._fetch_serp("bitcoin", 10) == ""
    assert route.call_count == fetch.MAX_RETRIES + 1


@respx.mock
async def test_fetch_4xx_is_permanent() -> None:
    route = respx.get(url__startswith=_SEARCH).mock(return_value=httpx.Response(404))
    assert await fetch._fetch_serp("bitcoin", 10) == ""
    assert route.call_count == 1


@respx.mock
async def test_fetch_transport_error_never_raises() -> None:
    respx.get(url__startswith=_SEARCH).mock(side_effect=httpx.ConnectError("boom"))
    assert await fetch._fetch_serp("bitcoin", 10) == ""


# ── usable-shape check + egress ladder ─────────────────────────────────


@pytest.mark.parametrize(
    ("html", "usable"),
    [("", False), ("<h3>x</h3>", False), ("x" * 20001, False), (_USABLE, True)],
)
def test_usable_serp_html_shape(html: str, usable: bool) -> None:
    assert browser._usable_serp_html(html) is usable


def test_proxy_pool_parses_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WEBSHARE_PROXY_LIST", "http://a:1, http://b:2 socks5://c\nhttp://d:4")
    assert browser._proxy_pool() == ["http://a:1", "http://b:2", "http://d:4"]


async def test_browser_tier_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "pry.engine.flaresolverr", None)
    assert await browser._fetch_serp_browser("q", 10) == ""


async def test_browser_ladder_rotates_egress(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str | None] = []

    async def fake_fetch(url: str, proxy: str | None = None) -> str:
        seen.append(proxy)
        return _USABLE if proxy == "http://p2:2" else "<html>blocked</html>"

    monkeypatch.setenv("WEBSHARE_PROXY_LIST", "http://p1:1 http://p2:2")
    monkeypatch.setattr("pry.engine.flaresolverr.fetch_via_flaresolverr", fake_fetch)
    assert await browser._fetch_serp_browser("q", 10) == _USABLE
    assert seen == [None, "http://p1:1", "http://p2:2"]


async def test_browser_ladder_all_blocked(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_fetch(url: str, proxy: str | None = None) -> str:
        return "<html>blocked</html>"

    monkeypatch.setattr("pry.engine.flaresolverr.fetch_via_flaresolverr", fake_fetch)
    assert await browser._fetch_serp_browser("q", 10) == ""


async def test_browser_ladder_swallows_tier_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str | None] = []

    async def fake_fetch(url: str, proxy: str | None = None) -> str:
        calls.append(proxy)
        if len(calls) == 1:
            raise RuntimeError("tier down")
        return _USABLE

    monkeypatch.setenv("WEBSHARE_PROXY_LIST", "http://p1:1")
    monkeypatch.setattr("pry.engine.flaresolverr.fetch_via_flaresolverr", fake_fetch)
    assert await browser._fetch_serp_browser("q", 10) == _USABLE
    assert calls == [None, "http://p1:1"]
