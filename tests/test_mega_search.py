"""Tests for the consensus search aggregator.

These are offline: every engine is stubbed, so the suite asserts ranking and
dedup behaviour rather than live network behaviour.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

from pathlib import Path

import pytest

from pry.engine import mega_scoring as scoring, mega_search as ms
from pry.engine.url_key import url_key


def _row(url: str, title: str = "T", snippet: str = "") -> dict[str, str]:
    return {"url": url, "title": title, "snippet": snippet}


def test_normalize_strips_scheme_www_and_trailing_slash() -> None:
    assert url_key("https://www.Example.com/path/") == url_key("http://example.com/path")


def test_normalize_drops_tracking_params() -> None:
    a = url_key("https://x.com/p?utm_source=n&id=7")
    b = url_key("https://x.com/p?id=7&fbclid=abc")
    assert a == b


def test_term_overlap_fraction() -> None:
    assert scoring.term_overlap("python asyncio tutorial", "python asyncio guide") == pytest.approx(
        2 / 3
    )
    assert scoring.term_overlap("python asyncio", "") == 0.0


def test_consensus_outranks_single_engine_hit() -> None:
    grouped = {
        "searxng": [_row("https://a.com"), _row("https://solo.com")],
        "yahoo": [_row("https://a.com")],
    }
    ranked = ms._merge(grouped, "query")
    assert ranked[0]["url"] == "https://a.com"
    assert ranked[0]["consensus"] == 2
    assert ranked[-1]["consensus"] == 1


def test_duplicate_urls_collapse_and_keep_richest_payload() -> None:
    grouped = {
        "searxng": [_row("https://a.com", "short", "tiny")],
        "yahoo": [_row("https://www.a.com/", "a much longer title", "a far longer snippet")],
    }
    ranked = ms._merge(grouped, "query")
    assert len(ranked) == 1
    assert ranked[0]["title"] == "a much longer title"
    assert ranked[0]["snippet"] == "a far longer snippet"
    assert ranked[0]["consensus"] == 2


def test_non_http_rows_are_discarded() -> None:
    grouped = {"searxng": [_row("ftp://bad"), _row("https://ok.com")]}
    expected = ["https://ok.com"]
    assert [r["url"] for r in ms._merge(grouped, "q")] == expected


@pytest.mark.asyncio
async def test_mega_search_reports_failed_legs() -> None:
    async def ok(query: str, n: int) -> list[dict[str, str]]:
        return [_row("https://ok.com")]

    async def boom(query: str, n: int) -> list[dict[str, str]]:
        raise RuntimeError("captcha")

    def resolve(name: str) -> object | None:
        return {"searxng": ok, "yahoo": boom}.get(name)

    out = await ms.mega_search("q", 5, engines=("searxng", "yahoo"), resolve=resolve)
    expected = ["searxng"]
    assert out["engines_ok"] == expected
    expected_2 = ["yahoo"]
    assert out["engines_failed"] == expected_2
    assert out["results"][0]["url"] == "https://ok.com"


@pytest.mark.asyncio
async def test_empty_query_returns_empty() -> None:
    assert await ms.mega_search("   ", resolve=lambda name: None) == {}


def test_mega_search_owns_one_job() -> None:
    """mega_search delegates fan-out, scoring and merge; it must not re-implement them.

    This replaced a ``len(source) <= 200`` assertion, which was a line-count gate
    and not a design gate. The fleet standard names that failure mode directly
    (standards/fleet/MODULARITY-STANDARD.md, quoting MODULE-BOUNDARIES R4): an
    agent optimising for 199 lines extracts private helpers while the module
    still owns five jobs. It also made a legitimate 240-line single-purpose
    module look like a violation.

    The real invariant is ownership: composition lives here, and the three
    concerns it composes live in their own modules.
    """
    # Scoring is pure and testable without I/O, so it must not be inlined here.
    assert hasattr(scoring, "score")
    assert hasattr(scoring, "agreeing")
    assert hasattr(scoring, "MIN_CONSENSUS")
    # And this module must actually USE it rather than carry a second copy.
    source = Path(ms.__file__).read_text()
    assert "from pry.engine.mega_scoring import" in source
    assert "def _score(" not in source, "scoring was re-inlined into mega_search"
