"""Pry — SEO Content Change Monitor.
Track competitor meta tags, titles, descriptions, headings, content changes."""
from paths import PRY_DATA_DIR

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

import hashlib
import json
import logging
import os
import re
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

SEO_DIR = PRY_DATA_DIR / "seo"
SEO_DIR.mkdir(parents=True, exist_ok=True)


async def analyze_seo(url: str) -> dict[str, Any]:
    """Analyze SEO elements from a URL."""
    from lxml import html as lxml_html

    from client import get_client

    client = await get_client()
    try:
        resp = await client.get(
            url,
            timeout=30,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (SEO Monitor)"},
        )
        if not resp.is_success:
            return {"url": url, "error": f"HTTP {resp.status_code}"}

        tree = lxml_html.fromstring(resp.text)

        result: dict[str, Any] = {
            "url": url,
            "title": _get_title(tree),
            "meta_description": _get_meta_content(tree, "description"),
            "meta_keywords": _get_meta_content(tree, "keywords"),
            "h1": _get_headings(tree, "h1"),
            "h2": _get_headings(tree, "h2"),
            "canonical": _get_attr(tree, 'link[rel="canonical"]', "href"),
            "og_title": _get_meta_content(tree, "og:title"),
            "og_description": _get_meta_content(tree, "og:description"),
            "og_image": _get_meta_content(tree, "og:image"),
            "twitter_title": _get_meta_content(tree, "twitter:title"),
            "twitter_description": _get_meta_content(tree, "twitter:description"),
            "robots_meta": _get_meta_content(tree, "robots"),
            "charset": _get_charset(tree, resp),
            "viewport": _get_meta_content(tree, "viewport"),
            "word_count": _count_words(resp.text),
            "links_internal": _count_links(tree, url, internal=True),
            "links_external": _count_links(tree, url, internal=False),
            "has_schema": _has_schema(resp.text),
            "hreflang_tags": _get_hreflangs(tree),
            "status_code": resp.status_code,
            "content_type": resp.headers.get("content-type", ""),
            "last_modified": resp.headers.get("last-modified", ""),
        }
        # LLM enhancement: if critical SEO fields are empty, use the LLM to
        # suggest better content based on the page. Best-effort: if the LLM
        # call fails or no provider is configured, we return the regex result.
        missing_critical = [f for f in ("title", "meta_description", "h1") if not result.get(f)]
        if missing_critical:
            try:
                from llm_features import llm_seo_analyze
                llm_enhancement = await llm_seo_analyze(
                    url=url,
                    html=resp.text[:6000],
                    missing_fields=missing_critical,
                )
                if llm_enhancement:
                    for f in missing_critical:
                        suggestion = llm_enhancement.get(f)
                        if suggestion and not result.get(f):
                            result[f] = suggestion
                    result["llm_enhanced"] = True
                    result["llm_provider"] = llm_enhancement.get("llm_provider", "")
                    result["llm_cost_usd"] = llm_enhancement.get("llm_cost_usd", 0.0)
            except (httpx.HTTPError, httpx.RequestError) as e:
                logger.debug("llm_seo_enhance_failed", extra={"url": url, "error": str(e)[:80]})

        return result
    except (httpx.HTTPError, httpx.RequestError) as e:
        return {"url": url, "error": str(e)[:200]}


def _get_title(tree: Any) -> str:
    el = tree.find(".//title")
    return el.text_content().strip()[:200] if el is not None and el.text is not None else ""


def _get_meta_content(tree: Any, name: str) -> str:
    for el in tree.xpath(f'//meta[@name="{name}"] | //meta[@property="{name}"]'):
        content = el.get("content", "")
        return content.strip()[:500] if content else ""
    return ""


def _get_headings(tree: Any, tag: str) -> list[str]:
    return [
        h.text_content().strip()[:200] for h in tree.xpath(f"//{tag}") if h.text_content().strip()
    ]


def _get_attr(tree: Any, selector: str, attr: str) -> str:
    els = tree.cssselect(selector)
    return str(els[0].get(attr, ""))[:500] if els else ""


def _get_charset(tree: Any, resp: Any) -> str:
    meta = tree.find(".//meta[@charset]")
    if meta is not None:
        return str(meta.get("charset", ""))
    ct = resp.headers.get("content-type", "")
    m = re.search(r"charset=([\w-]+)", ct)
    return m.group(1) if m else ""


def _count_words(html: str) -> int:
    text = re.sub(r"<[^>]+>", " ", html)
    words = re.findall(r"\w+", text)
    return len(words)


