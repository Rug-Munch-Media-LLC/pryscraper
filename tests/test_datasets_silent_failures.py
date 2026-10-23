# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Silent-failure regression tests for the datasets fetch paths.

Every fetch helper in this slice fails closed (``None`` / ``[]``) when an
upstream answer is unusable. Failing closed is correct; failing closed without
a trace is not — an operator could not tell "no data today" from "every
upstream is returning garbage".

These tests pin all three halves of the contract:

* the failure still fails closed (no exception escapes to the caller),
* the failure is logged with the url/params and the error,
* a genuine ``ValueError`` from our own code is no longer swallowed as
  "no data" (the narrowing from ``ValueError`` to ``UpstreamPayloadError``).

All HTTP is mocked with respx — no live network.
"""

from __future__ import annotations

import logging

import httpx
import pytest
import respx

import datasets.sports_data.props_http as props_http
import datasets.sports_data.scores as scores
import datasets.sports_data.stats as stats
from datasets.shape_error import UpstreamPayloadError

_ODDS_EVENT_URL = "https://api.the-odds-api.com/v4/sports/basketball_nba/events"
_SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"
_STATS_URL = "https://site.web.api.espn.com/apis/common/v3/sports/basketball/nba/athletes/1/stats"


def _warnings(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [record for record in caplog.records if record.levelno >= logging.WARNING]


def _messages(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [record.getMessage() for record in _warnings(caplog)]


def _error_of(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [str(record.__dict__.get("error", "")) for record in _warnings(caplog)]


# ── shape error type ───────────────────────────────────────────────────
def test_upstream_payload_error_is_a_value_error() -> None:
    """Callers written against ``except ValueError`` keep working."""
    assert issubclass(UpstreamPayloadError, ValueError)


# ── sports props ───────────────────────────────────────────────────────
@respx.mock
async def test_props_wrong_shape_returns_none_and_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A 200 response with a JSON scalar is an upstream fault, not silence."""
    caplog.set_level(logging.WARNING)
    respx.get(_ODDS_EVENT_URL).mock(return_value=httpx.Response(200, json="nope"))
    assert await props_http.fetch_json(_ODDS_EVENT_URL) is None
    assert "sports_props_fetch_failed" in _messages(caplog)
    assert any("not an object or array" in error for error in _error_of(caplog))


@respx.mock
async def test_props_invalid_json_returns_none_and_logs_url(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Truncated JSON is an upstream fault, and the log must name the url."""
    caplog.set_level(logging.WARNING)
    respx.get(_ODDS_EVENT_URL).mock(
        return_value=httpx.Response(
            200, content=b"{not-json", headers={"content-type": "application/json"}
        )
    )
    assert await props_http.fetch_json(_ODDS_EVENT_URL) is None
    urls = [record.__dict__.get("url") for record in _warnings(caplog)]
    assert _ODDS_EVENT_URL[:120] in urls


# ── ESPN scoreboard ────────────────────────────────────────────────────
@respx.mock
async def test_scoreboard_wrong_shape_returns_none_and_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING)
    respx.get(_SCOREBOARD_URL).mock(return_value=httpx.Response(200, json=["not", "an", "object"]))
    assert await scores._fetch_json(_SCOREBOARD_URL) is None
    assert "espn_scoreboard_fetch_failed" in _messages(caplog)


# ── ESPN athlete stats ─────────────────────────────────────────────────
@respx.mock
async def test_stats_invalid_json_returns_none_and_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING)
    respx.get(_STATS_URL).mock(
        return_value=httpx.Response(
            200, content=b"<html>rate limited</html>", headers={"content-type": "application/json"}
        )
    )
    assert await stats._fetch_json(_STATS_URL) is None
    assert "espn_stats_fetch_failed" in _messages(caplog)


# ── narrowing: a real ValueError must surface ──────────────────────────
@respx.mock
async def test_genuine_value_error_is_not_swallowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only UpstreamPayloadError is a "no data" signal — not every ValueError."""
    respx.get(_SCOREBOARD_URL).mock(return_value=httpx.Response(200, json={"events": []}))

    def _explode(_self: httpx.Response, **_kwargs: object) -> object:
        raise ValueError("bug in our own parsing code")

    with monkeypatch.context() as patch_ctx:
        patch_ctx.setattr(httpx.Response, "json", _explode)
        with pytest.raises(ValueError, match="bug in our own parsing code"):
            await scores._fetch_json(_SCOREBOARD_URL)


# ── kayak embedded JSON ────────────────────────────────────────────────
def test_kayak_invalid_embedded_json_logs_and_returns_none(
    caplog: pytest.LogCaptureFixture,
) -> None:
    import datasets.travel.hotels_kayak as kayak

    caplog.set_level(logging.WARNING)
    html = 'window.__data = {"a": 1,} ;'
    assert kayak._extract_embedded_object(html, "window.__data = ") is None
    assert "kayak_embedded_json_invalid" in _messages(caplog)
