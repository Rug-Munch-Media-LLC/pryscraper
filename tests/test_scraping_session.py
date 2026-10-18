# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for scraping_methods — PersistentSession warm-up and cookie reuse."""

from __future__ import annotations

import httpx

from pry.engine.scraping_methods import PersistentSession
from tests.support.scraping import ok_handler

# ── Session persistence / cookie warmer ─────────────────────────────────────


async def test_session_warmup_then_cookie_reuse() -> None:
    seen: list[httpx.Request] = []
    handler = ok_handler()

    def tracking_handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    async with PersistentSession(
        home_url="https://example.com/", transport=httpx.MockTransport(tracking_handler)
    ) as session:
        resp = await session.fetch("https://example.com/api/products")
    assert resp is not None
    expected = {"ok": True}
    assert resp.json() == expected
    assert session.is_warmed
    # Warm-up hit the homepage first. The validated IP is the CONNECT target
    # (DNS-rebinding pinning); the logical host survives in Host/SNI.
    assert seen[0].url.scheme == "https"
    assert seen[0].headers["host"] == "example.com"
    assert seen[0].url.path == "/"
    # Cookie collected during warm-up was sent on the API request.
    assert "sid=abc123" in (seen[-1].headers.get("cookie") or "")


async def test_session_reuses_cookies_across_calls() -> None:
    seen: list[httpx.Request] = []
    handler = ok_handler()

    def tracking_handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    session = PersistentSession(
        home_url="https://example.com/", transport=httpx.MockTransport(tracking_handler)
    )
    try:
        first = await session.fetch("https://example.com/api/a")
        second = await session.fetch("https://example.com/api/b")
        assert first is not None
        assert second is not None
        assert len(seen) == 3  # warmup + 2 API calls on ONE client
        assert all("sid=abc123" in (r.headers.get("cookie") or "") for r in seen[1:])
    finally:
        await session.close()


async def test_session_derives_home_from_first_fetch() -> None:
    seen: list[httpx.Request] = []
    handler = ok_handler()

    def tracking_handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    session = PersistentSession(transport=httpx.MockTransport(tracking_handler))
    try:
        resp = await session.fetch("https://example.com/api/v2/odds?market=ml")
        assert resp is not None
        assert seen[0].url.path == "/"  # derived homepage warm-up
        assert seen[-1].url.path == "/api/v2/odds"
        assert "sid=abc123" in (seen[-1].headers.get("cookie") or "")
    finally:
        await session.close()


async def test_session_warmup_failure_still_fetches() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/":
            raise httpx.ConnectError("no route to host", request=request)
        return httpx.Response(200, json={"ok": True})

    session = PersistentSession(
        home_url="https://example.com/", transport=httpx.MockTransport(handler)
    )
    try:
        assert await session.warmup() is False
        assert not session.is_warmed
        resp = await session.fetch("https://example.com/api/products")
        assert resp is not None
        expected = {"ok": True}
        assert resp.json() == expected
    finally:
        await session.close()


async def test_session_never_raises_on_transport_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    session = PersistentSession(
        home_url="https://example.com/", transport=httpx.MockTransport(handler)
    )
    try:
        assert await session.warmup() is False
        assert await session.fetch("https://example.com/api/products") is None
    finally:
        await session.close()


async def test_session_invalid_url_returns_none() -> None:
    session = PersistentSession(home_url="https://example.com/")
    try:
        assert await session.fetch("file:///etc/passwd") is None
        assert await session.fetch("") is None
    finally:
        await session.close()


async def test_session_cookies_snapshot() -> None:
    session = PersistentSession(
        home_url="https://example.com/", transport=httpx.MockTransport(ok_handler())
    )
    try:
        assert session.cookies() == {}
        await session.warmup()
        assert session.cookies().get("sid") == "abc123"
    finally:
        await session.close()
