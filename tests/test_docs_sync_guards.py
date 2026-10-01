# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Guards that stop the doc-count sweep from corrupting the docs it syncs."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests.docs_sync_helpers import FACTS


def test_refuses_to_run_on_already_corrupted_docs() -> None:
    """Kills: silently amplifying compounding damage on every subsequent run.

    Once a doc contains ``****99 MCP tools** MCP tools**``, a generic ``\\d+``
    rule keeps matching the digits inside the garbage and multiplies it further.
    The sync must stop instead. Verified against the real scanner.
    """
    from docs_sync_sweep import COMPOUNDED_RE

    # Only shapes this bug can actually PRODUCE. Asserting a shape the bug
    # cannot emit (e.g. "MCP-99 MCP-99") tests nothing and invites loosening the
    # detector until it passes.
    damaged = [
        "**99 MCP tools** MCP tools** MCP tools**",  # rule re-matched its output
        "MCP-MCP-MCP-MCP-99_tools_tools_tools_tools-purple",  # badge slug
        "x_99_tools_tools_tools y",
        "99 tools** MCP tools** z",
    ]
    for text in damaged:
        assert COMPOUNDED_RE.search(text), f"missed real damage: {text}"


def test_compound_detector_ignores_legitimate_prose() -> None:
    """Kills: a guard so noisy it gets disabled.

    An earlier signature (r'-\\w+-tier') matched the ADR filename
    ``0005-15-tier-scraping.md``. Every pattern must be one that cannot occur
    in ordinary documentation.
    """
    from docs_sync_sweep import COMPOUNDED_RE

    legitimate = [
        "[0005-15-tier-scraping.md](/adr/0005-15-tier-scraping.md)",
        "**15-tier anti-bot bypass** for Cloudflare",
        "99 MCP tools across 33 categories",
        "| MCP tools | **99** | 5 | 8 |",
        "MCP Layer (99 tools) - /mcp",
        "the tools** and the tool",
        "**99 MCP tools** across 33 categories",
        "MCP-99 MCP-99 MCP-99_tools-purple",
    ]
    for text in legitimate:
        assert not COMPOUNDED_RE.search(text), f"false positive on: {text}"


def _all_production_rules() -> list[tuple[str, object]]:
    """Every rule list the real sync uses, plus a label for each."""
    from docs_sync_site import RULES as SITE_RULES
    from docs_sync_sweep import generic_rules

    return [("sweep", r) for r in generic_rules()] + [("site", r) for r in SITE_RULES]


def test_every_production_rule_is_two_elements() -> None:
    """Kills: reintroducing the ``(pattern, repl, correct)`` footgun.

    ``patch()`` fills ``{n}``-style placeholders into BOTH templates from one
    source. The old third element let a caller pass a pre-formatted value where
    a bare number belonged, and the replacement expanded into itself --
    ``MCP-MCP-MCP-MCP-99_tools_tools_tools`` shipped in README.md. Making every
    rule two elements means the mistake has nowhere to go.
    """
    for label, rule in _all_production_rules():
        assert len(rule) == 2, f"{label} rule has {len(rule)} elements: {rule!r}"


def test_no_production_rule_repeats_its_own_replacement() -> None:
    """Kills: any rule whose output re-matches its own pattern to multiply it.

    Applying every real rule three times must converge after one pass. This is
    the property whose absence produced the compounding corruption, tested
    against the rules that actually ship rather than a hand-copied example.
    """
    for label, (pattern_fmt, repl_fmt) in _all_production_rules():
        try:
            probe = repl_fmt.format(**FACTS)
        except (KeyError, IndexError):  # a literal brace, not a placeholder
            continue
        once = re.sub(pattern_fmt.format(**FACTS), probe, probe)
        twice = re.sub(pattern_fmt.format(**FACTS), probe, once)
        assert once == twice == probe, (
            f"{label} rule is not self-stable: {probe!r} -> {once!r} -> {twice!r}"
        )


def test_patch_rejects_a_three_element_rule() -> None:
    """Kills: silently accepting the malformed shape if a caller tries again.

    Validation happens before the filesystem is touched, so a bad rule fails
    even when the target path does not exist.
    """
    from docs_sync import patch

    with pytest.raises(ValueError, match="must be"):
        patch(Path("/nonexistent-doc.md"), [("a", "b", "c")], False, FACTS)
