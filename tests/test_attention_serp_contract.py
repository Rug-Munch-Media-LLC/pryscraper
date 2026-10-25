"""AI Overview / PAA shapes and the scrape contract (never raises)."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import pytest

from datasets.attention import serp
from tests.serp_fixtures import A_HTML, AI_CLASS, AI_LABEL, PAA_LABEL, PAA_LEGACY, root

# ── AI Overview shapes ─────────────────────────────────────────────────


def test_ai_overview_class_strategy() -> None:
    assert serp._extract_ai_overview(root(AI_CLASS)) == "Supply and demand."


def test_ai_overview_label_strategy() -> None:
    assert (
        serp._extract_ai_overview(root(AI_LABEL))
        == "Bitcoin uses proof of work to secure its ledger."
    )


def test_ai_overview_truncates_long_text() -> None:
    html = "<html><body><div><span>AI Overview " + "z" * 3000 + "</span></div></body></html>"
    assert len(serp._extract_ai_overview(root(html)) or "") == 2000


def test_ai_overview_absent() -> None:
    assert serp._extract_ai_overview(root("<html><body><p>no</p></body></html>")) is None


# ── People Also Ask shapes ─────────────────────────────────────────────


def test_paa_legacy_strategy() -> None:
    assert serp._extract_paa(root(PAA_LEGACY)) == [
        "What is Bitcoin?",
        "Who created Bitcoin?",
    ]


def test_paa_label_strategy() -> None:
    assert serp._extract_paa(root(PAA_LABEL)) == [
        "Is Bitcoin legal?",
        "How is Bitcoin mined?",
    ]


def test_paa_absent() -> None:
    assert serp._extract_paa(root("<html><body><p>none</p></body></html>")) == []


def test_paa_label_without_headings() -> None:
    html = "<html><body><div><span>People also ask</span><p>nothing</p></div></body></html>"
    assert serp._extract_paa(root(html)) == []


def test_to_root_returns_none_on_bad_input() -> None:
    assert serp._to_root(123) is None  # type: ignore[arg-type]


# ── scrape contract ────────────────────────────────────────────────────


async def test_serp_empty_query_contract() -> None:
    assert await serp.serp("   ") == {
        "query": "   ",
        "results": [],
        "ai_overview": None,
        "paa": [],
        "error": "empty query",
    }


async def test_serp_empty_response_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    async def no_html(query: str, num: int) -> str:
        return ""

    monkeypatch.setattr(serp, "_fetch_serp", no_html)
    result = await serp.serp("bitcoin")
    assert result["error"] == "empty response"
    assert result["results"] == []


async def test_serp_blocked_page_falls_back_to_browser(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def blocked(query: str, num: int) -> str:
        return "<html><body>blocked</body></html>"

    async def browser_ok(query: str, num: int) -> str:
        return A_HTML

    monkeypatch.setattr(serp, "_fetch_serp", blocked)
    monkeypatch.setattr(serp, "_fetch_serp_browser", browser_ok)
    result = await serp.serp("bitcoin", num=5)
    assert "error" not in result
    assert [r["url"] for r in result["results"]] == ["https://example.com/bitcoin"]


async def test_serp_both_tiers_blocked_keeps_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def blocked(query: str, num: int) -> str:
        return "<html><body>blocked</body></html>"

    async def browser_blocked(query: str, num: int) -> str:
        return ""

    monkeypatch.setattr(serp, "_fetch_serp", blocked)
    monkeypatch.setattr(serp, "_fetch_serp_browser", browser_blocked)
    result = await serp.serp("bitcoin")
    assert set(result) == {"query", "results", "ai_overview", "paa"}
    assert result["results"] == []


async def test_serp_success_shape_and_pagination(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[tuple[str, int]] = []

    async def fetch(query: str, num: int) -> str:
        seen.append((query, num))
        return A_HTML

    monkeypatch.setattr(serp, "_fetch_serp", fetch)
    result = await serp.serp("  bitcoin  ", num=3)
    assert seen == [("bitcoin", 3)]
    assert result["query"] == "  bitcoin  "
    assert len(result["results"]) == 1
    assert result["ai_overview"] is None
    assert result["paa"] == []


async def test_serp_extraction_error_is_contained(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fetch(query: str, num: int) -> str:
        return A_HTML

    def boom(root_node: Any, num: int) -> list[dict[str, Any]]:
        raise TypeError("extractor broke")

    monkeypatch.setattr(serp, "_fetch_serp", fetch)
    monkeypatch.setattr(serp, "_extract_results", boom)
    result = await serp.serp("bitcoin")
    assert result["error"] == "extractor broke"
    assert result["results"] == []


async def test_serp_redirect_resolution_uses_num_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[int] = []

    async def fetch(query: str, num: int) -> str:
        return A_HTML

    async def resolve(results: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
        seen.append(limit)
        return results

    monkeypatch.setattr(serp, "_fetch_serp", fetch)
    monkeypatch.setattr(serp, "_resolve_google_redirects", resolve)
    await serp.serp("bitcoin", num=7)
    assert seen == [7]
