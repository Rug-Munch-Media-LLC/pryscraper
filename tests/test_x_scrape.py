"""Offline tests for the X syndication adapters. No live calls in CI."""

from __future__ import annotations

import pathlib

import pytest

from pry.actors import x_parse, x_syndication, x_tweet

FIX = pathlib.Path(__file__).parent / "fixtures" / "x"
TIMELINE = FIX / "timeline_page.html"
TWEET = FIX / "tweet_result.json"


class _Resp:
    def __init__(self, status_code: int, text: str = "") -> None:
        self.status_code = status_code
        self.text = text


class _Client:
    """Minimal httpx.Client stand-in: one canned response, no network."""

    def __init__(self, resp: _Resp) -> None:
        self._resp = resp

    def get(self, url: str, **_kwargs) -> _Resp:
        return self._resp


@pytest.mark.skipif(not TIMELINE.exists(), reason="no recorded syndication fixture")
def test_normalize_extracts_tweets() -> None:
    tweets = x_parse.normalize_tweets(TIMELINE.read_text(), "elonmusk")
    assert tweets, "recorded fixture must yield at least one tweet"
    first = tweets[0]
    assert first["id"]
    assert first["text"]
    assert first["created_at"]
    assert set(first["metrics"]) == {"likes", "retweets", "replies", "quotes"}
    assert first["url"].startswith("https://x.com/")


def test_normalize_login_wall_returns_empty() -> None:
    assert x_parse.normalize_tweets("<html><body>Log in to X</body></html>", "jack") == []
    assert x_parse.normalize_tweets("", "jack") == []


def test_normalize_bad_json_returns_empty() -> None:
    html = '<script id="__NEXT_DATA__" type="application/json">{oops</script>'
    assert x_parse.normalize_tweets(html, "jack") == []


def test_fetch_ratelimit_refusal() -> None:
    env = x_syndication.fetch_profile_timeline("jack", client=_Client(_Resp(429)))
    assert env["ok"] is False
    assert env["error"]["code"] == "blocked.ratelimit"


def test_fetch_auth_refusal() -> None:
    env = x_syndication.fetch_profile_timeline("jack", client=_Client(_Resp(403)))
    assert env["ok"] is False
    assert env["error"]["code"] == "blocked.auth"


def test_fetch_invalid_handle_makes_no_request() -> None:
    class _Boom:
        def get(self, *_a, **_k):
            raise AssertionError("must not request an invalid handle")

    env = x_syndication.fetch_profile_timeline("bad handle!", client=_Boom())
    assert env["ok"] is False
    assert env["error"]["code"] == "no_data"


@pytest.mark.skipif(not TIMELINE.exists(), reason="no recorded syndication fixture")
def test_fetch_success_envelope() -> None:
    env = x_syndication.fetch_profile_timeline(
        "elonmusk", client=_Client(_Resp(200, TIMELINE.read_text()))
    )
    assert env["ok"] is True
    assert env["source"] == "syndication.timeline"
    assert env["data"]["count"] >= 1
    assert env["error"] is None


def test_tweet_success() -> None:
    env = x_tweet.fetch_tweet("20", client=_Client(_Resp(200, TWEET.read_text())))
    assert env["ok"] is True
    assert env["data"]["id"] == "20"
    assert env["data"]["text"]
    assert env["data"]["metrics"]["likes"] >= 0


def test_tweet_empty_body_is_soft_block() -> None:
    env = x_tweet.fetch_tweet("20", client=_Client(_Resp(200, "{}")))
    assert env["ok"] is False
    assert env["error"]["code"] == "blocked.ratelimit"


def test_tweet_non_json_is_refused() -> None:
    env = x_tweet.fetch_tweet("20", client=_Client(_Resp(200, "<html>nope")))
    assert env["ok"] is False
    assert env["error"]["code"] == "no_data"
