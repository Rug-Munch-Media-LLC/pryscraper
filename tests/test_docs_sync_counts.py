# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""The doc-count sweep must rewrite ANY stale number, not a known list.

Why this exists
---------------
The sweep originally enumerated the stale counts it knew about
(``STALE_TOOL_COUNTS = (112, 76, 73, ...)``) and rewrote only those. When the
tool set shrank and the real count moved 113 -> 99, every doc still said 113 --
so 113 was absent from the stale list and not one of those lines was rewritten.
The sweep reported success while leaving 13 wrong numbers in place.

Enumerating stale values is a trap: the list needs a hand edit on every change
to the tool set, and forgetting it fails silently. These tests pin the
behaviour that makes forgetting impossible.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

from tests.docs_sync_helpers import FACTS, REPO, TOOLS_N, _apply, _rules


@pytest.mark.parametrize(
    ("stale", "label"),
    [
        ("113", "the value that actually shipped stale"),
        ("112", "the original enumerated value"),
        ("7", "a number never seen before"),
        ("4242", "an arbitrary future value"),
    ],
)
def test_sweep_rewrites_any_stale_tool_count(stale: str, label: str) -> None:
    """Kills: a sweep that only knows an enumerated set of stale values."""
    out = _apply(_rules(), f"All {stale} tools are immediately available.\n", FACTS)
    assert f"All {TOOLS_N} tools are" in out, f"failed to rewrite {stale} ({label})"


def test_sweep_is_idempotent() -> None:
    """Kills: the compounding-substitution bug (``****99 MCP tools** ...``).

    A rule must not re-match part of its own output. Every pattern is anchored on
    both sides precisely so this holds.
    """
    once = _apply(_rules(), "All 113 tools are ready. MCP Layer (113 tools) here.\n", FACTS)
    twice = _apply(_rules(), once, FACTS)
    assert once == twice
    assert "****" not in once


@pytest.mark.parametrize(
    "text",
    [
        "Pry exposes **113 MCP tools across 33 categories**.\n",
        "| MCP tools | **113** |\n",
        "### Tools (113 total, 33 categories)\n",
        "- MCP Layer (113 tools) - `/mcp`\n",
        "- **15-tier anti-bot bypass** becomes **99-tier anti-bot bypass**\n",
        "via a 15-tier fallback chain\n",
    ],
)
def test_sweep_covers_every_documented_shape(text: str) -> None:
    """Kills: a new prose phrasing slipping past the sweep."""
    out = _apply(_rules(), text, FACTS)
    assert "113" not in out, f"stale 113 survived in: {text.strip()}"


def test_mcp_slug_rule_cannot_compound() -> None:
    """Kills: the badge corruption ``MCP-MCP-MCP-MCP-99_tools_tools_tools...``.

    The README badge rule was ``MCP-\\d+_tools`` with no trailing anchor. It
    re-matched its own output and compounded, leaving a visibly corrupt shields.io
    badge in README.md. The lookahead pins the end of the slug.
    """
    rule = (r"MCP-\d+_tools(?=-)", "MCP-{tools}_tools")
    text = "MCP-113_tools-purple"
    once = _apply([rule], text, FACTS)
    assert once == "MCP-99_tools-purple"
    for _ in range(5):
        assert _apply([rule], once, FACTS) == once, "slug rule compounded"


def test_no_live_badge_corruption_in_docs() -> None:
    """Kills: shipping a doc that already carries compounded output."""
    bad = re.compile(r"(?:MCP-){2,}|tools(?:_tools){1,}")
    for rel in ("README.md", "SKILL.md", "llms.txt", "AGENTS.md"):
        path = REPO / rel
        if path.exists():
            assert not bad.search(path.read_text()), f"{rel} contains compounded output"


def test_no_enumerated_stale_counts_remain() -> None:
    """Kills: someone re-introducing a hardcoded stale list.

    ``generic_rules`` must not reference a module-level tuple of known-stale
    numbers. That list is the trap; its absence is the fix.
    """
    src = (REPO / "scripts" / "docs_sync_sweep.py").read_text()
    body = src.split("def generic_rules", 1)[1]
    assert "STALE_TOOL_COUNTS" not in body, "generic_rules must not enumerate stale values"
    assert "_alt(" not in body, "generic_rules must not build an alternation of stale values"


def test_docs_sync_module_imports_cleanly() -> None:
    """Kills: a rules module that only imports under a specific sys.path order."""
    for mod in ("docs_sync", "docs_sync_rules", "docs_sync_sweep", "docs_sync_site"):
        assert mod in sys.modules or __import__(mod)


def test_repo_has_no_stray_top_level_source_dirs() -> None:
    """Kills: a stale empty directory being counted as a real package.

    ``src/payments/`` held a single August ``.pyc`` and no source; PEP 420
    discovery correctly reported it as a real package no include pattern
    matched, which is how the packaging gate caught it.
    """
    # Only SOURCE directories count. ``src/pryscraper_mcp.egg-info/`` is a
    # setuptools build artifact (no .py, gitignored, excluded from discovery),
    # so it must not trip this. ``src/payments/`` was the real case: one stale
    # .pyc from August, no source, and PEP 420 discovery still counted it as a
    # package no include pattern matched.
    stray = [
        p.name
        for p in (REPO / "src").iterdir()
        if p.is_dir()
        and p.name != "pry"
        and not p.name.endswith((".egg-info", "__pycache__"))
        and any(p.rglob("*.py"))
    ]
    assert not stray, f"unexpected source package(s) under src/: {stray}"


def test_path_helper_is_resolvable() -> None:
    """Kills: a test module whose REPO constant silently points elsewhere."""
    assert (REPO / "pyproject.toml").is_file()
    assert Path(REPO).resolve() == Path(__file__).resolve().parents[1]
