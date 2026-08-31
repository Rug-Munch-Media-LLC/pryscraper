# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Post-deploy publication metadata: store category + PPE pricing payload.

``apify push`` ships source code but cannot set Store-facing metadata.
Going public requires ``PUT /v2/acts/:actorId`` with **categories** (the
platform rejects ``isPublic: true`` without them - root cause of the
silent "meta put failed" sweep of 2026-08-26), and monetization requires
a ``pricingInfos`` PAY_PER_EVENT record built from the preset's
:class:`~actor_factory.spec.PricingEvent` tuple.

Account-level prerequisites that have NO API (one-time Console actions):
accepting the Apify Store Publishing Terms and setting payout billing
info. Until both are done the platform answers ``403
store-terms-not-accepted`` / ``400 cannot-monetize-without-payout-billing-info``
regardless of payload correctness - :func:`publish_metadata` surfaces
those verbatim instead of masking them.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from actor_factory.spec import ActorSpec

API_BASE = "https://api.apify.com/v2"

# Verified against PUT /v2/acts schema-validation on 2026-08-26
# (invalid values answer 400 "...is not an allowed value").
APIFY_VALID_CATEGORIES: frozenset[str] = frozenset(
    {
        "AI",
        "AUTOMATION",
        "BUSINESS",
        "ECOMMERCE",
        "EDUCATION",
        "JOBS",
        "LEAD_GENERATION",
        "MARKETING",
        "NEWS",
        "OPEN_SOURCE",
        "REAL_ESTATE",
        "SEO_TOOLS",
        "SOCIAL_MEDIA",
        "SPORTS",
        "TRAVEL",
        "VIDEOS",
        "OTHER",
        "DEVELOPER_TOOLS",
    }
)

