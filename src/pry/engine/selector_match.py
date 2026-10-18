"""Candidate scoring and best-match search for adaptive selector relocation.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

from __future__ import annotations

import difflib

from bs4 import BeautifulSoup, Tag

from pry.engine.selector_context import (
    ElementContext,
    attr_similarity,
    attrs_of,
    norm_text,
    path_similarity,
    structural_path,
)

# Minimum fuzzy text similarity to accept a relocation candidate.
MIN_TEXT_SIMILARITY = 0.4

# How many candidate elements to score during relocation (perf cap).
MAX_CANDIDATES = 400


def _text_score(ctx: ElementContext, node_text: str) -> float:
    """Fuzzy text similarity; both-empty counts as a consistent match."""
    if ctx.text and node_text:
        return difflib.SequenceMatcher(None, ctx.text, node_text).ratio()
    if not ctx.text and not node_text:
        return 1.0
    return 0.0


def _parent_score(ctx: ElementContext, parent: Tag | None) -> tuple[float, float]:
    """Parent tag/attribute contribution and its weight."""
    if parent is None or not ctx.parent_tag or parent.name != ctx.parent_tag:
        return 0.0, 0.5
    return 0.5 + 0.5 * attr_similarity(attrs_of(parent), ctx.parent_attrs), 0.5


def _sibling_score(ctx: ElementContext, node: Tag) -> float:
    """Previous-sibling text contribution (0 or 0.5)."""
    prev_sibs = [s for s in node.find_previous_siblings() if isinstance(s, Tag)]
    if not prev_sibs or not ctx.sibling_text:
        return 0.0
    prev_text = norm_text(prev_sibs[0].get_text(" ", strip=True))[:200]
    if prev_text and difflib.SequenceMatcher(None, ctx.sibling_text, prev_text).ratio() > 0.6:
        return 0.5
    return 0.0


def score_candidate(node: Tag, ctx: ElementContext) -> float:
    """Score how likely a candidate node is the relocated element (0..1)."""
    node_text = norm_text(node.get_text(" ", strip=True))[:500]
    parent = node.parent if isinstance(node.parent, Tag) else None
    parent_score, parent_weight = _parent_score(ctx, parent)

    score = 0.0
    weight = 0.0

    # Tag name match.
    weight += 1.0
    if ctx.tag and node.name == ctx.tag:
        score += 1.0

    # Attribute similarity.
    weight += 1.0
    score += attr_similarity(attrs_of(node), ctx.attrs)

    # Text similarity (fuzzy).
    weight += 1.5
    score += _text_score(ctx, node_text)

    # Structural path similarity.
    weight += 1.0
    score += path_similarity(structural_path(node), ctx.path)

    # Parent tag/attrs.
    weight += parent_weight
    score += parent_score

    # Previous-sibling text.
    weight += 0.5
    score += _sibling_score(ctx, node)

    return score / weight if weight else 0.0


def find_best_match(soup: BeautifulSoup, ctx: ElementContext) -> tuple[Tag | None, float]:
    """Scan candidate elements and return the highest-scoring match."""
    candidates = soup.find_all(ctx.tag) if ctx.tag else soup.find_all(True)
    if not candidates and ctx.tag:
        # Remembered tag may have changed; scan everything.
        candidates = soup.find_all(True)
    best: Tag | None = None
    best_score = 0.0
    scanned = 0
    for node in candidates:
        if not isinstance(node, Tag):
            continue
        scanned += 1
        if scanned > MAX_CANDIDATES:
            break
        node_score = score_candidate(node, ctx)
        if node_score > best_score:
            best = node
            best_score = node_score
    return best, best_score


__all__ = [
    "MAX_CANDIDATES",
    "MIN_TEXT_SIMILARITY",
    "find_best_match",
    "score_candidate",
]
