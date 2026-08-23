"""Pry - Apify Actor Factory: per-actor item processors.

Each niche actor must DO what its store description promises - not just
run a generic scrape. Processors take Pry's raw scrape result plus input
options and return the enriched dataset item.

Every processor is pure (HTML/text in -> dict out) so tests need no network.

Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any
from urllib.parse import urljoin


def _base_item(url: str, result: dict[str, Any]) -> dict[str, Any]:
    return {
        "url": url,
        "status": result.get("status", "error"),
        "method": result.get("method", "unknown"),
        "scraped_at": result.get("scraped_at"),
        "content": result.get("content", ""),
        "error": result.get("error", ""),
    }


def _raw_html(result: dict[str, Any]) -> str:
    return result.get("raw_html") or ""


# ── corpus builder ───────────────────────────────────────────────────────────

_seen_hashes: set[int] = set()


def _simhash64(text: str) -> int:
    import hashlib

    tokens = re.findall(r"\w+", text.lower())
    if not tokens:
        return 0
    vector = [0] * 64
    for token in tokens:
        h = int(hashlib.md5(token.encode(), usedforsecurity=False).hexdigest(), 16)
        for i in range(64):
            vector[i] += 1 if h & (1 << i) else -1
    return sum(1 << i for i in range(64) if vector[i] > 0)


def process_corpus(
    url: str, result: dict[str, Any], options: dict[str, Any], state: dict[str, Any]
) -> dict[str, Any]:
    """Filter boilerplate shells and near-duplicates for clean corpora."""
    item = _base_item(url, result)
    content = item["content"] or ""
    min_chars = int(options.get("min_content_chars", 500) or 0)
    if item["status"] == "ok" and len(content) < min_chars:
        item["status"] = "skipped"
        item["error"] = f"content shorter than {min_chars} chars"
        item.pop("content", None)
        return item
    if options.get("dedupe", True) and item["status"] == "ok":
        fingerprint = _simhash64(content)
        if fingerprint and fingerprint in state.setdefault("seen_hashes", set()):
            item["status"] = "skipped"
            item["error"] = "near-duplicate of an earlier document"
            item.pop("content", None)
            return item
        if fingerprint:
            state["seen_hashes"].add(fingerprint)
    return item


# ── SEO auditor ──────────────────────────────────────────────────────────────

_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
_META_RE = re.compile(r"<meta[^>]+name=[\"']description[\"'][^>]+content=[\"']([^\"']*)[\"']", re.I)
_META_RE_ALT = re.compile(
    r"<meta[^>]+content=[\"']([^\"']*)[\"'][^>]+name=[\"']description[\"']", re.I
)
_CANONICAL_RE = re.compile(r"<link[^>]+rel=[\"']canonical[\"'][^>]+href=[\"']([^\"']*)[\"']", re.I)
_HEADING_RE = re.compile(r"<h([1-6])[^>]*>(.*?)</h\1>", re.I | re.S)
_TAG_STRIP_RE = re.compile(r"<[^>]+>")


def process_seo(
    url: str, result: dict[str, Any], options: dict[str, Any], state: dict[str, Any]
) -> dict[str, Any]:
    """Extract SEO signals: title, meta description, headings, canonical."""
    item = _base_item(url, result)
    html = _raw_html(result)
    if item["status"] != "ok":
        return item
    title_m = _TITLE_RE.search(html)
    desc_m = _META_RE.search(html) or _META_RE_ALT.search(html)
    canonical_m = _CANONICAL_RE.search(html)
    headings: dict[str, list[str]] = {}
    if options.get("check_headings", True):
        for level, text in _HEADING_RE.findall(html):
            key = f"h{level}"
            headings.setdefault(key, []).append(_TAG_STRIP_RE.sub("", text).strip()[:120])
    issues: list[str] = []
    if not title_m:
        issues.append("missing_title")
    elif len(title_m.group(1).strip()) > 65:
        issues.append("title_too_long")
    if not desc_m:
        issues.append("missing_meta_description")
    canonical = canonical_m.group(1) if canonical_m else ""
    if options.get("check_canonicals", True) and not canonical:
        issues.append("missing_canonical")
    item["seo"] = {
        "title": title_m.group(1).strip()[:200] if title_m else "",
        "meta_description": (desc_m.group(1).strip()[:300] if desc_m else ""),
        "canonical": urljoin(url, canonical) if canonical else "",
        "headings": headings,
        "issues": issues,
    }
    return item


# ── lead harvester ───────────────────────────────────────────────────────────

_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
_PHONE_RE = re.compile(r"(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}")
_SOCIAL_RE = re.compile(
    r"https?://(?:www\.)?(linkedin\.com|twitter\.com|x\.com|facebook\.com)"
    r"/[A-Za-z0-9_.\-/]+",
    re.I,
)


def process_leads(
    url: str, result: dict[str, Any], options: dict[str, Any], state: dict[str, Any]
) -> dict[str, Any]:
    """Extract publicly listed emails, phones and social links."""
    item = _base_item(url, result)
    html = _raw_html(result)
    if item["status"] != "ok":
        return item
    emails = sorted(set(_EMAIL_RE.findall(html)))
    phones = sorted(set(_PHONE_RE.findall(html)))[:10]
    socials = sorted({m.rstrip("/.") for m in _SOCIAL_RE.findall(html)})
    item["leads"] = {
        "emails": emails[:25],
        "phones": phones,
        "social_links": socials if options.get("include_social_links", True) else [],
    }
    return item


# ── news monitor ─────────────────────────────────────────────────────────────

_ARTICLE_LINK_RE = re.compile(
    r"<a[^>]+href=[\"']([^\"']*/(?:20\d\d|article|news|blog)[^\"']*)[\"']", re.I
)


def process_news(
    url: str, result: dict[str, Any], options: dict[str, Any], state: dict[str, Any]
) -> dict[str, Any]:
    """Emit article links found on a news/blog page (full-text via content)."""
    item = _base_item(url, result)
    html = _raw_html(result)
    if item["status"] != "ok":
        return item
    cap = int(options.get("max_articles_per_source", 20) or 20)
    seen: set[str] = set()
    articles: list[str] = []
    for href in _ARTICLE_LINK_RE.findall(html):
        absolute = urljoin(url, href).split("#")[0]
        if absolute not in seen:
            seen.add(absolute)
            articles.append(absolute)
        if len(articles) >= cap:
            break
    item["articles"] = articles
    return item


# ── price watcher ────────────────────────────────────────────────────────────

_JSONLD_RE = re.compile(
    r"<script[^>]+type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>", re.I | re.S
)


def _price_from_jsonld(html: str) -> tuple[float | None, str, str]:
    """Extract (price, currency, name) from schema.org/Product JSON-LD."""
    for block in _JSONLD_RE.findall(html):
        try:
            data = json.loads(block.strip())
        except json.JSONDecodeError:
            continue
        candidates = data if isinstance(data, list) else [data]
        for node in candidates:
            graph = node.get("@graph") if isinstance(node, dict) else None
            for obj in ([node] if isinstance(node, dict) else []) + (graph or []):
                if not isinstance(obj, dict):
                    continue
                if str(obj.get("@type", "")).lower() != "product":
                    continue
                offers = obj.get("offers") or {}
                if isinstance(offers, list):
                    offers = offers[0] if offers else {}
                price = offers.get("price") or offers.get("lowPrice")
                currency = offers.get("priceCurrency", "")
                name = str(obj.get("name", ""))[:200]
                try:
                    return float(str(price).replace(",", "")), currency, name
                except (TypeError, ValueError):
                    continue
    return None, "", ""


def process_price(
    url: str, result: dict[str, Any], options: dict[str, Any], state: dict[str, Any]
) -> dict[str, Any]:
    """Schema.org/Product structured-data-first price extraction."""
    item = _base_item(url, result)
    html = _raw_html(result)
    if item["status"] != "ok":
        return item
    price, currency, name = _price_from_jsonld(html)
    if price is None:
        item["status"] = "error"
        item["error"] = "no structured product price found"
        return item
    item["product"] = {
        "name": name,
        "price": price,
        "currency": currency or options.get("currency_hint", "USD"),
    }
    return item


# ── registry ─────────────────────────────────────────────────────────────────

ProcessorFn = Callable[[str, dict[str, Any], dict[str, Any], dict[str, Any]], dict[str, Any]]

PROCESSORS: dict[str, ProcessorFn] = {
    "corpus": process_corpus,
    "seo": process_seo,
    "leads": process_leads,
    "news": process_news,
    "price": process_price,
}


def get_processor(name: str | None) -> ProcessorFn | None:
    return PROCESSORS.get(name or "")
