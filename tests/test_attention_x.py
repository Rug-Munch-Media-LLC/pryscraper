# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for the X/Twitter attention lane.

Covers SSR JSON extraction (modern + legacy schema, nearest-author
fallback, de-duplication), the DOM fallback, the never-raise contract,
login-wall reporting with no fabricated posts, session/egress masking,
the owner-key path used by internal Pry calls, and the
``GET /v1/attention/x/posts`` route.

All HTTP is mocked — no live network.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
import respx
from fastapi import FastAPI
from fastapi.testclient import TestClient

import datasets.attention.x_posts as x_posts
import datasets.attention.x_session as x_session
from datasets.attention.x_parse import parse_posts
from datasets.attention.x_session import XSession, resolve_proxy
from datasets.attention.x_templates import build_url, normalize_target
from pry.api.routers.data.attention import router as attention_router


def _result(
    tweet_id: str,
    handle: str = "jack",
    text: str = "hello world",
    *,
    modern: bool = True,
    with_author: bool = True,
) -> dict[str, Any]:
    """Build one ``tweet_results`` node shaped like X's SSR payload."""
    tweet: dict[str, Any] = {"rest_id": tweet_id, "views": {"count": 42}}
    if modern:
        tweet["details"] = {"full_text": text, "created_at_ms": 1142974214000}
        tweet["counts"] = {"favorite_count": 309039, "retweet_count": 124552}
    else:
        tweet["legacy"] = {
            "full_text": text,
            "created_at": "Thu Mar 21 20:50:14 +0000 2024",
            "favorite_count": 7,
            "in_reply_to_status_id_str": "19",
        }
    if with_author:
        tweet["core"] = {
            "user_results": {
                "result": {
                    "rest_id": "12",
                    "core": {"screen_name": handle, "name": handle.title()},
                    "relationship_counts": {"followers": 12535482},
                    "verification": {"is_blue_verified": True},
                }
            }
        }
    return {"rest_id": tweet_id, "result": tweet}


def _ssr_html(*results: dict[str, Any]) -> str:
    """Render a page whose script carries the escaped SSR JSON payload."""
    payload = {
        "data": {
            "timeline": {"instructions": [{"content": {"tweet_results": item}} for item in results]}
        }
    }
    escaped = json.dumps(payload).replace('"', '\\"')
    return f'<html><body><script nonce="n">window.$_TSR={escaped}</script></body></html>'


@pytest.fixture
def clean_session(monkeypatch: pytest.MonkeyPatch) -> XSession:
    """No credentials, no proxy — the anonymous public-page session."""
    session = XSession()
    monkeypatch.setattr(x_posts.XSession, "from_env", classmethod(lambda cls: session))
    monkeypatch.setattr(x_posts, "next_webshare_proxy", lambda domain=None: None)
    return session


def test_normalize_and_build_url() -> None:
    assert normalize_target("profile_timeline", "@jack") == "jack"
    assert normalize_target("status", "https://x.com/jack/status/20?s=20") == "20"
    assert normalize_target("profile_timeline", "not a handle!") == ""
    assert build_url("status", "20") == "https://x.com/i/status/20"
    with pytest.raises(ValueError, match="unknown kind"):
        build_url("nope", "x")


def test_parse_ssr_modern_schema_and_dedupe() -> None:
    html = _ssr_html(_result("20", text="just setting up my twttr"), _result("20"))
    posts, source = parse_posts(html)

    assert source == "ssr"
    assert len(posts) == 1
    post = posts[0]
    assert post["id"] == "20"
    assert post["text"] == "just setting up my twttr"
    assert post["created_at"] == "2006-03-21T20:50:14Z"
    assert post["author"] == {
        "id": "12",
        "handle": "jack",
        "name": "Jack",
        "followers": 12535482,
        "verified": True,
    }
    assert post["metrics"]["likes"] == 309039
    assert post["metrics"]["views"] == 42
    assert post["url"] == "https://x.com/jack/status/20"


def test_parse_legacy_schema_marks_reply() -> None:
    posts, source = parse_posts(_ssr_html(_result("21", modern=False)))

    assert source == "ssr"
    assert posts[0]["created_at"] == "2024-03-21T20:50:14Z"
    assert posts[0]["metrics"]["likes"] == 7
    assert posts[0]["is_reply"] is True
    assert posts[0]["in_reply_to_id"] == "19"


def test_parse_uses_nearest_user_results_when_core_absent() -> None:
    node = _result("30", with_author=False)
    node["result"]["context"] = {
        "user_results": {"result": {"rest_id": "99", "core": {"screen_name": "nearest"}}}
    }
    posts, _ = parse_posts(_ssr_html(node))

    assert posts[0]["author"]["handle"] == "nearest"
    assert posts[0]["author"]["id"] == "99"


def test_parse_dom_fallback() -> None:
    html = (
        '<article data-testid="tweet">'
        '<a href="/jack/status/20"></a>'
        '<div data-testid="User-Name"><a href="/jack">jack</a></div>'
        '<div data-testid="tweetText">just setting up my twttr</div>'
        '<time datetime="2006-03-21T20:50:14.000Z"></time>'
        "</article>"
    )
    posts, source = parse_posts(html)

    assert source == "dom"
    assert posts[0]["id"] == "20"
    assert posts[0]["text"] == "just setting up my twttr"
    assert posts[0]["author"]["handle"] == "jack"
    assert posts[0]["metrics"]["likes"] == 0


