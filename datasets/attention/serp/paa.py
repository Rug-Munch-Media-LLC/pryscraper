"""Pry — People Also Ask extraction from a parsed SERP document."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

from typing import Any

from .text import _text

_LABEL = "People also ask"
_LABEL_TAGS = ("h3", "span", "div", "section")
_MAX_QUESTIONS = 10


def _extract_paa(root: Any) -> list[str]:
    """Best-effort People-Also-Ask extraction (heuristic, changes often)."""
    # Strategy A: legacy "related-question-pair" blocks.
    questions = _questions_from_pairs(root)
    if questions:
        return questions[:_MAX_QUESTIONS]
    # Strategy B: locate the "People also ask" label, then walk up to the
    # smallest container that holds heading-like questions.
    return _questions_from_label(root)


def _questions_from_pairs(root: Any) -> list[str]:
    """Strategy A: ``div.related-question-pair`` text, de-duplicated."""
    questions: list[str] = []
    try:
        pairs = root.cssselect("div.related-question-pair")
    except (AttributeError, TypeError, ValueError):
        pairs = []
    for el in pairs:
        q = _text(el)
        if q and q not in questions:
            questions.append(q)
    return questions


def _questions_from_label(root: Any) -> list[str]:
    """Strategy B: walk up from the label to the nearest container with h3s."""
    questions: list[str] = []
    try:
        for el in root.iter():
            tag = el.tag
            if not isinstance(tag, str) or tag not in _LABEL_TAGS:
                continue
            if (el.text or "").strip() != _LABEL:
                continue
            container = el.getparent()
            for _ in range(4):
                if container is None:
                    break
                headings: list[str] = []
                for h in container.cssselect("h3"):
                    q = _text(h)
                    if q and q != _LABEL and q not in questions:
                        headings.append(q)
                if headings:
                    questions.extend(headings)
                    return questions[:_MAX_QUESTIONS]
                container = container.getparent()
            return questions[:_MAX_QUESTIONS]
    except (AttributeError, TypeError, ValueError):
        return questions
    return questions
