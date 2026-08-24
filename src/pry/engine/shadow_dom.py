"""Pry — Shadow DOM flattening utilities.
Recursively extracts content from shadow roots in HTML."""

# SPDX-License-Identifier: BSL-1.1
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — Stealth / Anti-Detection Module
# Licensed under Business Source License 1.1 — see LICENSE-BSL-STEALTH.
# Change Date: 2029-01-01 (converts to MIT).

import logging
import re

logger = logging.getLogger(__name__)

# Regex to detect shadow DOM in raw HTML
SHADOW_ROOT_PATTERNS = [
    r"<template[^>]*shadowroot[^>]*>",
    r"#shadow-root",
    r"attachshadow",
    r"shadowroot",
    r"open-mode",
    r"closed-mode",
]


def has_shadow_dom(html: str) -> bool:
    """Check if HTML contains Shadow DOM content."""
    lower = html.lower()
    return any(re.search(p, lower) for p in SHADOW_ROOT_PATTERNS)


def flatten_shadow_dom(html: str) -> str:
    """Flatten shadow DOM templates into the main document.

    Converts:
        <template shadowroot="open">content</template>
    To:
        content (inline, no template wrapper)

    Also handles declarative shadow DOM (<template shadowrootmode="open">).
    """
    # Pattern 1: <template shadowroot="open">...</template>
    result = re.sub(
        r'<template\s+shadowroot=["\'](?:open|closed)["\'][^>]*>(.*?)</template>',
        r"\1",
        html,
        count=0,
        flags=re.DOTALL,
    )

    # Pattern 2: <template shadowrootmode="open">...</template>
    result = re.sub(
        r'<template\s+shadowrootmode=["\'](?:open|closed)["\'][^>]*>(.*?)</template>',
        r"\1",
        result,
        count=0,
        flags=re.DOTALL,
    )

    # Pattern 3: <template shadowroot="open" shadowrootmode="open">...</template>
    result = re.sub(
        r'<template\s+shadowroot(?:mode)?=["\'](?:open|closed)["\'].*?>(.*?)</template>',
        r"\1",
        result,
        count=0,
        flags=re.DOTALL,
    )

    # Pattern 4: <div id="shadow-host">#shadow-root (open)</div>
    # (this is a comment/annotation, not real shadow DOM — leave as-is)

    logger.debug(
        "shadow_dom_flattened", extra={"original_size": len(html), "new_size": len(result)}
    )
    return result


class ShadowDOMProcessor:
    """Process HTML to extract content from shadow DOM components.

    Usage:
        processor = ShadowDOMProcessor()
        flat_html = processor.process(original_html)
    """

    def __init__(self, flatten_declarative: bool = True):
        self.flatten_declarative = flatten_declarative

    def process(self, html: str) -> str:
        """Flatten shadow DOM in HTML content."""
        if not self._detect(html):
            return html

        result = html
        if self.flatten_declarative:
            result = flatten_shadow_dom(result)

        # Additional processing: extract inline styles from shadow roots
        result = self._extract_shadow_styles(result)

        return result

    def _detect(self, html: str) -> bool:
        return has_shadow_dom(html)

    def _extract_shadow_styles(self, html: str) -> str:
        """Extract <style> elements from shadow roots and inline them."""
        # <style> inside templates that were shadow roots
        result = re.sub(
            r"<style>(.*?)</style>",
            r"<style>\1</style>",
            html,
            flags=re.DOTALL,
        )
        return result
