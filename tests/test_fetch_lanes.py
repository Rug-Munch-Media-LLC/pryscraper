"""Hermetic tests for the ordered fetch-lane ladder (no network, injected lanes)."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC

from __future__ import annotations

import asyncio
import time

from pry.engine import fetch_lanes as fl


class FakeLane:
    """Stand-in transport: fixed reply, optional delay or exception, call counter."""

    def __init__(self, name, reply=None, delay=0.0, exc=None):
        self.name, self.reply, self.delay, self.exc = name, reply, delay, exc
        self.calls = 0

    async def get(self, url, timeout_s):
        self.calls += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.exc:
            raise self.exc
        return self.reply


def ok(body="<html>2 results</html>"):
    return fl.Reply(fl.OK, 200, body)


def test_classify_vocabulary():
    assert fl.classify(200, "hello") == fl.OK
    assert fl.classify(429, "") == fl.RATE_LIMIT
    assert fl.classify(403, "") == fl.RATE_LIMIT
    assert fl.classify(503, "") == fl.RATE_LIMIT
    assert fl.classify(0, "") == fl.TIMEOUT
    assert fl.classify(403, "Disallowed by robots.txt") == fl.ROBOTS
    assert fl.classify(200, "please solve this CAPTCHA") == fl.CAPTCHA
    assert fl.classify(500, "") == fl.ERROR


async def test_default_ladder_order_and_lane_table():
    lanes = {name: FakeLane(name, ok()) for name in fl.LANE_NAMES}
    got = await fl.fetch("https://api.qwant.com/v3/search?q=x", timeout_ms=2000, resolver=lanes)
    assert got["status"] == fl.OK
    assert got["lane_used"] == "direct"
    assert [a["lane"] for a in got["attempts"]] == ["direct"]
    assert lanes["tor"].calls == 0
    table = fl.lane_table({"qwant": "api.qwant.com", "absent": "nope.example"})
    assert table["qwant"]["lane_used"] == "direct"
    assert table["qwant"]["lanes_tried"] == ["direct"]
    assert table["absent"]["lane_used"] is None


async def test_captcha_escalates_to_next_lane():
    lanes = {
        "direct": FakeLane("direct", fl.Reply(fl.CAPTCHA, 200, "captcha page")),
        "flaresolverr": FakeLane("flaresolverr", ok()),
    }
    got = await fl.fetch(
        "https://html.duckduckgo.com/html/?q=x",
        timeout_ms=2000,
        lanes=("direct", "flaresolverr"),
        resolver=lanes,
    )
    assert got["status"] == fl.OK
    assert got["lane_used"] == "flaresolverr"
    assert [a["lane"] for a in got["attempts"]] == ["direct", "flaresolverr"]
    assert got["body"].startswith("<html>")


async def test_rate_limit_escalates():
    lanes = {
        "direct": FakeLane("direct", fl.Reply(fl.RATE_LIMIT, 429, "")),
        "tor": FakeLane("tor", ok()),
    }
    got = await fl.fetch(
        "https://search.example/x", timeout_ms=2000, lanes=("direct", "tor"), resolver=lanes
    )
    assert got["lane_used"] == "tor"
    assert got["attempts"][0]["code"] == 429


async def test_robots_never_escalates():
    lanes = {
        "direct": FakeLane("direct", fl.Reply(fl.ROBOTS, 403, "Disallowed by robots.txt")),
        "tor": FakeLane("tor", ok()),
    }
    got = await fl.fetch(
        "https://example.com/private", timeout_ms=2000, lanes=("direct", "tor"), resolver=lanes
    )
    assert got["status"] == fl.ROBOTS
    assert got["lane_used"] is None
    assert [a["lane"] for a in got["attempts"]] == ["direct"]
    assert lanes["tor"].calls == 0, "a robots refusal must not be retried on another exit"


async def test_unavailable_lane_escalates_without_network():
    lanes = {
        "webshare": FakeLane("webshare", exc=fl.LaneUnavailable("pool empty")),
        "tor": FakeLane("tor", ok()),
    }
    got = await fl.fetch(
        "https://example.com/x", timeout_ms=2000, lanes=("webshare", "tor"), resolver=lanes
    )
    assert got["attempts"][0]["status"] == fl.UNAVAILABLE
    assert got["lane_used"] == "tor"


async def test_budget_exhaustion_stops_the_ladder():
    lanes = {"direct": FakeLane("direct", ok(), delay=5.0), "tor": FakeLane("tor", ok())}
    started = time.perf_counter()
    got = await fl.fetch(
        "https://example.com/slow", timeout_ms=250, lanes=("direct", "tor"), resolver=lanes
    )
    elapsed_ms = (time.perf_counter() - started) * 1000
    assert got["status"] == fl.TIMEOUT
    assert got["lane_used"] is None
    assert elapsed_ms < 900, "a dead lane must not extend the call past the budget"
    assert lanes["tor"].calls == 0


async def test_attempt_telemetry_per_lane():
    lanes = {
        "direct": FakeLane("direct", fl.Reply(fl.RATE_LIMIT, 429, "")),
        "webshare": FakeLane("webshare", exc=fl.LaneUnavailable("empty")),
        "tor": FakeLane("tor", ok()),
    }
    got = await fl.fetch(
        "https://example.com/t",
        timeout_ms=2000,
        lanes=("direct", "webshare", "tor"),
        resolver=lanes,
    )
    rows = got["attempts"]
    assert [r["lane"] for r in rows] == ["direct", "webshare", "tor"]
    assert [r["status"] for r in rows] == [fl.RATE_LIMIT, fl.UNAVAILABLE, fl.OK]
    assert [r["code"] for r in rows] == [429, 0, 200]
    assert all(isinstance(r["ms"], int) and r["ms"] >= 0 for r in rows)