def _count_links(tree: Any, base_url: str, internal: bool) -> int:
    from urllib.parse import urlparse

    base_domain = urlparse(base_url).netloc
    count = 0
    for a in tree.xpath("//a[@href]"):
        href = a.get("href", "")
        if href.startswith("http") or href.startswith("//"):
            domain = urlparse(href).netloc
            if (internal and domain == base_domain) or (not internal and domain != base_domain):
                count += 1
        elif internal and href.startswith("/"):
            count += 1
    return count


def _has_schema(html: str) -> bool:
    return bool(re.search(r'<script[^>]*type="application/ld\+json"', html))


def _get_hreflangs(tree: Any) -> list[dict[str, str]]:
    tags = []
    for el in tree.xpath("//link[@hreflang]"):
        tags.append(
            {
                "hreflang": el.get("hreflang", ""),
                "href": el.get("href", ""),
            }
        )
    return tags


async def track_seo_changes(url: str) -> dict[str, Any]:
    """Track SEO changes since last analysis."""
    url_hash = hashlib.sha256(url.encode()).hexdigest()[:16]
    history_path = SEO_DIR / f"seo_{url_hash}.json"

    # Get current SEO data
    current = await analyze_seo(url)
    if "error" in current:
        return current

    # Load previous data
    previous: dict[str, Any] | None = None
    if history_path.exists():
        with suppress(json.JSONDecodeError, OSError):
            previous = json.loads(history_path.read_text())

    # Detect changes
    changes = []
    if previous:
        tracked_fields = ["title", "meta_description", "meta_keywords", "h1", "h2", "canonical"]
        for field in tracked_fields:
            old_val = previous.get(field)
            new_val = current.get(field)
            if old_val != new_val:
                changes.append(
                    {
                        "field": field,
                        "type": "changed",
                        "from": old_val,
                        "to": new_val,
                        "severity": "high" if field in ("title", "meta_description") else "medium",
                    }
                )

        # Word count change
        old_words = previous.get("word_count", 0)
        new_words = current.get("word_count", 0)
        if old_words and new_words and abs(new_words - old_words) > 100:
            changes.append(
                {
                    "field": "word_count",
                    "type": "changed",
                    "from": old_words,
                    "to": new_words,
                    "delta": new_words - old_words,
                    "severity": "low",
                }
            )

    # Save current data
    with suppress(OSError):
        history_path.write_text(json.dumps(current, indent=2))

    return {
        "url": url,
        "current": current,
        "changes": changes,
        "change_count": len(changes),
        "has_changes": len(changes) > 0,
        "is_first_scan": previous is None,
        "checked_at": datetime.now(UTC).isoformat(),
    }


async def get_seo_keyword_insights(url: str, keywords: list[str]) -> dict[str, Any]:
    """Analyze which keywords a URL is targeting based on content analysis."""
    from client import get_client

    client = await get_client()
    try:
        resp = await client.get(url, timeout=30, follow_redirects=True)
        if not resp.is_success:
            return {"url": url, "error": f"HTTP {resp.status_code}"}

        text = resp.text.lower()
        results = []
        for keyword in keywords:
            kw_lower = keyword.lower().strip()
            # Check in title
            title = _get_title_from_html(text)
            in_title = kw_lower in title.lower() if title else False
            # Check in H1
            h1s = re.findall(r"<h1[^>]*>(.*?)</h1>", text, re.DOTALL)
            in_h1 = any(kw_lower in h.lower() for h in h1s)
            # Check in meta description
            meta_desc = _get_meta_from_html(text, "description")
            in_meta = kw_lower in meta_desc.lower() if meta_desc else False
            # Count in body
            body = re.sub(r"<[^>]+>", " ", text)
            frequency = body.lower().count(kw_lower)

            results.append(
                {
                    "keyword": keyword,
                    "frequency": frequency,
                    "in_title": in_title,
                    "in_h1": in_h1,
                    "in_meta_description": in_meta,
                    "density": round(frequency / max(len(body.split()), 1) * 100, 2)
                    if frequency > 0
                    else 0,
                }
            )

        return {
            "url": url,
            "keywords_analyzed": len(keywords),
            "results": results,
        }
    except (httpx.HTTPError, httpx.RequestError) as e:
        return {"url": url, "error": str(e)[:200]}


def _get_title_from_html(html: str) -> str:
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.DOTALL)
    return m.group(1).strip() if m else ""


def _get_meta_from_html(html: str, name: str) -> str:
    m = re.search(f"<meta[^>]*name=[\"']{name}[\"'][^>]*content=[\"']([^\"']*)[\"']", html)
    if m:
        return m.group(1)
    m = re.search(f"<meta[^>]*property=[\"']{name}[\"'][^>]*content=[\"']([^\"']*)[\"']", html)
    return m.group(1) if m else ""
