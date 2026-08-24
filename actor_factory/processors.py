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

    # Social preview (og:) tags - shared by meta auditors.
    og: dict[str, str] = {}
    _og_re = re.compile(
        r"""<meta[^>]+(?:property|name)=["']([^"']*)["'][^>]+content=["']([^"']*)["']""",
        re.I,
    )
    for m in _og_re.finditer(html):
        key, val = m.group(1), m.group(2)
        if key.startswith("og:"):
            og[key] = val.strip()[:300]

    if "og:title" not in og:
        issues.append("missing_og_title")
    if "og:image" not in og:
        issues.append("missing_og_image")

    # Image alt-text audit (accessibility signal).
    imgs = re.findall(r"<img\b[^>]*>", html, re.I)
    _alt_re = re.compile(r"""alt=["'][^"']*["']""", re.I)
    missing_alt = sum(1 for tag in imgs if not _alt_re.search(tag))
    if imgs and missing_alt == len(imgs):
        issues.append("all_images_missing_alt")

    # Privacy/cookie compliance markers (GDPR checker).
    lower = html.lower()
    privacy_markers = {
        "cookie_banner": any(
            k in lower for k in ("cookiebot", "onetrust", "cookie-consent", "cookieconsent")
        ),
        "privacy_page_linked": 'href="' in lower
        and ("/privacy" in lower or "/datenschutz" in lower),
    }

    item["seo"] = {
        "title": title_m.group(1).strip()[:200] if title_m else "",
        "meta_description": (desc_m.group(1).strip()[:300] if desc_m else ""),
        "canonical": urljoin(url, canonical) if canonical else "",
        "headings": headings,
        "issues": issues,
        "og_tags": og,
        "images_total": len(imgs),
        "images_missing_alt": missing_alt,
        "privacy_markers": privacy_markers,
    }
    return item


# ── generic page auditor (accessibility / gdpr / social-cards / ad-intel) ────

_SCRIPT_SRC_RE = re.compile(r"""<script[^>]+src=["']([^"']+)["']""", re.I)
_AD_NETWORK_MARKERS = {
    "google adsense": "adsbygoogle",
    "google ad manager": "googletagmanager.com/gtm",
    "meta audience": "connect.facebook.net",
    "amazon associates": "amazon-adsystem",
    "taboola": "taboola",
    "outbrain": "outbrain",
    "criteo": "criteo",
    "media.net": "media.net",
}
_CHECK_IDS = ("accessibility", "compliance", "social_cards", "ad_intel", "links")


