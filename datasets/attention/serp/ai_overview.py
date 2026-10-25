"""Pry — AI Overview ("AI Overview" answer box) extraction."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

from typing import Any

from .text import _text

_LABEL = "AI Overview"
_CONTAINER_SELECTORS = (
    "div.ILfuVd",
    "div[data-attrid='kAAb9c']",
    "div[data-attrid='knowledge-answer']",
)
_TEXT_TAGS = ("div", "span", "h2", "section", "article")


def _strip_label(text: str) -> str:
    """Drop a leading ``AI Overview`` label and surrounding space."""
    if text.startswith(_LABEL):
        return text[len(_LABEL) :].strip()
    return text


def _extract_ai_overview(root: Any) -> str | None:
    """Best-effort AI Overview extraction (heuristic, changes often)."""
    # Strategy A: known AI-overview container classes / attrs.
    for selector in _CONTAINER_SELECTORS:
        try:
            els = root.cssselect(selector)
        except (AttributeError, TypeError, ValueError):
            continue
        for el in els:
            text = _text(el)
            if text:
                return _strip_label(text) or None
    # Strategy B: find the literal "AI Overview" label and return the
    # enclosing block's text (label stripped).
    return _extract_from_label(root)


def _extract_from_label(root: Any) -> str | None:
    """Strategy B: element whose own text starts with the label."""
    try:
        for el in root.iter():
            tag = el.tag
            if not isinstance(tag, str) or tag not in _TEXT_TAGS:
                continue
            direct = (el.text or "").strip()
            if not direct.startswith(_LABEL):
                continue
            parent = el.getparent()
            if parent is None:
                return " ".join(direct.split())
            text = " ".join((parent.text_content() or "").split())
            text = _strip_label(text)
            if len(text) > 10:
                return text[:2000]
            return " ".join(direct.split())
    except (AttributeError, TypeError, ValueError):
        return None
    return None
