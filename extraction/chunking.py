"""Pry — Chunking strategies for LLM extraction."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

import re
from typing import Any

from extraction.embeddings import filter_chunks_by_query


class ChunkingStrategy:
    """Base chunking strategy. Subclasses implement _chunk()."""

    def chunk(self, text: str) -> list[str]:
        """Split text into chunks."""
        raise NotImplementedError


class RegexChunking(ChunkingStrategy):
    """Chunk by splitting on a regex pattern (e.g., headings, paragraphs)."""

    def __init__(self, pattern: str = r"\n#{2,3}\s", max_chunk_size: int = 2000):
        self.pattern = pattern
        self.max_chunk_size = max_chunk_size

    def chunk(self, text: str) -> list[str]:
        chunks = re.split(self.pattern, text)
        merged = []
        current = ""
        for c in chunks:
            if len(current) + len(c) < self.max_chunk_size:
                current += "\n" + c if current else c
            else:
                if current:
                    merged.append(current.strip())
                current = c
        if current:
            merged.append(current.strip())
        return merged


class SentenceChunking(ChunkingStrategy):
    """Chunk by sentences, grouped to approximate max_chunk_size."""

    def __init__(self, max_chunk_size: int = 1500, overlap: int = 100):
        self.max_chunk_size = max_chunk_size
        self.overlap = overlap

    def chunk(self, text: str) -> list[str]:
        sentences = re.split(r"(?<=[.!?])\s+", text)
        chunks = []
        current = ""
        for s in sentences:
            if len(current) + len(s) > self.max_chunk_size and current:
                chunks.append(current.strip())
                overlap_text = current[-self.overlap :] if self.overlap > 0 else ""
                current = overlap_text + " " + s
            else:
                current += " " + s if current else s
        if current:
            chunks.append(current.strip())
        return chunks


class TopicChunking(ChunkingStrategy):
    """Chunk by markdown headings (##, ###, etc.). Each heading becomes a chunk."""

    def __init__(self, max_chunk_size: int = 3000):
        self.max_chunk_size = max_chunk_size

    def chunk(self, text: str) -> list[str]:
        pattern = r"(^|\n)(#{1,6}\s.+?)(?=\n#{1,6}\s|\Z)"
        matches = list(re.finditer(pattern, text, re.DOTALL))
        if not matches:
            return (
                [text]
                if len(text) < self.max_chunk_size
                else SentenceChunking(self.max_chunk_size).chunk(text)
            )

        chunks = []
        for m in matches:
            content = m.group(0).strip()
            if len(content) > self.max_chunk_size:
                sub_chunks = SentenceChunking(self.max_chunk_size).chunk(content)
                chunks.extend(sub_chunks)
            else:
                chunks.append(content)
        return chunks if chunks else [text]


async def extract_with_chunking(
    content: str,
    instruction: str,
    schema: dict[str, Any] | None = None,
    chunk_strategy: str = "topic",
    query: str = "",
    top_k: int = 5,
) -> list[dict[str, Any]]:
    """Extract structured data by chunking content, extracting from relevant chunks.

    chunk_strategy: "topic", "sentence", or "regex"
    query: optional natural language query for relevance filtering
    """
    if chunk_strategy == "topic":
        chunker: ChunkingStrategy = TopicChunking()
    elif chunk_strategy == "sentence":
        chunker = SentenceChunking()
    elif chunk_strategy == "regex":
        chunker = RegexChunking()
    else:
        chunker = TopicChunking()

    chunks = chunker.chunk(content)

    if query:
        chunks = filter_chunks_by_query(chunks, query, top_k=top_k)

    results = []
    for i, c in enumerate(chunks):
        results.append(
            {
                "chunk_index": i,
                "chunk_size": len(c),
                "content": c[:500],
            }
        )

    return results


__all__ = [
    "ChunkingStrategy",
    "RegexChunking",
    "SentenceChunking",
    "TopicChunking",
    "extract_with_chunking",
]
