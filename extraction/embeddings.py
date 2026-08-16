"""Pry — Embedding helpers for LLM extraction relevance filtering."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

import logging
import math
from collections.abc import Sequence
from typing import Any

import httpx

logger = logging.getLogger(__name__)


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


__all__ = ["compute_embedding", "cosine_similarity", "filter_chunks_by_query"]