# Explicit store category per preset. Kept as a total mapping (validated by
# tests) so every actor lands in a deliberate shelf instead of whatever a
# keyword heuristic guesses that week.
PRESET_CATEGORY_MAP: dict[str, str] = {
    # Scraping primitives
    "pry-universal-scraper": "AUTOMATION",
    "pry-site-crawler": "AUTOMATION",
    "pry-screenshot-capture": "AUTOMATION",
    "pry-document-parser": "AUTOMATION",
    "pry-tech-stack-detector": "DEVELOPER_TOOLS",
    "pry-json-api-monitor": "DEVELOPER_TOOLS",
    "pry-api-docs-diff": "DEVELOPER_TOOLS",
    "pry-changelog-tracker": "DEVELOPER_TOOLS",
    "pry-github-release-monitor": "DEVELOPER_TOOLS",
    "pry-npm-package-stats": "DEVELOPER_TOOLS",
    "pry-pypi-package-stats": "DEVELOPER_TOOLS",
    "pry-llm-corpus-builder": "AI",
    # SEO / site health
    "pry-seo-site-auditor": "SEO_TOOLS",
    "pry-serp-scraper": "SEO_TOOLS",
    "pry-serp-rank-tracker": "SEO_TOOLS",
    "pry-sitemap-diff": "SEO_TOOLS",
    "pry-broken-links-auditor": "SEO_TOOLS",
    "pry-social-card-auditor": "SEO_TOOLS",
    "pry-gdpr-cookie-checker": "SEO_TOOLS",
    "pry-accessibility-scanner": "SEO_TOOLS",
    "pry-local-business-schema-auditor": "SEO_TOOLS",
    # Lead gen / sales
    "pry-lead-harvester": "LEAD_GENERATION",
    "pry-maps-lead-extractor": "LEAD_GENERATION",
    "pry-contact-form-finder": "LEAD_GENERATION",
    "pry-provider-finder": "LEAD_GENERATION",
    "pry-scholarship-grants-finder": "EDUCATION",
    "pry-startup-funding-monitor": "BUSINESS",
    "pry-ad-intel-monitor": "MARKETING",
    "pry-press-release-monitor": "MARKETING",
    "pry-newsletter-archive-miner": "MARKETING",
    "pry-deal-radar": "ECOMMERCE",
    # E-commerce
    "pry-product-data-extractor": "ECOMMERCE",
    "pry-ecommerce-catalog-crawler": "ECOMMERCE",
    "pry-inventory-alert": "ECOMMERCE",
    "pry-price-watcher": "ECOMMERCE",
    "pry-review-aggregator": "ECOMMERCE",
    # Travel
    "pry-hotel-rate-watch": "TRAVEL",
    "pry-flight-price-watch": "TRAVEL",
    "pry-event-listings-aggregator": "TRAVEL",
    # Real estate
    "pry-property-lister": "REAL_ESTATE",
    "pry-local-directory-extractor": "REAL_ESTATE",
    # Jobs / HR
    "pry-jobs-aggregator": "JOBS",
    "pry-course-catalog-extractor": "EDUCATION",
    "pry-research-paper-watch": "EDUCATION",
    "pry-arxiv-paper-monitor": "EDUCATION",
    # News & media monitoring
    "pry-news-feed-monitor": "NEWS",
    "pry-rss-feed-monitor": "NEWS",
    "pry-blog-post-extractor": "NEWS",
    "pry-hacker-news-monitor": "NEWS",
    "pry-producthunt-launch-monitor": "NEWS",
    "pry-forum-discussion-miner": "SOCIAL_MEDIA",
    "pry-app-store-review-miner": "SOCIAL_MEDIA",
    "pry-podcast-review-miner": "SOCIAL_MEDIA",
    "pry-podcast-feed-miner": "VIDEOS",
    "pry-youtube-rss-monitor": "VIDEOS",
    "pry-knowledge-base-miner": "BUSINESS",
    # Change / compliance watching
    "pry-change-monitor": "AUTOMATION",
    "pry-wayback-diff": "AUTOMATION",
    "pry-cve-advisory-watch": "BUSINESS",
    "pry-terms-policy-watch": "BUSINESS",
    "pry-court-docket-monitor": "BUSINESS",
    "pry-sec-filings-watch": "BUSINESS",
    "pry-usaspending-contracts": "BUSINESS",
    "pry-tender-procurement-monitor": "BUSINESS",
    "pry-sanctions-screener": "BUSINESS",
    "pry-fda-recall-monitor": "BUSINESS",
    "pry-clinical-trials-watch": "BUSINESS",
    "pry-uspto-patent-monitor": "BUSINESS",
    "pry-rdap-domain-watch": "DEVELOPER_TOOLS",
    "pry-ssl-cert-monitor": "DEVELOPER_TOOLS",
    "pry-onion-site-monitor": "DEVELOPER_TOOLS",
    # Crypto / web3
    "pry-token-safety-scanner": "AI",
    "pry-token-unlock-monitor": "BUSINESS",
    "pry-whale-transfer-monitor": "BUSINESS",
    "pry-chain-tvl-monitor": "BUSINESS",
    "pry-defi-yield-monitor": "BUSINESS",
    "pry-stablecoin-flow-monitor": "BUSINESS",
    "pry-gas-fee-monitor": "BUSINESS",
    "pry-crypto-listing-monitor": "BUSINESS",
    "pry-crypto-market-monitor": "BUSINESS",
    "pry-prediction-market-monitor": "BUSINESS",
    # Data feeds / environment
    "pry-weather-data-collector": "OTHER",
    "pry-air-quality-monitor": "OTHER",
    "pry-earthquake-alert-monitor": "OTHER",
    "pry-space-launch-monitor": "OTHER",
    "pry-electricity-price-watch": "BUSINESS",
    "pry-fx-rate-monitor": "BUSINESS",
    "pry-status-page-aggregator": "OTHER",
    "pry-sports-odds-best-line": "SPORTS",
    "pry-steam-game-stats": "OTHER",
    "pry-recipe-miner": "OTHER",
    "pry-restaurant-menu-extractor": "OTHER",
    "pry-pdf-invoice-extractor": "BUSINESS",
    "pry-outbound-link-harvester": "SEO_TOOLS",
    # batch 22: vertical-market watch actors (MARKET_RESEARCH.md gaps)
    "pry-app-store-rank-watch": "OTHER",
    "pry-appexchange-marketplace-watch": "BUSINESS",
    "pry-ai-model-pricing-watch": "DEVELOPER_TOOLS",
    "pry-gpu-cloud-price-watch": "DEVELOPER_TOOLS",
    "pry-chargepoint-ev-station-watch": "BUSINESS",
    "pry-insurance-rate-compare": "BUSINESS",
    "pry-telecom-plan-monitor": "BUSINESS",
    "pry-utility-tariff-watch": "BUSINESS",
    "pry-pharma-pipeline-watch": "BUSINESS",
    "pry-esg-scorecard-extractor": "BUSINESS",
    "pry-restaurant-availability-watch": "OTHER",
    "pry-ticket-resale-price-watch": "OTHER",
    "pry-shipment-carrier-rate-watch": "BUSINESS",
    "pry-ngo-grant-deadline-watch": "BUSINESS",
    "pry-supplier-risk-signal-watch": "BUSINESS",
}


