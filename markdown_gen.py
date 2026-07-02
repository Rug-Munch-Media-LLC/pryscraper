"""Pry — markdown generation strategies with content filtering.
Raw, Fit (pruning), and Fit+BM25 (query-relevant) markdown generators."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

import logging
import math
import re
from collections.abc import Sequence
from typing import Any, ClassVar

logger = logging.getLogger(__name__)


class MarkdownGenerator:
    """Base markdown generator. Produces raw markdown from content."""

    def generate(self, content: str, url: str = "") -> dict[str, Any]:
        """Generate markdown. Returns dict with raw_markdown and metadata."""
        return {"raw_markdown": content, "url": url}


class PruningContentFilter:
    """Remove noise from content: nav bars, ads, sidebars, footers.
    Uses heuristics to identify and prune boilerplate sections."""

    BOILERPLATE_PATTERNS: ClassVar[list[str]] = [
        r"nav|navbar|navigation|menu",
        r"footer|copyright",
        r"sidebar|aside",
        r"advertisement|sponsored|promoted",
        r"cookie|consent|gdpr",
        r"social.*share|share.*buttons",
        r"newsletter|subscribe|sign.?up",
        r"comments?.*section",
    ]

    def __init__(self, threshold: float = 0.3, min_word_threshold: int = 50) -> None:
        self.threshold = threshold
        self.min_word_threshold = min_word_threshold

    def filter(self, content: str) -> str:
        """Remove boilerplate sections from content."""
        lines = content.split("\n")
        kept: list[str] = []
        for line in lines:
            if self._is_boilerplate(line):
                continue
            if len(line.strip()) < 3:
                continue
            kept.append(line)
        return "\n".join(kept)

    def _is_boilerplate(self, line: str) -> bool:
        lower = line.lower().strip()
        return any(re.search(p, lower) for p in self.BOILERPLATE_PATTERNS)

    def score(self, content: str) -> dict[str, Any]:
        """Score content quality. Higher = better."""
        lines = content.split("\n")
        total = len(lines)
        boilerplate = sum(1 for line in lines if self._is_boilerplate(line))
        header_score = sum(1 for line in lines if line.startswith("#"))
        link_score = sum(1 for line in lines if "http" in line.lower())
        return {
            "total_lines": total,
            "boilerplate_lines": boilerplate,
            "boilerplate_ratio": round(boilerplate / total, 2) if total > 0 else 0,
            "headers": header_score,
            "links": link_score,
            "quality": "high" if boilerplate / total < self.threshold else "low",
        }


class BM25ContentFilter:
    """BM25-based content filtering for query-relevant extraction.
    Scores each section by relevance to a user query."""

    def __init__(self, k1: float = 1.5, b: float = 0.75, threshold: float = 1.0) -> None:
        self.k1 = k1
        self.b = b
        self.threshold = threshold

    def filter(self, content: str, query: str) -> str:
        """Filter content to keep only query-relevant sections."""
        sections = self._split_sections(content)
        if not sections:
            return content

        scores = self._bm25_scores(sections, query)

        kept: list[str] = []
        for section, score in zip(sections, scores, strict=False):
            if score >= self.threshold:
                kept.append(section)

        return "\n\n".join(kept) if kept else content

    def _split_sections(self, content: str) -> list[str]:
        """Split content into sections by headings."""
        sections = re.split(r"\n(?=#+\s)", content)
        return [s.strip() for s in sections if s.strip()]

    def _bm25_scores(self, sections: Sequence[str], query: str) -> list[float]:
        """Compute BM25 score for each section against query."""
        query_terms = query.lower().split()
        if not query_terms:
            return [1.0] * len(sections)

        tokenized = [self._tokenize(s) for s in sections]
        avg_len = sum(len(t) for t in tokenized) / max(len(tokenized), 1)

        df: dict[str, int] = {}
        for tokens in tokenized:
            for term in set(tokens):
                df[term] = df.get(term, 0) + 1

        n = len(sections)
        scores: list[float] = []
        for tokens in tokenized:
            score = 0.0
            doc_len = len(tokens)
            for term in query_terms:
                if term not in df:
                    continue
                tf = tokens.count(term)
                idf = math.log((n - df[term] + 0.5) / (df[term] + 0.5) + 1.0)
                numerator = tf * (self.k1 + 1)
                denominator = tf + self.k1 * (1 - self.b + self.b * doc_len / avg_len)
                score += idf * (numerator / denominator)
            scores.append(score)

        return scores

    def _tokenize(self, text: str) -> list[str]:
        """Simple word tokenizer."""
        return re.findall(r"\w+", text.lower())


class DefaultMarkdownGenerator(MarkdownGenerator):
    """Markdown generator with configurable content filtering.

    Usage:
        gen = DefaultMarkdownGenerator(
            content_filter=PruningContentFilter(threshold=0.3)
        )
        result = gen.generate(content, url="https://example.com")
        print(result["raw_markdown"])
        if "fit_markdown" in result:
            print(result["fit_markdown"])
    """

    def __init__(
        self, content_filter: PruningContentFilter | BM25ContentFilter | None = None
    ) -> None:
        self.content_filter = content_filter

    def generate(self, content: str, url: str = "", query: str = "") -> dict[str, Any]:
        """Generate markdown with optional filtering.

        Returns:
            raw_markdown: Original content as markdown
            fit_markdown: Pruned content (if PruningContentFilter)
            fit_markdown_bm25: BM25-filtered content (if BM25ContentFilter + query)
            metadata: Content quality scores
        """
        result: dict[str, Any] = {
            "raw_markdown": content,
            "url": url,
        }

        if self.content_filter:
            if isinstance(self.content_filter, BM25ContentFilter) and query:
                result["fit_markdown_bm25"] = self.content_filter.filter(content, query)
                result["filter"] = "bm25"
            elif isinstance(self.content_filter, PruningContentFilter):
                result["fit_markdown"] = self.content_filter.filter(content)
                result["metadata"] = self.content_filter.score(content)
                result["filter"] = "pruning"
            else:
                result["fit_markdown"] = content

        return result
