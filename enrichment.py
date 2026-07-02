import httpx
"""Pry — Data Enrichment Pipeline.
Enrich scraped data with company info, social profiles, tech stack detection."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


# ── Tech Stack Detection ──

TECH_PATTERNS: dict[str, list[str]] = {
    "wordpress": [r"wp-content", r"wp-includes", r"/wp-json/", r"wordpress"],
    "shopify": [r"shopify\.com", r"myshopify\.com", r"Shopify", r"cdn\.shopify"],
    "woocommerce": [r"woocommerce", r"wc-", r"add-to-cart"],
    "wix": [r"wix\.com", r"Wix\.com", r"wixstatic\.com"],
    "squarespace": [r"squarespace\.com", r"Squarespace"],
    "webflow": [r"webflow\.com", r"Webflow"],
    "magento": [r"magento", r"Magento", r"mage\-"],
    "laravel": [r"laravel", r"Laravel"],
    "django": [r"django", r"Django", r"csrfmiddlewaretoken", r"csrftoken"],
    "rails": [r"rails", r"Ruby on Rails", r"_rails"],
    "nextjs": [r"_next/static", r"__next_data__", r"next\.js"],
    "nuxt": [r"__NUXT__", r"nuxt"],
    "gatsby": [r"gatsby", r"Gatsby"],
    "react": [r"react\.js", r"react-dom", r"React", r"create-react-app"],
    "vue": [r"vue\.js", r"Vue", r"vue-router"],
    "angular": [r"angular\.js", r"Angular", r"ng-"],
    "cloudflare": [r"cloudflare", r"cf-ray", r"__cfduid"],
    "fastly": [r"fastly", r"Fastly"],
    "cloudfront": [r"cloudfront\.net", r"CloudFront"],
    "google_analytics": [r"google-analytics\.com", r"gtag", r"ga\.js"],
    "facebook_pixel": [r"facebook\.com/tr", r"fbq\("],
    "hotjar": [r"hotjar", r"Hotjar"],
    "intercom": [r"intercom\.io", r"Intercom"],
    "hubspot": [r"hubspot\.com", r"HubSpot", r"hs-scripts"],
    "stripe": [r"stripe\.com", r"Stripe", r"pk_live"],
    "paypal": [r"paypal\.com", r"PayPal"],
}


def detect_tech_stack(html: str, headers: dict[str, str] | None = None) -> dict[str, Any]:
    """Detect technologies used on a website from HTML and headers."""
    detected: dict[str, bool] = {}
    lower_html = html.lower()

    for tech, patterns in TECH_PATTERNS.items():
        for p in patterns:
            if re.search(p, lower_html) or (
                headers and any(re.search(p, str(v).lower()) for v in headers.values())
            ):
                detected[tech] = True
                break

    # Categorize
    categories: dict[str, list[str]] = {
        "cms": [
            t
            for t in [
                "wordpress",
                "shopify",
                "woocommerce",
                "wix",
                "squarespace",
                "webflow",
                "magento",
            ]
            if detected.get(t)
        ],
        "framework": [
            t for t in ["laravel", "django", "rails", "nextjs", "nuxt", "gatsby"] if detected.get(t)
        ],
        "frontend": [t for t in ["react", "vue", "angular"] if detected.get(t)],
        "hosting_cdn": [t for t in ["cloudflare", "fastly", "cloudfront"] if detected.get(t)],
        "analytics": [
            t
            for t in ["google_analytics", "facebook_pixel", "hotjar", "intercom", "hubspot"]
            if detected.get(t)
        ],
        "payments": [t for t in ["stripe", "paypal"] if detected.get(t)],
    }

    return {
        "detected": list(detected.keys()),
        "count": len(detected),
        "categories": categories,
    }


# ── Social Profile Extraction ──

SOCIAL_PATTERNS: dict[str, str] = {
    "twitter": r"(?:twitter\.com|x\.com)/([A-Za-z0-9_]{1,30})/?",
    "linkedin": r"linkedin\.com/(?:company|in)/([A-Za-z0-9\-]+)/?",
    "facebook": r"facebook\.com/([A-Za-z0-9\.\-]+)/?",
    "instagram": r"instagram\.com/([A-Za-z0-9_\.]+)/?",
    "youtube": r"youtube\.com/@?([A-Za-z0-9_\-]+)/?",
    "github": r"github\.com/([A-Za-z0-9\-]+)/?",
    "crunchbase": r"crunchbase\.com/(?:organization|person)/([A-Za-z0-9\-]+)/?",
    "angellist": r"angel\.co/([A-Za-z0-9\-]+)/?",
    "producthunt": r"producthunt\.com/@?([A-Za-z0-9_\-]+)/?",
}


def extract_social_profiles(html: str, url: str = "") -> dict[str, Any]:
    """Extract social media profile links from HTML."""
    profiles: dict[str, list[str]] = {}
    lower_html = html.lower()

    for platform, pattern in SOCIAL_PATTERNS.items():
        matches = re.findall(pattern, lower_html)
        if matches:
            profiles[platform] = list(set(matches[:3]))

    # Also check URL itself
    if url:
        lower_url = url.lower()
        for platform, pattern in SOCIAL_PATTERNS.items():
            if platform not in profiles:
                m = re.search(pattern, lower_url)
                if m:
                    profiles[platform] = [m.group(1)]

    return {
        "profiles": profiles,
        "platforms_found": list(profiles.keys()),
        "total": sum(len(v) for v in profiles.values()),
    }


# ── Company Info Extraction ──


def extract_company_info(html: str) -> dict[str, Any]:
    """Extract company information from website content."""
    lower = html.lower()
    info: dict[str, Any] = {}

    # Extract email
    emails = re.findall(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b", html)
    info["emails"] = list({e for e in emails if not e.endswith(".png") and not e.endswith(".jpg")})[
        :5
    ]

    # Extract phone
    phones = re.findall(r"[\+\(]?\d{1,3}[\)\s.-]?\d{3,4}[\s.-]?\d{4}", html)
    info["phones"] = list(set(phones))[:3]

    # Extract address
    address_patterns = [
        r"\d{1,5}\s+[A-Za-z0-9\s,]+(?:Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Drive|Dr|Lane|Ln|Way)[,\s]+[A-Za-z\s]+,\s*[A-Z]{2}\s*\d{5}",
        r"\d{1,5}\s+[A-Za-z0-9\s,]+(?:Street|St|Avenue|Ave|Road|Rd)[,\s]+[A-Za-z\s]+,[,\s]*[A-Z]{2}",
    ]
    addresses = []
    for pat in address_patterns:
        matches = re.findall(pat, html)
        addresses.extend(matches[:2])
    info["addresses"] = addresses

    # Extract founded year
    years = re.findall(
        r"(?:founded|established|since|incorporated)\s*(?:\w+\s+)?(?::)?\s*(\d{4})", lower
    )
    info["founded_year"] = years[0] if years else None

    # Extract team size
    team = re.findall(r"(\d+[\+]?)\s*(?:employees|team members|people)", lower)
    info["team_size"] = team[0] if team else None

    return info


# ── Full Enrichment Pipeline ──


async def enrich_url(
    url: str, html: str = "", headers: dict[str, str] | None = None
) -> dict[str, Any]:
    """Run full enrichment pipeline on a URL/content.

    Returns: tech stack, social profiles, company info, domain age, security.
    """
    from client import get_client

    if not html:
        try:
            client = await get_client()
            resp = await client.get(url, timeout=20, follow_redirects=True)
            if resp.is_success:
                html = resp.text
                headers = dict(resp.headers)
        except (httpx.HTTPError, httpx.RequestError) as e:
            logger.warning("enrichment_fetch_failed", extra={"url": url, "error": str(e)})

    result: dict[str, Any] = {
        "url": url,
        "tech_stack": detect_tech_stack(html, headers)
        if html
        else {"detected": [], "count": 0, "categories": {}},
        "social_profiles": extract_social_profiles(html, url)
        if html
        else {"profiles": {}, "platforms_found": [], "total": 0},
        "company_info": extract_company_info(html) if html else {},
    }
    return result
