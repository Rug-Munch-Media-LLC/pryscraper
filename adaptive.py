"""Pry — adaptive crawling with information foraging.
Intelligently decides when to stop crawling based on content relevance."""

import logging
import re
from collections import Counter
from typing import Any

logger = logging.getLogger(__name__)


class AdaptiveCrawler:
    """Adaptive crawler that learns site structure and stops when
    enough relevant information has been gathered.

    Uses information foraging theory: crawl stops when the marginal
    benefit of crawling another page drops below a threshold.
    """

    def __init__(
        self,
        max_pages: int = 50,
        max_depth: int = 3,
        relevance_threshold: float = 0.3,
        information_gain_threshold: float = 0.05,
        min_pages: int = 5,
    ):
        self.max_pages = max_pages
        self.max_depth = max_depth
        self.relevance_threshold = relevance_threshold
        self.information_gain_threshold = information_gain_threshold
        self.min_pages = min_pages
        self._visited: set[str] = set()
        self._page_scores: list[dict[str, Any]] = []
        self._keywords: Counter[str] = Counter()
        self._total_pages = 0

    async def should_continue(
        self,
        url: str,
        content: str,
        depth: int,
        query: str = "",
    ) -> dict[str, Any]:
        """Decide whether to continue crawling based on content analysis.

        Returns dict with:
            continue_crawl: bool
            reason: str
            relevance_score: float
            information_gain: float
            pages_crawled: int
        """
        self._total_pages += 1
        self._visited.add(url)

        relevance = self._compute_relevance(content, query) if query else 1.0
        info_gain = self._compute_information_gain(content)

        page_score = {
            "url": url,
            "depth": depth,
            "relevance": relevance,
            "information_gain": info_gain,
            "content_length": len(content),
        }
        self._page_scores.append(page_score)

        if self._total_pages >= self.max_pages:
            return self._decision(
                False, f"Reached max pages ({self.max_pages})", relevance, info_gain
            )

        if depth >= self.max_depth:
            return self._decision(
                False, f"Reached max depth ({self.max_depth})", relevance, info_gain
            )

        if self._total_pages < self.min_pages:
            return self._decision(
                True,
                f"Below minimum pages ({self._total_pages}/{self.min_pages})",
                relevance,
                info_gain,
            )

        if query and relevance < self.relevance_threshold:
            return self._decision(
                False,
                f"Relevance {relevance:.2f} below threshold {self.relevance_threshold}",
                relevance,
                info_gain,
            )

        if info_gain < self.information_gain_threshold and self._total_pages > self.min_pages:
            recent_gains = [s["information_gain"] for s in self._page_scores[-3:]]
            if all(g < self.information_gain_threshold for g in recent_gains):
                return self._decision(
                    False,
                    f"Information gain {info_gain:.4f} below threshold for 3 consecutive pages",
                    relevance,
                    info_gain,
                )

        return self._decision(
            True,
            f"Continuing (relevance={relevance:.2f}, gain={info_gain:.4f})",
            relevance,
            info_gain,
        )

    def _decision(
        self, continue_crawl: bool, reason: str, relevance: float, info_gain: float
    ) -> dict[str, Any]:
        return {
            "continue": continue_crawl,
            "reason": reason,
            "relevance_score": round(relevance, 4),
            "information_gain": round(info_gain, 4),
            "pages_crawled": self._total_pages,
        }

    def _compute_relevance(self, content: str, query: str) -> float:
        """Score how relevant content is to the query (0-1)."""
        query_terms = set(query.lower().split())
        content_lower = content.lower()
        if not query_terms:
            return 1.0

        matches = sum(1 for t in query_terms if t in content_lower)
        return matches / len(query_terms)

    def _compute_information_gain(self, content: str) -> float:
        """Compute information gain as ratio of new terms to total terms."""
        words = set(re.findall(r"\w+", content.lower()))
        new_words = words - set(self._keywords.keys())

        for w in words:
            self._keywords[w] += 1

        if not words:
            return 0.0

        gain = len(new_words) / max(len(words), 1)

        length_factor = min(1.0, len(content) / 5000)

        return gain * length_factor

    def get_stats(self) -> dict[str, Any]:
        """Get crawling statistics."""
        return {
            "pages_crawled": self._total_pages,
            "unique_keywords": len(self._keywords),
            "avg_relevance": (
                round(sum(s["relevance"] for s in self._page_scores) / len(self._page_scores), 3)
                if self._page_scores
                else 0
            ),
            "avg_info_gain": (
                round(
                    sum(s["information_gain"] for s in self._page_scores) / len(self._page_scores),
                    4,
                )
                if self._page_scores
                else 0
            ),
        }

    def reset(self) -> None:
        """Reset crawler state for a new crawl."""
        self._visited.clear()
        self._page_scores.clear()
        self._keywords.clear()
        self._total_pages = 0
