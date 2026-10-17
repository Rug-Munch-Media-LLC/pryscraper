"""Pry — structured extraction strategies (facade).

Thin re-export facade over the ``extraction`` package. Kept for backward
compatibility: existing ``from extraction import X`` imports keep working.

Implementation lives in:
  - ``extraction.css`` — JsonCSS extractor / cssselect extraction
  - ``extraction.chunking`` — chunking strategies for LLM
  - ``extraction.embeddings`` — embedding helpers
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from extraction.chunking import (
    ChunkingStrategy,
    RegexChunking,
    SentenceChunking,
    TopicChunking,
    extract_with_chunking,
)
from extraction.css import JsonCssExtractionStrategy, extract_structured
from extraction.embeddings import (
    compute_embedding,
    cosine_similarity,
    filter_chunks_by_query,
)

__all__ = [
    "ChunkingStrategy",
    "JsonCssExtractionStrategy",
    "RegexChunking",
    "SentenceChunking",
    "TopicChunking",
    "compute_embedding",
    "cosine_similarity",
    "extract_structured",
    "extract_with_chunking",
    "filter_chunks_by_query",
]

# Markdown normalization + quality scoring (crawl4ai parity). Re-exported so the
# stable ``pry.engine.extraction`` import path keeps working.
from pry.engine.markdown_quality import (
    finalize_markdown,
    markdown_quality,
    normalize_markdown,
)

__all__ += ["finalize_markdown", "markdown_quality", "normalize_markdown"]