def _audit_findings(html: str, url: str, options: dict[str, Any]) -> list[dict[str, Any]]:
    """Run enabled checks; each finding: {check, status(ok|warn|fail), detail}."""
    findings: list[dict[str, Any]] = []
    lower = html.lower()

    if options.get("check_accessibility", True):
        imgs = re.findall(r"<img\b[^>]*>", html, re.I)
        _alt_re = re.compile(r"""alt=["'][^"']*["']""", re.I)
        missing_alt = sum(1 for tag in imgs if not _alt_re.search(tag))
        findings.append(
            {
                "check": "images_alt_text",
                "status": "ok"
                if not imgs or missing_alt == 0
                else ("warn" if missing_alt < len(imgs) else "fail"),
                "detail": f"{missing_alt}/{len(imgs)} images missing alt text",
            }
        )
        if not re.search(r"<html[^>]+lang=", html, re.I):
            findings.append(
                {
                    "check": "html_lang",
                    "status": "warn",
                    "detail": "<html> element has no lang attribute",
                }
            )

    if options.get("check_compliance", True):
        banner = any(
            k in lower for k in ("cookiebot", "onetrust", "cookie-consent", "cookieconsent")
        )
        findings.append(
            {
                "check": "cookie_consent_mechanism",
                "status": "ok" if banner else "warn",
                "detail": "consent platform detected"
                if banner
                else "no known consent platform found",
            }
        )
        privacy_linked = "/privacy" in lower or "/datenschutz" in lower
        findings.append(
            {
                "check": "privacy_policy_link",
                "status": "ok" if privacy_linked else "fail",
                "detail": "privacy policy link found"
                if privacy_linked
                else "no /privacy link on page",
            }
        )

    if options.get("check_social_cards", True):
        og_titles = len(re.findall(r"""property=["']og:title["']""", html, re.I))
        og_images = len(re.findall(r"""property=["']og:image["']""", html, re.I))
        findings.append(
            {
                "check": "open_graph_tags",
                "status": "ok" if og_titles and og_images else "fail",
                "detail": f"og:title x{og_titles}, og:image x{og_images}",
            }
        )

    if options.get("check_ad_intel", False):
        networks = sorted(
            {label for label, marker in _AD_NETWORK_MARKERS.items() if marker in lower}
        )
        findings.append(
            {
                "check": "ad_networks",
                "status": "ok",
                "detail": ", ".join(networks) if networks else "no known ad network scripts",
            }
        )

    if options.get("check_links", True):
        anchors = re.findall(r"""<a\b[^>]+href=["']([^"']+)["']""", html, re.I)
        internal = sum(1 for a in anchors if a.startswith("#") or urljoin(url, a).startswith(url))
        findings.append(
            {
                "check": "link_inventory",
                "status": "ok",
                "detail": f"{len(anchors)} links ({internal} internal)",
            }
        )
    return findings


def process_audit(
    url: str, result: dict[str, Any], options: dict[str, Any], state: dict[str, Any]
) -> dict[str, Any]:
    """Compliance/quality audit: severity-ranked findings instead of raw HTML."""
    item = _base_item(url, result)
    if item["status"] != "ok":
        return item
    html = _raw_html(result) or item["content"] or ""
    findings = _audit_findings(html, url, options)
    failed = sum(1 for f in findings if f["status"] == "fail")
    warned = sum(1 for f in findings if f["status"] == "warn")
    item.pop("content", None)
    item["audit"] = {
        "score": max(0, 100 - failed * 25 - warned * 10),
        "findings": findings,
        "failed": failed,
        "warnings": warned,
    }
    return item


# ── change monitor (diff-by-simhash against prior runs) ──────────────────────


def process_monitor(
    url: str, result: dict[str, Any], options: dict[str, Any], state: dict[str, Any]
) -> dict[str, Any]:
    """Baseline + change detection: stable hash of visible content; emits
    `changed` only when the fingerprint differs from the previous run."""
    item = _base_item(url, result)
    if item["status"] != "ok":
        return item
    content = item["content"] or ""
    threshold = int(options.get("change_threshold", 3) or 3)
    fingerprint = _simhash64(content)
    seen: dict[str, int] = state.setdefault("fingerprints", {})
    previous = seen.get(url)
    changed: bool | None
    if previous is None:
        changed = None  # baseline run - nothing to compare yet
        detail = "baseline captured"
    elif previous == fingerprint:
        changed = False
        detail = "unchanged since previous capture"
    else:
        distance = bin(previous ^ fingerprint).count("1")
        changed = distance > threshold
        detail = f"simhash distance {distance} (threshold {threshold})"
    seen[url] = fingerprint
    include_unchanged = bool(options.get("include_unchanged", False))
    if changed is False and not include_unchanged:
        item["status"] = "skipped"
        item["error"] = "unchanged"
        item.pop("content", None)
    item.pop("content", None)
    item["monitor"] = {
        "fingerprint": str(fingerprint),
        "changed": changed,
        "detail": detail,
    }
    return item


# ── structured-data extractor (schema.org JSON-LD) ──────────────────────────

