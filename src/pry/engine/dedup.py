"""Pry — Result Deduplication using SimHash.
Detects near-duplicate content (e.g., 95% similar pages) using SimHash.
Useful for crawl deduplication, change detection, and content grouping."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

import hashlib
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


class SimHash:
    """SimHash implementation for near-duplicate detection."""

    @staticmethod
    def hash(text: str, n_features: int = 128) -> int:
        """Generate a SimHash fingerprint for text."""
        tokens = re.findall(r"\w+", text.lower())
        if not tokens:
            return 0
        vector = [0] * n_features
        for token in tokens:
            token_hash = int(hashlib.md5(token.encode(), usedforsecurity=False).hexdigest(), 16)
            for i in range(n_features):
                if token_hash & (1 << i):
                    vector[i] += 1
                else:
                    vector[i] -= 1
        result = 0
        for i in range(n_features):
            if vector[i] > 0:
                result |= 1 << i
        return result

    @staticmethod
    def hamming_distance(hash1: int, hash2: int) -> int:
        """Count differing bits between two hashes (lower = more similar)."""
        x = hash1 ^ hash2
        distance = 0
        while x:
            distance += x & 1
            x >>= 1
        return distance

    @staticmethod
    def similarity(hash1: int, hash2: int, n_features: int = 128) -> float:
        """Calculate similarity (0-1) between two SimHashes."""
        dist = SimHash.hamming_distance(hash1, hash2)
        return 1.0 - (dist / n_features)


class Deduplicator:
    """Find near-duplicate content across documents."""

    def __init__(self, threshold: float = 0.85):
        self.threshold = threshold
        self._hashes: dict[str, int] = {}

    def add(self, doc_id: str, text: str) -> int:
        """Add a document and return its SimHash."""
        h = SimHash.hash(text)
        self._hashes[doc_id] = h
        return h

    def find_duplicates(self, text: str) -> list[dict[str, Any]]:
        """Find existing documents that are near-duplicates of this text."""
        target_hash = SimHash.hash(text)
        duplicates: list[dict[str, Any]] = []
        for doc_id, doc_hash in self._hashes.items():
            sim = SimHash.similarity(target_hash, doc_hash)
            if sim >= self.threshold:
                duplicates.append(
                    {
                        "doc_id": doc_id,
                        "similarity": round(sim, 3),
                        "distance": SimHash.hamming_distance(target_hash, doc_hash),
                    }
                )
        return sorted(duplicates, key=lambda x: -x["similarity"])

    def cluster(self, texts: dict[str, str]) -> dict[str, list[str]]:
        """Cluster texts by similarity. Returns {cluster_id: [doc_ids]}."""
        hashes = {doc_id: SimHash.hash(text) for doc_id, text in texts.items()}
        clusters: dict[str, list[str]] = {}
        visited: set[str] = set()
        cluster_id = 0
        for doc_id, hash_val in hashes.items():
            if doc_id in visited:
                continue
            cluster = [doc_id]
            visited.add(doc_id)
            for other_id, other_hash in hashes.items():
                if other_id in visited:
                    continue
                if SimHash.similarity(hash_val, other_hash) >= self.threshold:
                    cluster.append(other_id)
                    visited.add(other_id)
            if cluster:
                clusters[f"cluster_{cluster_id}"] = cluster
                cluster_id += 1
        return clusters

    def diff(self, text1: str, text2: str) -> dict[str, Any]:
        """Show what changed between two versions of the same content."""
        hash1 = SimHash.hash(text1)
        hash2 = SimHash.hash(text2)
        sim = SimHash.similarity(hash1, hash2)
        distance = SimHash.hamming_distance(hash1, hash2)
        return {
            "similarity": round(sim, 3),
            "hamming_distance": distance,
            "changed": sim < self.threshold,
            "change_severity": (
                "high"
                if distance > 20
                else "medium"
                if distance > 10
                else "low"
                if distance > 3
                else "minimal"
            ),
        }
