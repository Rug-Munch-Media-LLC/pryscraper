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

import pytest

from pry.engine import mega_search as ms


def _row(url: str, title: str = "T", snippet: str = "") -> dict[str, str]:
    return {"url": url, "title": title, "snippet": snippet}


def test_normalize_strips_scheme_www_and_trailing_slash() -> None:
    assert ms._normalize_url("https://www.Example.com/path/") == ms._normalize_url(
        "http://example.com/path"
    )


def test_normalize_drops_tracking_params() -> None:
    a = ms._normalize_url("https://x.com/p?utm_source=n&id=7")
    b = ms._normalize_url("https://x.com/p?id=7&fbclid=abc")
    assert a == b


def test_term_overlap_fraction() -> None:
    assert ms._term_overlap("python asyncio tutorial", "python asyncio guide") == pytest.approx(
        2 / 3
    )
    assert ms._term_overlap("python asyncio", "") == 0.0


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
    assert [r["url"] for r in ms._merge(grouped, "q")] == ["https://ok.com"]


@pytest.mark.asyncio
async def test_mega_search_reports_failed_legs(monkeypatch: pytest.MonkeyPatch) -> None:
    async def ok(query: str, n: int) -> list[dict[str, str]]:
        return [_row("https://ok.com")]

    async def boom(query: str, n: int) -> list[dict[str, str]]:
        raise RuntimeError("captcha")

    monkeypatch.setattr(ms, "_engine_func", lambda name: {"searxng": ok, "yahoo": boom}.get(name))
    out = await ms.mega_search("q", 5, engines=("searxng", "yahoo"))
    assert out["engines_ok"] == ["searxng"]
    assert out["engines_failed"] == ["yahoo"]
    assert out["results"][0]["url"] == "https://ok.com"


@pytest.mark.asyncio
async def test_empty_query_returns_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ms, "_engine_func", lambda name: None)
    assert await ms.mega_search("   ") == {}


def test_module_stays_under_size_cap() -> None:
    """Size gate: this module must stay under the 200-line cap."""
    from pathlib import Path

    source = Path(ms.__file__).read_text().splitlines()
    assert len(source) <= 200, f"mega_search.py is {len(source)} lines (cap 200)"
