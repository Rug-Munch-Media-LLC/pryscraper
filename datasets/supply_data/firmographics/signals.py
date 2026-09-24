"""Website HTML signal extraction for firmographics enrichment."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

import re

_TECH_SIGNATURES: dict[str, tuple[str, ...]] = {
    "WordPress": ("wp-content", "wp-includes", 'generator" content="wordpress'),
    "Shopify": ("cdn.shopify.com", "shopify.theme", "shopify.built"),
    "WooCommerce": ("woocommerce",),
    "Wix": ("wixstatic.com", "wix.com"),
    "Squarespace": ("static.squarespace.com", "squarespace"),
    "Next.js": ("__next_data__", "_next/static"),
    "Nuxt": ("__nuxt__", "_nuxt/"),
    "React": ("data-reactroot", "react-dom"),
    "Vue.js": ("vue.runtime", "data-v-"),
    "Tailwind CSS": ("tailwindcss",),
    "Django": ("csrfmiddlewaretoken", "django"),
    "Laravel": ("laravel_session", "laravel"),
    "Ruby on Rails": ('csrf-param"', "rails"),
    "Cloudflare": ("cloudflare", "cf-ray", "__cf_bm"),
    "Google Analytics": ("google-analytics.com", "gtag("),
    "Google Tag Manager": ("googletagmanager.com", "gtm.js"),
    "HubSpot": ("hs-scripts", "hsforms", "hubspot"),
    "Intercom": ("intercomsettings", "widget.intercom"),
    "Zendesk": ("zendesk", "widget.zopim"),
    "Stripe": ("js.stripe.com", "stripe"),
    "Segment": ("cdn.segment.com",),
    "Mixpanel": ("cdn.mxpnl.com", "mixpanel"),
    "Amplitude": ("cdn.amplitude.com", "amplitude"),
    "Mailchimp": ("mc-embedded-subscribe", "mailchimp"),
    "SendGrid": ("sendgrid",),
}

_INDUSTRY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "Logistics & Supply Chain": (
        "logistics",
        "freight",
        "shipping",
        "supply chain",
        "warehouse",
        "3pl",
        "freight forwarding",
        "customs",
    ),
    "Manufacturing": ("manufactur", "factory", "industrial", "machining", "precision parts"),
    "Retail & E-commerce": ("retail", "e-commerce", "ecommerce", "online store"),
    "Software / SaaS": ("software", "saas", "cloud", "api", "developer platform"),
    "Healthcare": ("healthcare", "medical", "pharma", "clinic"),
    "Financial Services": ("financial", "bank", "insurance", "fintech", "payments"),
    "Energy": ("energy", "solar", "renewable", "oil", "gas"),
    "Construction": ("construction", "contractor", "infrastructure", "building"),
    "Food & Beverage": ("food", "beverage", "snack", "coffee", "brewery"),
    "Automotive": ("automotive", "auto parts", "electric vehicle", "vehicle"),
    "Electronics": ("electronics", "semiconductor", "pcb", "circuit", "component"),
    "Textiles & Apparel": ("textile", "apparel", "garment", "fashion", "clothing"),
    "Chemicals": ("chemical", "polymer", "plastic", "resin"),
}

_LINKEDIN_RE = re.compile(
    r"""href=["']((?:https?:)?//(?:www\.|[a-z]{2,3}\.)?linkedin\.com/(?:company|school)/[^"'#?]+)""",
    re.IGNORECASE,
)


def _detect_tech_stack(html: str) -> list[str]:
    lowered = html.lower()
    return [
        tech
        for tech, signatures in _TECH_SIGNATURES.items()
        if any(signature in lowered for signature in signatures)
    ]


def _extract_linkedin(html: str) -> str | None:
    match = _LINKEDIN_RE.search(html)
    if not match:
        return None
    url = match.group(1)
    return url if url.startswith("http") else f"https:{url}"


def _detect_industry(html: str) -> str | None:
    haystack = html.lower()
    title_match = re.search(r"<title[^>]*>(.*?)</title>", haystack, re.DOTALL)
    desc_match = re.search(
        r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)["\']',
        haystack,
    )
    chunks = [
        title_match.group(1) if title_match else "",
        desc_match.group(1) if desc_match else "",
    ]
    description = " ".join(chunks).lower()
    for industry, keywords in _INDUSTRY_KEYWORDS.items():
        if any(keyword in description for keyword in keywords):
            return industry
    return None
