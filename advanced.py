"""Pry — Exclusive features Firecrawl doesn't have.
Diff tracking, LLM summarization, RSS generation, change monitoring,
schema.org extraction, email finder, and more.
All powered by local Ollama — no API keys needed."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

import difflib
import hashlib
import json
import re
from datetime import datetime

import httpx

OLLAMA_BASE = "http://100.100.18.18:11434"


class PryAdvanced:
    """Features Firecrawl charges extra for — or doesn't have at all."""

    def __init__(self, cache=None):
        self.cache = cache
        self._diffs: dict[str, list] = {}

    # ── 1. LLM Page Summary ──
    async def summarize(self, content: str, max_words: int = 100) -> dict:
        """Summarize scraped content using local Ollama. Free, private, no data leakage."""
        if not content or len(content) < 100:
            return {"summary": content, "model": "none"}

        prompt = (
            f"Summarize the following content in {max_words} words or fewer. "
            f"Focus on key facts, data, and actionable information:\n\n{content[:6000]}"
        )
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    f"{OLLAMA_BASE}/api/generate",
                    json={
                        "model": "qwen2.5-coder:3b",
                        "prompt": prompt,
                        "stream": False,
                        "options": {"num_ctx": 8192, "temperature": 0.2},
                    },
                )
                return {"summary": resp.json().get("response", ""), "model": "qwen2.5-coder:3b"}
        except (httpx.HTTPError, httpx.RequestError) as e:
            return {"summary": content[:500], "error": str(e)}

    # ── 2. Diff Tracking — Compare page versions ──
    async def track_diff(self, url: str, new_content: str) -> dict:
        """Compare current content against previous scrape. Returns unified diff.
        First scrape returns 'initial', subsequent returns changes."""
        content_hash = hashlib.md5(new_content.encode(), usedforsecurity=False).hexdigest()

        if url not in self._diffs:
            self._diffs[url] = [
                {
                    "hash": content_hash,
                    "content": new_content,
                    "timestamp": datetime.utcnow().isoformat(),
                }
            ]
            return {"status": "initial", "url": url, "changes": None, "version": 1}

        prev = self._diffs[url][-1]
        if prev["hash"] == content_hash:
            return {
                "status": "unchanged",
                "url": url,
                "changes": [],
                "version": len(self._diffs[url]) + 1,
            }

        diff = list(
            difflib.unified_diff(
                prev["content"].splitlines(keepends=True),
                new_content.splitlines(keepends=True),
                fromfile=f"v{len(self._diffs[url])}",
                tofile=f"v{len(self._diffs[url]) + 1}",
                n=3,
            )
        )
        self._diffs[url].append(
            {
                "hash": content_hash,
                "content": new_content,
                "timestamp": datetime.utcnow().isoformat(),
            }
        )
        return {
            "status": "changed",
            "url": url,
            "changes": diff[:100],
            "version": len(self._diffs[url]),
        }

    # ── 3. Schema.org / JSON-LD extraction ──
    def extract_schema(self, html: str) -> list[dict]:
        """Extract structured data (JSON-LD, microdata) from HTML.
        Many sites embed Schema.org data that's richer than visible content."""
        results = []

        # JSON-LD in <script type="application/ld+json">
        for m in re.finditer(
            r'<script\s+type="application/ld\+json"[^>]*>(.*?)</script>', html, re.I | re.S
        ):
            try:
                data = json.loads(m.group(1))
                results.append(data)
            except json.JSONDecodeError:
                continue

        # Open Graph / Twitter Card meta tags
        og_data = {}
        for m in re.finditer(
            r'<meta\s+(?:property|name)=["\'](og:|twitter:)([^"\']+)["\']\s+content=["\']([^"\']*)["\']',
            html,
            re.I,
        ):
            key = m.group(1) + m.group(2)
            og_data[key] = m.group(3)
        if og_data:
            results.append({"@type": "OpenGraph", **og_data})

        return results

    # ── 4. Email finder ──
    def find_emails(self, content: str) -> list[str]:
        """Extract all email addresses from content.
        Useful for lead generation and contact discovery."""
        emails = set(re.findall(r"[\w.+-]+@[\w-]+\.[\w.-]+", content))
        # Filter out common false positives
        return sorted(
            [e for e in emails if not e.endswith((".png", ".jpg", ".css", ".js", ".svg"))]
        )

    # ── 5. Social media link finder ──
    def find_social_links(self, html: str) -> dict[str, str]:
        """Find social media profile links in HTML."""
        patterns = {
            "twitter": r"https?://(?:www\.)?(?:twitter\.com|x\.com)/[A-Za-z0-9_]+",
            "github": r"https?://(?:www\.)?github\.com/[A-Za-z0-9_-]+",
            "linkedin": r"https?://(?:www\.)?linkedin\.com/(?:company|in)/[A-Za-z0-9_-]+",
            "youtube": r"https?://(?:www\.)?youtube\.com/(?:@|c/|channel/|user/)[A-Za-z0-9_-]+",
            "telegram": r"https?://(?:t\.me|telegram\.me)/[A-Za-z0-9_]+",
            "discord": r"https?://(?:www\.)?discord\.(?:gg|com)/[A-Za-z0-9_]+",
            "reddit": r"https?://(?:www\.)?reddit\.com/r/[A-Za-z0-9_]+",
        }
        found = {}
        for platform, pattern in patterns.items():
            m = re.search(pattern, html, re.I)
            if m:
                found[platform] = m.group(0)
        return found

    # ── 6. AI Categorization ──
    async def categorize(self, content: str) -> list[str]:
        """Use local AI to categorize scraped content into topics.
        Returns tags like 'technology', 'crypto', 'news', 'tutorial', etc."""
        prompt = (
            "Categorize the following content. Return ONLY a JSON array of 2-5 category tags. "
            f'Example: ["technology", "crypto", "analysis"]\n\nContent:\n{content[:4000]}'
        )
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    f"{OLLAMA_BASE}/api/generate",
                    json={
                        "model": "qwen2.5-coder:3b",
                        "prompt": prompt,
                        "stream": False,
                        "options": {"num_ctx": 4096, "temperature": 0.1},
                    },
                )
                raw = resp.json().get("response", "")
                arr_match = re.search(r"\[.*?\]", raw, re.S)
                return json.loads(arr_match.group(0)) if arr_match else ["uncategorized"]
        except (json.JSONDecodeError, ValueError):
            return ["uncategorized"]

    # ── 7. Keyword density analysis ──
    def keyword_density(self, content: str, top_n: int = 20) -> list[dict]:
        """Analyze word frequency in content. Useful for SEO and content analysis."""
        words = re.findall(r"\b[a-zA-Z]{3,}\b", content.lower())
        stop_words = {
            "the",
            "and",
            "for",
            "are",
            "but",
            "not",
            "you",
            "all",
            "can",
            "was",
            "has",
            "had",
            "its",
            "that",
            "this",
            "with",
            "from",
            "they",
        }
        freq = {}
        for w in words:
            if w not in stop_words:
                freq[w] = freq.get(w, 0) + 1

        sorted_words = sorted(freq.items(), key=lambda x: -x[1])[:top_n]
        total = len(words)
        return [
            {"word": w, "count": c, "density": f"{c / total * 100:.2f}%"} for w, c in sorted_words
        ]

    # ── 8. Readability score ──
    def readability(self, content: str) -> dict:
        """Calculate Flesch Reading Ease score for content."""
        if not content:
            return {"score": 0, "level": "empty"}

        sentences = len(re.findall(r"[.!?]+", content))
        words = len(re.findall(r"\b\w+\b", content))
        syllables = len(re.findall(r"[aeiouy]+", content.lower()))

        if sentences == 0 or words == 0:
            return {"score": 0, "level": "empty"}

        score = 206.835 - 1.015 * (words / sentences) - 84.6 * (syllables / words)
        score = max(0, min(100, score))

        if score >= 90:
            level = "very easy"
        elif score >= 80:
            level = "easy"
        elif score >= 70:
            level = "fairly easy"
        elif score >= 60:
            level = "standard"
        elif score >= 50:
            level = "fairly difficult"
        elif score >= 30:
            level = "difficult"
        else:
            level = "very difficult"

        return {"score": round(score, 1), "level": level, "words": words, "sentences": sentences}