# Matches quoted AND unquoted attribute forms - Yoast SEO (#1 WordPress
# plugin) emits <script type=application/ld+json class=...> unquoted,
# which is valid HTML5. Found via live back-testing.
_JSONLD_RE = re.compile(
    r"""<script[^>]+type=["']?application/ld\+json["']?[^>]*>(.*?)</script>""",
    re.I | re.S,
)


def _jsonld_objects(html: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for m in _JSONLD_RE.finditer(html):
        try:
            data = json.loads(m.group(1).strip())
        except json.JSONDecodeError:
            continue
        candidates = data.get("@graph", [data]) if isinstance(data, dict) else data
        for obj in candidates if isinstance(candidates, list) else [candidates]:
            if isinstance(obj, dict) and obj.get("@type"):
                out.append(obj)
    return out


def process_extract(
    url: str, result: dict[str, Any], options: dict[str, Any], state: dict[str, Any]
) -> dict[str, Any]:
    """Pull schema.org JSON-LD entities (Recipe, Product, Review, Event,
    Course, JobPosting...) into clean per-item fields. Falls back to a
    metadata-only item when the page embeds no structured data."""
    item = _base_item(url, result)
    if item["status"] != "ok":
        return item
    html = _raw_html(result) or ""
    wanted = options.get("types")  # e.g. ["Recipe"] - None means any
    entities: list[dict[str, Any]] = []
    for obj in _jsonld_objects(html):
        types = obj.get("@type")
        types = types if isinstance(types, list) else [types]
        if wanted and not any(t in wanted for t in types):
            continue
        flat = {
            k: v
            for k, v in obj.items()
            if isinstance(v, (str, int, float, bool)) and k != "@context"
        }
        entities.append({"type": ",".join(str(t) for t in types), "fields": flat})
    if not entities:
        item["status"] = "skipped"
        item["error"] = "no matching structured data on page"
        item.pop("content", None)
        return item
    item.pop("content", None)
    item["extracted"] = {"entities": entities[:10]}
    return item


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
    has_form = bool(re.search(r"<form\b", html, re.I))
    mailto = bool(re.search(r'href=["\']mailto:', html, re.I))
    item["leads"] = {
        "emails": emails[:25],
        "phones": phones,
        "social_links": socials if options.get("include_social_links", True) else [],
        "contact_form_present": has_form or mailto,
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

# Same unquoted-attribute tolerance as the extractor regex above (Yoast).
_JSONLD_RE = re.compile(
    r"""<script[^>]+type=["']?application/ld\+json["']?[^>]*>(.*?)</script>""",
    re.I | re.S,
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


def process_backlinks(
    url: str, result: dict[str, Any], options: dict[str, Any], state: dict[str, Any]
) -> dict[str, Any]:
    """Harvest external outbound links (domain-level) for backlink intel."""
    item = _base_item(url, result)
    html = _raw_html(result)
    if item["status"] != "ok":
        return item
    base_domain = url.split("/")[2] if "://" in url else ""
    externals: dict[str, str] = {}
    for href in re.findall(r"""href=["'](https?://[^"']+)["']""", html, re.I):
        target = href.rstrip("/.")
        domain = target.split("/")[2] if "://" in target else ""
        if domain and domain != base_domain and domain not in externals:
            externals[domain] = target
    item["outbound_domains"] = sorted(externals)[:100]
    return item


# ── technology stack detector (HTML signature matching) ─────────────────────

_TECH_SIGNATURES: tuple[tuple[str, str, str], ...] = (
    # (category, name, html marker - lowercase)
    ("cms", "WordPress", "wp-content"),
    ("cms", "Drupal", "/sites/default/files"),
    ("cms", "Wix", "wix.com"),
    ("cms", "Squarespace", "squarespace"),
    ("ecommerce", "Shopify", "cdn.shopify.com"),
    ("ecommerce", "WooCommerce", "woocommerce"),
    ("ecommerce", "Magento", "magento"),
    ("framework", "Next.js", "/_next/"),
    ("framework", "Nuxt", "/_nuxt/"),
    ("framework", "React", "data-reactroot"),
    ("framework", "Vue.js", "data-v-app"),
    ("framework", "Angular", "ng-version"),
    ("js_lib", "jQuery", "jquery"),
    ("analytics", "Google Analytics", "google-analytics.com"),
    ("analytics", "Google Analytics 4", "gtag/js"),
    ("analytics", "Plausible", "plausible.io"),
    ("analytics", "Matomo", "matomo"),
    ("tag_manager", "Google Tag Manager", "googletagmanager.com/gtm"),
    ("tag_manager", "Segment", "cdn.segment.com"),
    ("marketing", "HubSpot", "hs-scripts.com"),
    ("marketing", "Mailchimp", "chimpstatic.com"),
    ("support", "Intercom", "intercom"),
    ("support", "Zendesk", "zendesk"),
    ("support", "Crisp", "crisp.chat"),
    ("payments", "Stripe", "js.stripe.com"),
    ("payments", "PayPal", "paypal.com/sdk"),
    ("hosting_cdn", "Cloudflare", "cloudflare"),
    ("hosting_cdn", "Vercel", "vercel.app"),
    ("hosting_cdn", "Netlify", "netlify"),
)


def process_tech(
    url: str, result: dict[str, Any], options: dict[str, Any], state: dict[str, Any]
) -> dict[str, Any]:
    """Detect website technologies from HTML signatures (Wappalyzer-style,
    signature-based only - no fingerprinting of visitors)."""
    item = _base_item(url, result)
    if item["status"] != "ok":
        return item
    html = (_raw_html(result) or item["content"] or "").lower()
    found: list[dict[str, str]] = []
    for category, name, marker in _TECH_SIGNATURES:
        if marker in html:
            found.append({"category": category, "name": name})
    generator_m = re.search(
        r"""<meta[^>]+name=["']generator["'][^>]+content=["']([^"']+)["']""",
        _raw_html(result) or "",
        re.I,
    )
    if generator_m:
        found.insert(0, {"category": "generator_meta", "name": generator_m.group(1)[:80]})
    item.pop("content", None)
    item["tech"] = {
        "technologies": found,
        "count": len(found),
        "categories": sorted({t["category"] for t in found}),
    }
    return item


# ── JSON API processor (public-API-backed Actors) ────────────────────────────


def _flatten_json(obj: Any, prefix: str = "", depth: int = 0, out: dict | None = None) -> dict:
    """Flatten nested dicts/lists into dot-notation keys (bounded)."""
    out = {} if out is None else out
    if depth > 4:
        return out
    if isinstance(obj, dict):
        for k, v in obj.items():
            key = f"{prefix}.{k}" if prefix else str(k)
            if isinstance(v, (dict, list)):
                _flatten_json(v, key, depth + 1, out)
            elif isinstance(v, (str, int, float, bool)) or v is None:
                out[key] = v
    elif isinstance(obj, list):
        for i, v in enumerate(obj[:20]):
            _flatten_json(v, f"{prefix}[{i}]", depth + 1, out)
    return out


def process_jsondata(
    url: str, result: dict[str, Any], options: dict[str, Any], state: dict[str, Any]
) -> dict[str, Any]:
    """Parse JSON API responses into structured dataset items.

    Powers the public-API-backed Actor lineup (GitHub, npm, PyPI, RDAP,
    iTunes, HN, exchange rates...): the engine fetches the URL, this
    processor turns the JSON body into clean items. Options:
      data_path - dot/bracket path to the array of interest (e.g. "items")
      max_items - cap per response (default 50)
    """
    item = _base_item(url, result)
    raw = result.get("raw_html") or item["content"] or ""
    text = raw.strip()
    # strip accidental markdown/code fences around the payload
    if text.startswith("```"):
        text = text.strip("`").lstrip("json\n").strip()
    start_obj = text.find("{")
    start_arr = text.find("[")
    # whichever container opens first wins - finding "{" first would
    # truncate a top-level array to its first element
    if start_arr != -1 and (start_obj == -1 or start_arr < start_obj):
        start = start_arr
    else:
        start = start_obj
    if start == -1:
        item["status"] = "skipped"
        item["error"] = "response is not JSON"
        item.pop("content", None)
        return item
    try:
        payload = json.loads(text[start:])
    except json.JSONDecodeError as exc:
        item["status"] = "skipped"
        item["error"] = f"invalid JSON: {exc}"
        item.pop("content", None)
        return item

    data_path = options.get("data_path")
    if data_path:
        cur: Any = payload
        for part in re.findall(r"[^\[\]]+|\[\d+\]", str(data_path)):
            try:
                cur = cur[int(part[1:-1])] if part.startswith("[") else cur[part]
            except (KeyError, IndexError, TypeError, ValueError):
                cur = None
                break
        payload = cur if cur is not None else []

    records = payload if isinstance(payload, list) else [payload]
    max_items = int(options.get("max_items", 50) or 50)
    item.pop("content", None)
    item["data"] = {
        "records": [_flatten_json(r) for r in records[:max_items]],
        "count": min(len(records), max_items),
        "total_in_response": len(records),
    }
    return item


# ── invoice extractor (PDF/text invoices -> accounting fields) ───────────────

_INVOICE_TOTAL_RE = re.compile(
    r"(?:grand\s+total|total\s+due|amount\s+due|invoice\s+total|balance\s+due|total)\s*[:\-]?\s*"
    r"(?P<cur>[A-Z]{3}|[$€£¥])?\s*(?P<amt>[\d.,]+)",
    re.I,
)
_INVOICE_DATE_RE = re.compile(
    r"(?:invoice\s+date|date(?:d)?|issue\s+date)\s*[:\-]?\s*"
    r"(?P<d>\d{1,4}[./-]\d{1,2}[./-]\d{1,4})",
    re.I,
)
_INVOICE_NUMBER_RE = re.compile(r"invoice\s*(?:number|no\.?|#)\s*[:\-]?\s*([A-Z0-9-]{3,30})", re.I)


def process_invoice(
    url: str, result: dict[str, Any], options: dict[str, Any], state: dict[str, Any]
) -> dict[str, Any]:
    """Extract accounting fields (vendor, number, dates, totals) from
    invoice documents parsed to text by the engine's PDF tier."""
    item = _base_item(url, result)
    if item["status"] != "ok":
        return item
    text = item["content"] or ""
    total_m = None
    for m in _INVOICE_TOTAL_RE.finditer(text):
        total_m = m  # last match wins: grand total usually printed last
    date_m = _INVOICE_DATE_RE.search(text)
    number_m = _INVOICE_NUMBER_RE.search(text)
    if not any([total_m, date_m, number_m]):
        item["status"] = "skipped"
        item["error"] = "no invoice fields detected in document text"
        item.pop("content", None)
        return item
    item.pop("content", None)
    item["invoice"] = {
        "number": number_m.group(1) if number_m else "",
        "date": date_m.group("d") if date_m else "",
        "total": total_m.group("amt") if total_m else "",
        "currency": (total_m.group("cur") if total_m else "") or "",
        "vendor_hint": (text.split("\n")[0][:80] if text else "").strip(),
    }
    return item


PROCESSORS: dict[str, ProcessorFn] = {
    "corpus": process_corpus,
    "backlinks": process_backlinks,
    "seo": process_seo,
    "leads": process_leads,
    "news": process_news,
    "price": process_price,
    "tech": process_tech,
    "jsondata": process_jsondata,
    "invoice": process_invoice,
    "audit": process_audit,
    "monitor": process_monitor,
    "extract": process_extract,
}


def get_processor(name: str | None) -> ProcessorFn | None:
    return PROCESSORS.get(name or "")