def category_for(preset_name: str) -> str:
    """Store category for a preset; raises KeyError for unknown presets."""
    return PRESET_CATEGORY_MAP[preset_name]


def build_pricing_infos(spec: ActorSpec) -> dict[str, Any]:
    """PAY_PER_EVENT ``pricingInfos`` entry from a preset's pricing events.

    Shape follows PayPerEventActorPricingInfo (docs.apify.com/api/v2/act-put):
    one flat-priced charge event per :class:`PricingEvent`, first event
    marked primary. ``apifyMarginPercentage`` mirrors the platform default
    (0.2) so the record validates before Apify stamps its own value.
    """
    if not spec.pricing_events:
        msg = f"{spec.name}: preset defines no pricing events"
        raise ValueError(msg)
    events: dict[str, dict[str, Any]] = {}
    for idx, event in enumerate(spec.pricing_events):
        events[event.name] = {
            "eventTitle": event.title,
            "eventDescription": event.description,
            "eventPriceUsd": event.price_usd,
            "isPrimaryEvent": idx == 0,
        }
    return {
        "pricingModel": "PAY_PER_EVENT",
        "apifyMarginPercentage": 0.2,
        "pricingPerEvent": {"actorChargeEvents": events},
    }


def build_publication_payload(spec: ActorSpec) -> dict[str, Any]:
    """Full metadata PUT body: public + categorized + priced."""
    return {
        "title": spec.title,
        "description": spec.description,
        "isPublic": True,
        "categories": [category_for(spec.name)],
        "pricingInfos": [build_pricing_infos(spec)],
    }


def _request(
    path: str, method: str, token: str, payload: dict[str, Any] | None = None
) -> tuple[int, dict[str, Any] | str]:
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(  # noqa: S310 - fixed https base URL
        f"{API_BASE}{path}",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method=method,
        data=data,
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310
            body = resp.read().decode("utf-8", "replace")
            return resp.status, json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")


def publish_metadata(
    spec: ActorSpec,
    token: str,
    *,
    org: str = "rugmunchmedia",
) -> tuple[bool, str]:
    """Apply publication metadata for one preset via PUT /v2/acts/:id.

    Returns ``(ok, detail)``. Account-level blockers (store terms not yet
    accepted, payout billing info missing) are reported verbatim so the
    operator knows exactly which Console step remains.
    """
    actor_id = f"{org}~{spec.name.removeprefix('pry-')}"
    status, body = _request(f"/acts/{actor_id}", "PUT", token, build_publication_payload(spec))
    if status == 200:
        data = body.get("data", {}) if isinstance(body, dict) else {}
        return True, f"public={data.get('isPublic')} cats={data.get('categories')}"
    detail = body if isinstance(body, str) else json.dumps(body)
    return False, f"HTTP {status}: {detail[:300]}"
