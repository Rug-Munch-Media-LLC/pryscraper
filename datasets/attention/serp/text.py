"""Pry — defensive text extraction from lxml nodes (never raises)."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

from typing import Any

_SNIPPET_SELECTORS = (".VwiC3b", "div[data-sncf]", ".IsZvec", ".aCOpRe")


def _text(el: Any) -> str:
    """Collapse an lxml element's text content into a single line."""
    try:
        return " ".join((el.text_content() or "").split())
    except (AttributeError, TypeError, ValueError):
        return ""


def _extract_snippet(block: Any) -> str:
    """Best-effort snippet extraction from one organic result block."""
    for selector in _SNIPPET_SELECTORS:
        try:
            els = block.cssselect(selector)
        except (AttributeError, TypeError, ValueError):
            continue
        if els:
            text = _text(els[0])
            if text:
                return text
    return ""