@respx.mock
async def test_get_posts_profile_returns_ssr_posts(clean_session: XSession) -> None:
    respx.get("https://x.com/jack").mock(
        return_value=httpx.Response(200, text=_ssr_html(_result("20")))
    )

    result = await x_posts.get_posts("profile_timeline", "@jack", limit=5)

    assert "error" not in result
    assert result["count"] == 1
    assert result["source"] == "ssr"
    assert result["authenticated"] is False
    assert result["posts"][0]["author"]["handle"] == "jack"


@respx.mock
async def test_get_posts_status_keeps_only_focal_tweet(clean_session: XSession) -> None:
    html = _ssr_html(_result("20"), _result("21", handle="replyguy"))
    respx.get("https://x.com/i/status/20").mock(return_value=httpx.Response(200, text=html))

    result = await x_posts.get_posts("status", "20")

    assert result["count"] == 1
    assert result["posts"][0]["id"] == "20"


async def test_get_posts_search_reports_login_wall(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _wall(url: str, session: XSession) -> tuple[str, str, str]:
        return "", "https://x.com/i/jf/onboarding/web?mode=login", ""

    monkeypatch.setattr(x_posts, "_fetch_with_egress", _wall)

    result = await x_posts.get_posts("search", "bitcoin")

    assert result["error"] == "login_wall"
    assert result["posts"] == []
    assert result["count"] == 0
    assert "logged-in session" in result["reason"]


async def test_get_posts_search_without_posts_is_login_wall(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _shell(url: str, session: XSession) -> tuple[str, str, str]:
        return "<html><title>X</title></html>", url, ""

    monkeypatch.setattr(x_posts, "_fetch_with_egress", _shell)

    result = await x_posts.get_posts("search", "bitcoin")

    assert result["error"] == "login_wall"
    assert result["posts"] == []


async def test_get_posts_never_raises_on_transport_error(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fail(url: str, session: XSession) -> tuple[str, str, str]:
        return "", url, "ConnectError: boom"

    monkeypatch.setattr(x_posts, "_fetch_with_egress", _fail)

    result = await x_posts.get_posts("profile_timeline", "jack")

    assert result["error"] == "fetch_failed"
    assert result["posts"] == []
    assert result["detail"] == "ConnectError: boom"


async def test_get_posts_rejects_bad_input(clean_session: XSession) -> None:
    assert (await x_posts.get_posts("nope", "jack"))["error"] == "unknown_kind"
    assert (await x_posts.get_posts("profile_timeline", "@@@"))["error"] == "invalid_target"


def test_session_masks_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("X_AUTH_TOKEN", "super-secret-auth")
    monkeypatch.setenv("X_CT0", "csrf-value")
    monkeypatch.setenv("X_COOKIE_HEADER", "")
    monkeypatch.setattr(x_session, "resolve_proxy", lambda raw: None)

    session = XSession.from_env()
    masked = session.masked()

    assert session.authenticated is True
    assert session.headers()["Cookie"] == "auth_token=super-secret-auth; ct0=csrf-value"
    assert "super-secret-auth" not in json.dumps(masked)
    assert "csrf-value" not in json.dumps(masked)
    assert masked["has_auth_token"] is True


def test_proxy_webshare_delegates_to_shared_pool(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(
        __import__("sys").modules,
        "pry.engine.webshare_proxy",
        type("M", (), {"next_webshare_proxy": staticmethod(lambda domain=None: "http://u:p@h:1")}),
    )

    assert resolve_proxy("webshare") == "http://u:p@h:1"
    assert resolve_proxy("http://literal:8080") == "http://literal:8080"
    assert resolve_proxy("") is None


def test_owner_key_recognised_for_internal_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    from pry.payments.x402_middleware.owner import owner_request

    monkeypatch.setenv("PRY_API_KEY", "owner-key")

    bearer = {b"authorization": b"Bearer owner-key"}
    api_key = {b"x-api-key": b"owner-key"}
    stranger = {b"authorization": b"Bearer someone-else"}

    assert owner_request(bearer) is True
    assert owner_request(api_key) is True
    assert owner_request(stranger) is False
    assert owner_request({}) is False


def test_router_serves_x_posts(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake(kind: str, target: str, limit: int = 20) -> dict[str, Any]:
        return {
            "kind": kind,
            "target": target,
            "url": "https://x.com/jack",
            "posts": [{"id": "20"}],
            "count": 1,
            "source": "ssr",
        }

    monkeypatch.setattr(x_posts, "get_posts", _fake)
    app = FastAPI()
    app.include_router(attention_router)

    response = TestClient(app).get(
        "/v1/attention/x/posts", params={"kind": "profile_timeline", "target": "jack"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["data"]["count"] == 1
    assert body["data"]["target"] == "jack"


def test_router_reports_lane_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake(kind: str, target: str, limit: int = 20) -> dict[str, Any]:
        return {"kind": kind, "target": target, "posts": [], "count": 0, "error": "login_wall"}

    monkeypatch.setattr(x_posts, "get_posts", _fake)
    app = FastAPI()
    app.include_router(attention_router)

    body = (
        TestClient(app)
        .get("/v1/attention/x/posts", params={"kind": "search", "target": "bitcoin"})
        .json()
    )

    assert body["success"] is False
    assert body["data"]["error"] == "login_wall"
