"""Pry — Crawl4AI-style content filtering and token-cost-aware markdown.

Removes boilerplate (nav, footer, ads, cookie banners), extracts only the
main content block, converts to minimal Markdown, and chunks for RAG with
token-cost estimates. Pure HTML/text processing — no HTTP.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import re
import textwrap
from typing import Any

from bs4 import BeautifulSoup, Tag

# Structural elements that are always boilerplate.
_STRIP_TAGS = (
    "script",
    "style",
    "noscript",
    "iframe",
    "svg",
    "canvas",
    "form",
    "button",
    "input",
    "select",
    "textarea",
    "nav",
    "footer",
    "header",
    "aside",
    "template",
)

# Boilerplate class/id patterns (Crawl4AI-style pruning).
_BOILERPLATE_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"nav|navbar|navigation|menu|breadcrumb",
        r"footer|copyright|colophon",
        r"sidebar|aside|widget",
        r"advert|advertisement|ads?[-_]|sponsored|promoted",
        r"cookie|consent|gdpr|privacy[-_]?banner",
        r"social[-_]?share|share[-_]?buttons|sharing",
        r"newsletter|subscribe|sign[-_]?up|mailing[-_]?list",
        r"related[-_]?posts|related[-_]?articles|recommended",
        r"comments?[-_]?section|disqus|comment[-_]?list",
        r"popup|modal|overlay|banner|toast",
        r"skip[-_]?to[-_]?content|screen[-_]?reader",
        r"pagination|pager",
        r"search[-_]?box|search[-_]?bar|search[-_]?form",
    )
)

# Selectors for the main content block, in priority order.
_MAIN_SELECTORS = (
    "article",
    "main",
    '[role="main"]',
    "#content",
    ".post-content",
    ".entry-content",
    ".article-content",
    ".article-body",
    ".content",
)


def _soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")


def _is_boilerplate_node(node: Tag) -> bool:
    """True if a node's class/id/aria-label matches boilerplate patterns."""
    attrs: list[str] = []
    for key in ("class", "id", "aria-label", "data-testid", "role"):
        value = node.get(key)
        if isinstance(value, (list, tuple)):
            attrs.extend(str(v) for v in value)
        elif value is not None:
            attrs.append(str(value))
    return any(pattern.search(" ".join(attrs).lower()) for pattern in _BOILERPLATE_PATTERNS)


def prune_boilerplate(html: str) -> str:
    """Remove common boilerplate patterns: cookie notices, GDPR banners,
    newsletter signup forms, social share buttons, ad containers, related
    posts sections, comment sections. Returns cleaned HTML."""
    soup = _soup(html)
    for node in soup.find_all(True):
        if not isinstance(node, Tag):
            continue
        if _is_boilerplate_node(node):
            node.decompose()
    return str(soup)


def filter_to_essential(html: str) -> str:
    """Remove boilerplate: nav, footer, header, aside, script, style, cookie
    banners, ad divs, social share widgets. Keep only main content.
    Returns cleaned HTML."""
    soup = _soup(html)
    for tag_name in _STRIP_TAGS:
        for node in soup.find_all(tag_name):
            node.decompose()
    for node in soup.find_all(True):
        if isinstance(node, Tag) and _is_boilerplate_node(node):
            node.decompose()
    # Drop empty containers left behind.
    for node in soup.find_all(True):
        if isinstance(node, Tag) and not node.get_text(strip=True) and not node.find("img"):
            node.decompose()
    return str(soup)


def extract_main_content(html: str) -> dict[str, Any]:
    """Extract the main content block from a page using readability-style
    heuristics (article/main/role=main tags, then largest text block).

    Returns: {"main_html", "main_text", "title", "reduction_pct"}.
    """
    soup = _soup(html)
    title = soup.title.get_text(strip=True) if soup.title else ""

    main_html = ""
    for selector in _MAIN_SELECTORS:
        found = soup.select_one(selector)
        if found and len(found.get_text(strip=True)) > 100:
            main_html = str(found)
            break

    if not main_html:
        # Readability fallback: pick the block-level element with the most text.
        best: Tag | None = None
        best_len = 0
        for node in soup.find_all(["div", "section", "td", "p", "span", "article", "main"]):
            if not isinstance(node, Tag):
                continue
            text_len = len(node.get_text(strip=True))
            if text_len > best_len:
                best = node
                best_len = text_len
        if best is not None:
            main_html = str(best)

    if not main_html:
        main_html = filter_to_essential(html)
        main_text = BeautifulSoup(main_html, "html.parser").get_text(separator="\n", strip=True)
    else:
        main_text = BeautifulSoup(main_html, "html.parser").get_text(separator="\n", strip=True)

    raw_len = len(html) or 1
    reduction_pct = round(max(0.0, (1 - len(main_html) / raw_len)) * 100, 1)
    return {
        "main_html": main_html,
        "main_text": main_text,
        "title": title,
        "reduction_pct": reduction_pct,
    }


