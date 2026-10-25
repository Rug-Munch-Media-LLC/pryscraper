"""SERP extraction against hosts that raise or expose non-element nodes.

Google's markup changes without notice; every extractor must degrade to
empty output (never raise) when a cssselect/iter call fails.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from datasets.attention import serp
from datasets.attention.serp import text as text_mod


class RaisingRoot:
    """Stand-in root whose selector/iteration APIs fail."""

    def cssselect(self, selector: str) -> list[Any]:
        raise ValueError(f"bad selector: {selector}")

    def iter(self) -> Any:
        raise ValueError("bad iter")


class OpaqueNodes:
    """Root whose iteration yields nodes with non-string tags."""

    def cssselect(self, selector: str) -> list[Any]:
        return []

    def iter(self) -> Any:
        yield SimpleNamespace(tag=1, text="AI Overview ignored")


def test_organic_degrades_on_selector_failure() -> None:
    assert serp._extract_results(RaisingRoot(), 10) == []


def test_ai_overview_degrades_on_selector_failure() -> None:
    assert serp._extract_ai_overview(RaisingRoot()) is None


def test_ai_overview_skips_non_element_tags() -> None:
    assert serp._extract_ai_overview(OpaqueNodes()) is None


def test_paa_degrades_on_selector_failure() -> None:
    assert serp._extract_paa(RaisingRoot()) == []


def test_snippet_degrades_on_selector_failure() -> None:
    assert text_mod._extract_snippet(RaisingRoot()) == ""
