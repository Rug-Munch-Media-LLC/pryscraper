# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Shared helpers for the docs_sync regression tests.

Split out so ``test_docs_sync_counts`` and ``test_docs_sync_guards`` each stay
under the 200-line structure cap.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO / "scripts"))

from docs_sync_sweep import generic_rules  # noqa: E402

TOOLS_N = "99"

# Bare values only. Every rule template draws its formatting from the template
# and its number from here; see scripts/docs_sync_rules.py for why the rules
# carry no third "correct" element.
FACTS = {
    "tools": TOOLS_N,
    "categories": "33",
    "tests": "308",
    "tiers": "15",
    "actors": "109",
    "templates": "110",
}


def _rules() -> list[tuple[str, str]]:
    """The production sweep rules."""
    return generic_rules()


def _apply(rules: list[tuple[str, str]], text: str, facts: dict[str, str]) -> str:
    """Apply rules the way ``docs_sync.patch`` does: per line, templates filled
    from ``facts``.

    ``patch`` additionally skips lines matched by its ``skip_re``; this harness
    omits that because it is testing the substitution algebra, not the skip set.
    """
    for pattern_fmt, repl_fmt in rules:
        pattern = pattern_fmt.format(**facts)
        repl = repl_fmt.format(**facts)
        out = []
        for line in text.splitlines(keepends=True):
            new_line, _matched = re.subn(pattern, repl, line)
            out.append(new_line)
        text = "".join(out)
    return text
