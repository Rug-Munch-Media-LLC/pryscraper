"""Pry — structured extraction strategies (facade).

CSS/XPath-based extraction (no LLM needed) + chunking strategies for LLM extraction.
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
