"""Hermetic tests: the Webshare lane escalates once and cools bad endpoints."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC

from __future__ import annotations

import httpx

from pry.engine import fetch_lane_impl as impl, fetch_lanes as fl


class SeqLane:
    def __init__(self, name, replies):
        self.name, self.replies, self.calls = name, list(replies), 0

    async def get(self, url, timeout_s):
        self.calls += 1
        return self.replies.pop(0)


class FakeClient:
    """Async-context client stub: one canned response, no network."""

    def __init__(self, resp):
        self._resp = resp

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False

    async def get(self, url):
        return self._resp


def proxied(marked):
    return impl.Proxied(
        "webshare", lambda _b=None: "http://u:p@192.0.2.9:6001", on_bad=marked.append
    )


def _rate_limited(_resp):
    return fl.Reply(fl.RATE_LIMIT, 429, "")


def _connect_error(self, timeout_s):
    raise httpx.ConnectError("refused")


async def test_webshare_rate_limit_marks_the_endpoint(monkeypatch):
    marked = []
    monkeypatch.setattr(impl.Direct, "_reply", staticmethod(_rate_limited))
    monkeypatch.setattr(impl.Direct, "_client", lambda self, timeout_s: FakeClient(object()))
    reply = await proxied(marked).get("https://example.com/", 1.0)
    assert reply.status == fl.RATE_LIMIT
    assert marked == ["192.0.2.9"]


async def test_ladder_escalates_webshare_then_wins(monkeypatch):
    marked = []
    monkeypatch.setattr(impl.Direct, "_reply", staticmethod(_rate_limited))
    monkeypatch.setattr(impl.Direct, "_client", lambda self, timeout_s: FakeClient(object()))
    lanes = {
        "direct": SeqLane("direct", [fl.Reply(fl.RATE_LIMIT, 429, "")]),
        "webshare": proxied(marked),
        "flaresolverr": SeqLane("flaresolverr", [fl.Reply(fl.OK, 200, "<html>ok</html>")]),
    }
    got = await fl.fetch(
        "https://example.com/",
        lanes=("direct", "webshare", "flaresolverr"),
        timeout_ms=2000,
        resolver=lanes,
    )
    assert got["lane_used"] == "flaresolverr"
    assert [a["lane"] for a in got["attempts"]] == ["direct", "webshare", "flaresolverr"]
    assert [a["lane"] for a in got["attempts"]].count("webshare") == 1
    assert marked == ["192.0.2.9"]


async def test_transport_failure_escalates_exactly_once(monkeypatch):
    marked = []
    monkeypatch.setattr(impl.Direct, "_client", _connect_error)
    lanes = {
        "direct": SeqLane("direct", [fl.Reply(fl.RATE_LIMIT, 429, "")]),
        "webshare": proxied(marked),
        "flaresolverr": SeqLane("flaresolverr", [fl.Reply(fl.OK, 200, "ok")]),
    }
    got = await fl.fetch(
        "https://example.com/",
        lanes=("direct", "webshare", "flaresolverr"),
        timeout_ms=2000,
        resolver=lanes,
    )
    assert [a["status"] for a in got["attempts"]] == [fl.RATE_LIMIT, fl.UNAVAILABLE, fl.OK]
    assert marked == ["192.0.2.9"]


async def test_robots_is_terminal_on_every_lane():
    lanes = {
        name: SeqLane(name, [fl.Reply(fl.ROBOTS, 200, "Disallowed by robots.txt")])
        for name in ("direct", "webshare", "flaresolverr")
    }
    got = await fl.fetch(
        "https://example.com/x",
        lanes=("direct", "webshare", "flaresolverr"),
        timeout_ms=1000,
        resolver=lanes,
    )
    assert got["status"] == fl.ROBOTS
    assert lanes["webshare"].calls == 0
    assert lanes["flaresolverr"].calls == 0
