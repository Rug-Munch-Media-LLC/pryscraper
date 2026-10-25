"""Same-family domain recall over the fleet 1024-d embed lane.

The lane is Qwen3-Embedding-0.6B at ``PRY_EMBED_LANE_URL`` (default :8004). When
it is unreachable this module reports ``available=False`` and falls back to the
registrable-host rule table: a degraded answer is labelled, never faked.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import logging
import math
import os
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import httpx

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

EMBED_LANE_URL = os.environ.get("PRY_EMBED_LANE_URL", "http://127.0.0.1:8004")
EMBED_MODEL = os.environ.get("PRY_EMBED_MODEL", "qwen3-embedding-0.6b")
EMBED_DIM = 1024
EMBED_TIMEOUT_SECONDS = 2.0
SIMILARITY_FLOOR = 0.75
SIMILAR_LIMIT = 5

# Anything the lane can realistically raise; deliberately not ``Exception``.
_LANE_ERRORS = (httpx.HTTPError, KeyError, IndexError, OSError, TypeError, ValueError, RuntimeError)

__all__ = [
    "EMBED_DIM",
    "EmbedLane",
    "Similarity",
    "cosine",
    "find_similar_domain",
    "host_family",
    "rule_matches",
]


@dataclass(frozen=True, slots=True)
class Similarity:
    """Outcome of a recall attempt, including *why* it degraded."""

    available: bool
    reason: str
    matches: list[str] = field(default_factory=list)


def host_family(domain: str) -> str:
    """Registrable-ish family: last two labels (``a.b.example.com`` -> ``example.com``)."""
    labels = [label for label in domain.split(".") if label]
    return ".".join(labels[-2:]) if len(labels) >= 2 else domain


def rule_matches(domain: str, known: Iterable[str]) -> list[str]:
    """Exact domain plus same-host-family matches, stable order, no vectors."""
    family = host_family(domain)
    return [d for d in known if d == domain or host_family(d) == family]


def cosine(left: list[float], right: list[float]) -> float:
    """Cosine similarity. A dimension mismatch raises instead of scoring."""
    if len(left) != len(right):
        raise ValueError(f"embedding dimension mismatch: {len(left)} != {len(right)}")
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    norm = math.sqrt(sum(a * a for a in left)) * math.sqrt(sum(b * b for b in right))
    if not norm:
        raise ValueError("zero-norm embedding")
    return dot / norm


class EmbedLane:
    """Thin client for the embed lane. An injected ``embedder`` is the test seam."""

    def __init__(
        self, url: str = EMBED_LANE_URL, embedder: Callable[[str], list[float]] | None = None
    ) -> None:
        self._url = url.rstrip("/")
        self._embedder = embedder

    def embed(self, text: str) -> list[float]:
        """One 1024-d vector, or raise."""
        if self._embedder is not None:
            return self._embedder(text)
        response = httpx.post(
            f"{self._url}/v1/embeddings",
            json={"input": text, "model": EMBED_MODEL},
            timeout=EMBED_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        vector = response.json()["data"][0]["embedding"]
        if len(vector) != EMBED_DIM:
            raise ValueError(f"lane returned {len(vector)}-d, contract is {EMBED_DIM}-d")
        return vector

    def probe(self) -> tuple[bool, str]:
        """Cheap liveness check, for diagnostics and the ADR's honest reporting."""
        try:
            self.embed("probe")
        except _LANE_ERRORS as exc:
            logger.warning("embed_probe_failed handler=unlock_similar error=%s", exc)
            return False, f"{type(exc).__name__}: {exc}"
        return True, "ok"


def find_similar_domain(
    domain: str,
    known: Iterable[str],
    lane: EmbedLane | None = None,
    floor: float = SIMILARITY_FLOOR,
    limit: int = SIMILAR_LIMIT,
) -> Similarity:
    """Rank known domains by embedding similarity; degrade to the rule table."""
    candidates = [d for d in dict.fromkeys(known) if d != domain]
    lane = lane or EmbedLane()
    try:
        base = lane.embed(domain)
        scored = [(cosine(base, lane.embed(other)), other) for other in candidates]
    except _LANE_ERRORS as exc:
        logger.warning("embed_lane_unavailable handler=unlock_similar error=%s", exc)
        return Similarity(
            available=False,
            reason=f"embed lane unavailable ({type(exc).__name__}); rule table used",
            matches=rule_matches(domain, candidates),
        )
    hits = sorted(
        (pair for pair in scored if pair[0] >= floor), key=lambda pair: (-pair[0], pair[1])
    )
    return Similarity(
        available=True, reason="embed lane", matches=[other for _, other in hits[:limit]]
    )
