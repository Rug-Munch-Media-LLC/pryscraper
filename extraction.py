"""Pry — structured extraction strategies.
CSS/XPath-based extraction (no LLM needed) + chunking strategies for LLM extraction."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

import logging
import math
import re
from collections.abc import Sequence
from typing import Any

import httpx
from lxml import html as lxml_html

logger = logging.getLogger(__name__)


class JsonCssExtractionStrategy:
    """Extract structured JSON from HTML using CSS selectors / XPath.

    Schema format:
    {
        "name": "items",
        "base_selector": "css-selector",
        "fields": [
            {"name": "title", "selector": "h3", "type": "text"},
            {"name": "link", "selector": "a", "type": "attribute", "attribute": "href"},
            {"name": "price", "selector": ".price", "type": "text", "transform": "strip_currency"},
            {"name": "nested", "type": "nested", "fields": [...]},
        ]
    }

    Field types: text, attribute, html, nested, count, exists, regex
    """

    def __init__(self, schema: dict[str, Any]) -> None:
        self.schema = schema
        self.name = schema.get("name", "extracted")

    def extract(self, html: str) -> list[dict[str, Any]]:
        """Extract structured data from HTML string."""
        tree = lxml_html.fromstring(html)
        base_selector = self.schema.get("base_selector")
        fields = self.schema.get("fields", [])

        elements = tree.cssselect(base_selector) if base_selector else [tree]

        results = []
        for el in elements:
            row = self._extract_fields(el, fields)
            if any(v not in (None, "", []) for v in row.values()):
                results.append(row)

        return results

    def _extract_fields(self, element: Any, fields: list[dict[str, Any]]) -> dict[str, Any]:
        row: dict[str, Any] = {}
        for field in fields:
            name = field["name"]
            ftype = field.get("type", "text")
            selector = field.get("selector", "")
            attr = field.get("attribute", "")
            transform = field.get("transform", "")

            try:
                if ftype == "nested":
                    sub_el = element.cssselect(selector)[0] if selector else element
                    row[name] = self._extract_fields(sub_el, field.get("fields", []))
                elif ftype == "count":
                    row[name] = len(element.cssselect(selector))
                elif ftype == "exists":
                    row[name] = len(element.cssselect(selector)) > 0
                elif ftype == "regex":
                    text = self._get_text(element, selector)
                    pattern = field.get("pattern", "")
                    match = re.search(pattern, text) if pattern else None
                    row[name] = match.group(1) if match else None
                elif ftype == "attribute":
                    els = element.cssselect(selector) if selector else [element]
                    values = []
                    for e in els:
                        v = e.get(attr, "")
                        if v:
                            values.append(self._apply_transform(v.strip(), transform))
                    row[name] = values[0] if len(values) == 1 else values if values else None
                elif ftype == "html":
                    els = element.cssselect(selector) if selector else [element]
                    row[name] = "\n".join(lxml_html.tostring(e, encoding="unicode") for e in els)
                else:
                    text = self._get_text(element, selector)
                    row[name] = self._apply_transform(text, transform)
            except Exception as e:  # noqa: BLE001
                logger.warning("field_extract_failed", extra={"field": name, "error": str(e)})
                row[name] = None

        return row

    def _get_text(self, element: Any, selector: str) -> str:
        if selector:
            els = element.cssselect(selector)
            if not els:
                return ""
            return str(" ".join(str(e.text_content()).strip() for e in els))
        return str(element.text_content()).strip()

    def _apply_transform(self, value: str, transform: str) -> Any:
        if not value:
            return value
        if transform == "strip_currency":
            return re.sub(r"[^\d.,]", "", value).strip()
        if transform == "lower":
            return value.lower()
        if transform == "upper":
            return value.upper()
        if transform == "strip":
            return value.strip()
        if transform == "int":
            try:
                return int(re.sub(r"[^\d\-]", "", value))
            except ValueError:
                return value
        if transform == "float":
            try:
                return float(re.sub(r"[^\d.\-]", "", value))
            except ValueError:
                return value
        return value


async def extract_structured(
    html: str,
    schema: dict[str, Any],
    extraction_type: str = "css",
) -> list[dict[str, Any]]:
    """Extract structured data using the specified strategy."""
    if extraction_type == "css":
        strategy = JsonCssExtractionStrategy(schema)
        return strategy.extract(html)
    raise ValueError(f"Unknown extraction type: {extraction_type}")


# ── Chunking Strategies for LLM Extraction ──


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


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    """Cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def compute_embedding(text: str, model: str = "all-MiniLM-L6-v2") -> list[float]:
    """Compute embedding for text using Ollama or a simple TF-IDF fallback."""
    try:
        import anyio

        from client import get_client
        from settings import settings

        async def _fetch() -> list[float]:
            client = await get_client()
            resp = await client.post(
                f"{settings.ollama_url}/api/embeddings",
                json={"model": model, "prompt": text},
                timeout=30,
            )
            resp.raise_for_status()
            body: Any = resp.json()
            return list(body.get("embedding", []))

        return anyio.run(_fetch)
    except (httpx.HTTPError, httpx.RequestError):
        ngrams: dict[str, float] = {}
        for i in range(len(text) - 2):
            ng = text[i : i + 3].lower()
            ngrams[ng] = ngrams.get(ng, 0) + 1
        total = sum(ngrams.values()) or 1
        return [ngrams.get(k, 0) / total for k in sorted(ngrams)[:256]]


def filter_chunks_by_query(chunks: list[str], query: str, top_k: int = 5) -> list[str]:
    """Filter chunks by cosine similarity to query."""
    try:
        query_emb = compute_embedding(query)
        scored = []
        for c in chunks:
            chunk_emb = compute_embedding(c)
            sim = cosine_similarity(query_emb, chunk_emb)
            scored.append((sim, c))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [c for _, c in scored[:top_k]]
    except Exception:  # noqa: BLE001
        logger.warning("embedding_filter_failed, returning top chunks by length")
        return sorted(chunks, key=len, reverse=True)[:top_k]


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
