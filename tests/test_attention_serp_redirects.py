"""Opaque Google /goto redirect resolution for SERP results."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

from typing import TYPE_CHECKING, Any

import httpx
import respx

if TYPE_CHECKING:
    import pytest

import pry.api.client as _client_module
from datasets.attention.serp import redirects

_GOTO = "https://www.google.com/goto"


@respx.mock
async def test_resolve_redirects_rewrites_url() -> None:
    respx.get(url__startswith=_GOTO).mock(
        return_value=httpx.Response(302, headers={"Location": "https://example.com/real"})
    )
    respx.get("https://example.com/real").mock(return_value=httpx.Response(200))
    out = await redirects._resolve_google_redirects(
        [{"position": 1, "url": _GOTO + "?url=tok"}], 10
    )
    assert out[0]["url"] == "https://example.com/real"


async def test_resolve_redirects_direct_urls_untouched() -> None:
    results = [{"position": 1, "url": "https://example.com/page"}]
    assert await redirects._resolve_google_redirects(results, 10) == results


async def test_resolve_redirects_respects_limit() -> None:
    results = [
        {"position": 1, "url": _GOTO + "?url=a"},
        {"position": 2, "url": _GOTO + "?url=b"},
    ]
    out = await redirects._resolve_google_redirects(results, 1)
    assert out[1]["url"] == _GOTO + "?url=b"


@respx.mock
async def test_resolve_redirects_http_error_keeps_url() -> None:
    respx.get(url__startswith=_GOTO).mock(side_effect=httpx.ConnectError("boom"))
    out = await redirects._resolve_google_redirects(
        [{"position": 1, "url": _GOTO + "?url=tok"}], 10
    )
    assert out[0]["url"] == _GOTO + "?url=tok"


async def test_resolve_redirects_unavailable_client_keeps_urls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def broken() -> Any:
        raise OSError("no client")

    monkeypatch.setattr(_client_module, "get_client", broken)
    results = [{"position": 1, "url": _GOTO + "?url=tok"}]
    assert await redirects._resolve_google_redirects(results, 10) == results
