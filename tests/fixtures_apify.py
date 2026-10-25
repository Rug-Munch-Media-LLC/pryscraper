# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""In-memory doubles for the Apify actor tests (no SDK, no network).

The actor takes its SDK entry point and scraper by injection, so these doubles
are enough to drive the whole loop — no monkeypatching of module state.
"""

from __future__ import annotations

from typing import Any

from pry.actors.apify_actor.runner import main


class FakeLog:
    """Collects the actor's log calls instead of writing them."""

    def __init__(self) -> None:
        self.records: list[tuple[str, str, dict[str, Any]]] = []

    def _record(self, level: str, event: str, extra: dict[str, Any] | None = None) -> None:
        self.records.append((level, event, extra or {}))

    def info(self, event: str, extra: dict[str, Any] | None = None) -> None:
        self._record("info", event, extra)

    def warning(self, event: str, extra: dict[str, Any] | None = None) -> None:
        self._record("warning", event, extra)

    def error(self, event: str, extra: dict[str, Any] | None = None) -> None:
        self._record("error", event, extra)

    def debug(self, event: str, extra: dict[str, Any] | None = None) -> None:
        self._record("debug", event, extra)

    def events(self, level: str) -> list[str]:
        return [event for lvl, event, _ in self.records if lvl == level]


class FakeConfiguration:
    """Apify SDK 3.x proxy configuration shape."""

    proxy_password = "secret"
    proxy_hostname = "proxy.apify.com"
    proxy_port = 8000


class FakeActor:
    """Minimal stand-in for the Apify ``Actor`` async context manager."""

    def __init__(self, raw_input: dict[str, Any], configuration: Any = None) -> None:
        self.raw_input = raw_input
        self.configuration = configuration
        self.log = FakeLog()
        self.pushed: list[dict[str, Any]] = []
        self.state: dict[str, Any] = {}
        self.entered = False

    async def __aenter__(self) -> FakeActor:
        self.entered = True
        return self

    async def __aexit__(self, *exc: object) -> None:
        self.entered = False

    async def get_input(self) -> dict[str, Any]:
        return self.raw_input

    async def push_data(self, item: dict[str, Any]) -> None:
        self.pushed.append(item)

    async def set_value(self, key: str, value: dict[str, Any]) -> None:
        self.state[key] = value


class FakeScraper:
    """Replays queued scrape results and records the options it received."""

    def __init__(self, results: list[dict[str, Any]]) -> None:
        self.results = list(results)
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def scrape(self, url: str, options: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((url, options))
        return self.results.pop(0) if self.results else {"status": "error", "error": "empty"}


def ok(content: str = "body", html: str = "") -> dict[str, Any]:
    """A successful scraper result."""
    return {"status": "ok", "content": content, "raw_html": html, "method": "direct"}


async def run(actor: FakeActor, scraper: FakeScraper) -> FakeActor:
    """Drive one actor run with the injected scraper."""
    await main(actor=actor, scraper_factory=lambda: scraper)
    return actor
