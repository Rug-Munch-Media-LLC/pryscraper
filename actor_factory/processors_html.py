"""Pry - Apify Actor Factory: HTML analysis processors.

Regex/HTML-signature processors: SEO auditing, generic page audits
(accessibility / GDPR / social cards / ad intel), lead extraction, news
link harvesting, backlink intel, and technology stack detection.

Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urljoin

from actor_factory.processors_common import _base_item, _raw_html

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


# ── lead extraction ──────────────────────────────────────────────────────────

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


# ── backlink harvester ───────────────────────────────────────────────────────


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