def _inline_to_md(node: Tag, include_links: bool, include_images: bool) -> str:
    """Convert inline children of a block node to markdown text."""
    parts: list[str] = []
    for child in node.children:
        if isinstance(child, Tag):
            if child.name == "br":
                parts.append("\n")
            elif child.name in ("strong", "b"):
                inner = child.get_text(strip=True)
                if inner:
                    parts.append(f"**{inner}**")
            elif child.name in ("em", "i"):
                inner = child.get_text(strip=True)
                if inner:
                    parts.append(f"*{inner}*")
            elif child.name == "code":
                inner = child.get_text(strip=True)
                if inner:
                    parts.append(f"`{inner}`")
            elif child.name == "a":
                inner = child.get_text(strip=True)
                href = child.get("href", "")
                if include_links and inner:
                    parts.append(f"[{inner}]({href})" if href else inner)
                elif inner:
                    parts.append(inner)
            elif child.name == "img":
                if include_images:
                    alt = child.get("alt", "") or "image"
                    src = child.get("src", "")
                    parts.append(f"![{alt}]({src})")
            else:
                parts.append(child.get_text(" ", strip=True))
        elif child.string:
            parts.append(str(child))
    return "".join(parts)


def html_to_minimal_markdown(
    html: str,
    include_links: bool = True,
    include_images: bool = False,
    max_line_length: int = 0,
) -> str:
    """Convert HTML to minimal Markdown. Strips redundant whitespace, collapses
    paragraphs, removes empty headings. If max_line_length > 0, wraps lines.
    Returns clean Markdown."""
    soup = _soup(html)
    lines: list[str] = []

    for node in soup.find_all(
        ["h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "blockquote", "pre", "hr", "table"]
    ):
        if not isinstance(node, Tag):
            continue
        name = node.name
        text = _inline_to_md(node, include_links, include_images).strip()
        text = re.sub(r"\s+", " ", text)
        if name in ("h1", "h2", "h3", "h4", "h5", "h6"):
            if not text:  # drop empty headings
                continue
            level = int(name[1])
            lines.append("#" * level + " " + text)
        elif name == "p":
            if text:
                lines.append(text)
        elif name == "li":
            if text:
                lines.append("- " + text)
        elif name == "blockquote":
            if text:
                lines.extend("> " + part for part in text.split("\n") if part)
        elif name == "pre":
            code = node.get_text().strip()
            if code:
                lines.append("```\n" + code + "\n```")
        elif name == "hr":
            lines.append("---")
        elif name == "table":
            rows = node.find_all("tr")
            table_lines: list[str] = []
            for i, row in enumerate(rows):
                cells = [
                    re.sub(r"\s+", " ", td.get_text(" ", strip=True))
                    for td in row.find_all(["td", "th"])
                ]
                if cells:
                    table_lines.append("| " + " | ".join(cells) + " |")
                    if i == 0:
                        table_lines.append("|" + "---|" * len(cells))
            lines.extend(table_lines)

    markdown = "\n\n".join(lines)
    markdown = re.sub(r"\n{3,}", "\n\n", markdown).strip()

    if max_line_length > 0:
        wrapped: list[str] = []
        for line in markdown.split("\n"):
            if line.startswith(("```", "#", "- ", "> ", "|", "---")):
                wrapped.append(line)
            else:
                wrapped.extend(
                    textwrap.wrap(
                        line,
                        width=max_line_length,
                        break_long_words=False,
                        break_on_hyphens=False,
                    )
                    or [""]
                )
        markdown = "\n".join(wrapped)

    return markdown


def estimate_tokens(text: str) -> int:
    """Estimate token count: len(text) // 4 (OpenAI-style approximation)."""
    return len(text) // 4


def _split_chunks(text: str, chunk_size: int, chunk_overlap: int) -> list[str]:
    """Split text into overlapping chunks on paragraph boundaries."""
    if not text:
        return []
    paragraphs = text.split("\n\n")
    chunks: list[str] = []
    current = ""
    for para in paragraphs:
        candidate = (current + "\n\n" + para).strip() if current else para
        if len(candidate) <= chunk_size or not current:
            current = candidate
            if len(current) >= chunk_size:
                chunks.append(current)
                tail = current[-chunk_overlap:] if chunk_overlap > 0 else ""
                current = tail
        else:
            chunks.append(current)
            tail = current[-chunk_overlap:] if chunk_overlap > 0 else ""
            current = (tail + "\n\n" + para).strip()
    if current.strip():
        chunks.append(current.strip())
    return chunks


def filter_and_chunk(
    html: str,
    chunk_size: int = 1000,
    chunk_overlap: int = 100,
    include_links: bool = True,
) -> dict[str, Any]:
    """Full pipeline: filter -> markdown -> chunk.

    Returns: {"markdown", "chunks", "total_tokens", "chunks_count",
    "reduction_pct"} where reduction_pct is how much the content was
    reduced from raw HTML size.
    """
    filtered = filter_to_essential(html)
    markdown = html_to_minimal_markdown(filtered, include_links=include_links)
    chunks = _split_chunks(markdown, chunk_size, chunk_overlap)
    raw_len = len(html) or 1
    reduction_pct = round(max(0.0, (1 - len(markdown) / raw_len)) * 100, 1)
    return {
        "markdown": markdown,
        "chunks": chunks,
        "total_tokens": estimate_tokens(markdown),
        "chunks_count": len(chunks),
        "reduction_pct": reduction_pct,
    }
