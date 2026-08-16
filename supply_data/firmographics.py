"""B2B company firmographics — job-board hiring signal + website signals.

Builds a firmographics record for a company from public, no-auth sources,
plus an optional Crunchbase-adjacent partner API for funding/headcount:

* **Website** — probes ``https://{slug}.com|.io|.co|.ai`` (no auth, real
  DNS/HTTP reachability). Override with ``PRY_FIRMO_WEBSITE``.
* **Tech stack** — fetches the website HTML and matches known signatures
  (WordPress, Shopify, Next.js, React, Vue, Cloudflare, HubSpot, Stripe,
  Google Analytics, …). If the page looks like an anti-bot challenge it is
  flagged honestly (``firmographics_anti_bot``) and tech_stack degrades to
  ``[]``.
* **LinkedIn URL** — extracts ``linkedin.com/company/...`` hrefs from the
  website footer.
* **Industry** — keyword match over the site title / meta description.
* **Hiring openings** — counts live postings on the company's public job
  boards: Greenhouse, Lever, Ashby (all free, no auth). ``0`` when no
  board is found (lead-gen interpretation: no open roles detected).
* **Headcount / funding / total_funding** — Crunchbase-adjacent partner
  API when configured (``PRY_FIRMO_API_URL`` + ``PRY_FIRMO_API_KEY``).
  Crunchbase's own public API is paid/deprecated and free adjacent sources
  have no clean API, so without a key these fields stay ``None`` and the
  gap is logged honestly (``firmographics_partner_not_configured``).

Contract
--------
* :func:`get_company_firmographics` — async, never raises, returns a
  ``dict`` with all nine keys (values degrade independently).

Result shape
------------
    {
        "name": "Acme Trading Co",
        "headcount": 1200,
        "funding": 40000000,
        "total_funding": 120000000,
        "tech_stack": ["WordPress", "Stripe", "Google Analytics"],
        "industry": "Logistics & Supply Chain",
        "hiring_openings": 14,
        "linkedin_url": "https://www.linkedin.com/company/acme-trading-co",
        "website": "https://acmetrading.com",
    }

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import logging
import os
import re
from typing import Any

import httpx

from retry import RetryConfig, async_retry

logger = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(15.0)
_RETRY_CONFIG = RetryConfig(
    max_retries=2,
    base_delay=0.4,
    max_delay=1.6,
    retryable_exceptions=(httpx.HTTPError,),
)
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; pryscraper-firmo/1.0; "
        "+https://git.rugmunch.io/RugMunchMedia/pryscraper)"
    ),
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
}
_WEBSITE_ENV = "PRY_FIRMO_WEBSITE"
# Crunchbase-adjacent partner API (funding + headcount). Crunchbase's own
# public API is paid/deprecated; free adjacent sources have no clean API.
_FIRMO_API_URL = os.environ.get("PRY_FIRMO_API_URL", "https://firmo.example.com/v1/companies")
_FIRMO_API_KEY_ENV = "PRY_FIRMO_API_KEY"

# Candidate domains probed in order; first reachable wins (no auth).
_WEBSITE_CANDIDATES = ("{slug}.com", "{slug}.io", "{slug}.co", "{slug}.ai")
# Public no-auth job boards, tried in order.
_JOB_BOARDS: tuple[tuple[str, str], ...] = (
    ("greenhouse", "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"),
    ("lever", "https://api.lever.co/v0/postings/{slug}?mode=json"),
    ("ashby", "https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=false"),
)

_ANTI_BOT_MARKERS = (
    "cf-challenge",
    "checking your browser",
    "attention required",
    "unusual traffic",
    "access denied",
    "captcha",
)

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


def _empty_firmographics(company: str) -> dict[str, Any]:
    """Canonical empty record — every key present, values None/0/[]."""
    return {
        "name": company,
        "headcount": None,
        "funding": None,
        "total_funding": None,
        "tech_stack": [],
        "industry": None,
        "hiring_openings": 0,
        "linkedin_url": None,
        "website": None,
    }


def _normalize_slug(company: str) -> str:
    """Company name -> domain/job-board slug (letters, digits, dashes)."""
    slug = re.sub(r"[^a-z0-9]+", "-", company.lower()).strip("-")
    return slug or "company"


def _as_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _as_money(value: Any) -> int | None:
    """Coerce a JSON money value (number or "$12M" string) to int USD."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip()
    if not text:
        return None
    multiplier = 1
    upper = text.upper()
    if upper.endswith("B"):
        multiplier, upper = 1_000_000_000, upper[:-1]
    elif upper.endswith("M"):
        multiplier, upper = 1_000_000, upper[:-1]
    elif upper.endswith("K"):
        multiplier, upper = 1_000, upper[:-1]
    digits = re.sub(r"[^0-9.]", "", upper)
    if not digits:
        return None
    try:
        return int(float(digits) * multiplier)
    except ValueError:
        return None


# ── Website discovery + HTML signals ──────────────────────────────────


async def _fetch_once(url: str) -> httpx.Response:
    async with httpx.AsyncClient(
        timeout=_TIMEOUT, headers=_HEADERS, follow_redirects=True
    ) as client:
        return await client.get(url)


async def _find_website(slug: str) -> str | None:
    """Return the first reachable website URL for a company slug, or None.

    ``PRY_FIRMO_WEBSITE`` short-circuits probing (production accuracy +
    tests). Never raises.
    """
    override = os.environ.get(_WEBSITE_ENV, "").strip()
    if override:
        return override if override.startswith(("http://", "https://")) else f"https://{override}"
    for candidate in _WEBSITE_CANDIDATES:
        url = f"https://{candidate.format(slug=slug)}"
        try:
            response = await _fetch_once(url)
            if 200 <= response.status_code < 400:
                return str(response.url)
        except (httpx.HTTPError, OSError):
            continue
    return None


async def _fetch_html(url: str) -> str | None:
    """Fetch website HTML text, or None on any failure."""
    try:
        response = await async_retry(lambda: _fetch_once(url), config=_RETRY_CONFIG)
        if 200 <= response.status_code < 400:
            return response.text
    except (httpx.HTTPError, OSError):
        return None
    return None


def _is_anti_bot_page(html: str) -> bool:
    lowered = html.lower()
    return any(marker in lowered for marker in _ANTI_BOT_MARKERS)


def _detect_tech_stack(html: str) -> list[str]:
    """Match website HTML against known tech signatures (heuristic)."""
    lowered = html.lower()
    detected: list[str] = []
    for tech, signatures in _TECH_SIGNATURES.items():
        if any(sig in lowered for sig in signatures):
            detected.append(tech)
    return detected


def _extract_linkedin(html: str) -> str | None:
    """Return the first linkedin.com/company|school URL found in HTML."""
    match = _LINKEDIN_RE.search(html)
    if not match:
        return None
    url = match.group(1)
    return url if url.startswith("http") else f"https:{url}"


def _detect_industry(html: str) -> str | None:
    """Keyword-match the site title/meta description onto an industry."""
    haystack = html.lower()
    # Cheap extraction of the most informative text regions.
    title_match = re.search(r"<title[^>]*>(.*?)</title>", haystack, re.DOTALL)
    desc_match = re.search(
        r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)["\']',
        haystack,
    )
    chunks = [
        title_match.group(1) if title_match else "",
        desc_match.group(1) if desc_match else "",
    ]
    haystack = " ".join(chunks).lower()
    for industry, keywords in _INDUSTRY_KEYWORDS.items():
        if any(keyword in haystack for keyword in keywords):
            return industry
    return None


# ── Job-board hiring signal ───────────────────────────────────────────


async def _board_jobs(client: httpx.AsyncClient, url: str) -> list[dict[str, Any]]:
    """Fetch one job board's postings; return the raw job list or []."""
    try:
        response = await client.get(url)
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError):
        return []
    if isinstance(payload, list):
        return [j for j in payload if isinstance(j, dict)]
    if isinstance(payload, dict):
        for key in ("jobs", "postings", "data"):
            value = payload.get(key)
            if isinstance(value, list):
                return [j for j in value if isinstance(j, dict)]
    return []


async def _count_hiring_openings(slug: str) -> int:
    """Count live postings on the company's first found public job board.

    Boards are tried in order (Greenhouse -> Lever -> Ashby); the first one
    that returns postings wins (a lower-bound hiring signal without
    hammering every free board).
    """
    total = 0
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, headers=_HEADERS) as client:
            for board, template in _JOB_BOARDS:
                jobs = await _board_jobs(client, template.format(slug=slug))
                if jobs:
                    total += len(jobs)
                    logger.info(
                        "firmographics_job_board_hit",
                        extra={"board": board, "openings": len(jobs)},
                    )
                    break
    except (httpx.HTTPError, OSError):
        return 0
    return total


# ── Crunchbase-adjacent partner API (optional) ────────────────────────


async def _partner_firmographics(company: str) -> dict[str, Any]:
    """Fetch headcount/funding from the optional partner API.

    Returns a dict with ``headcount``, ``funding``, ``total_funding`` keys;
    all None when not configured or on failure. Never raises.
    """
    empty = {"headcount": None, "funding": None, "total_funding": None}
    key = os.environ.get(_FIRMO_API_KEY_ENV, "").strip()
    if not key:
        logger.warning(
            "firmographics_partner_not_configured",
            extra={
                "company": company,
                "hint": "set PRY_FIRMO_API_URL + PRY_FIRMO_API_KEY for funding/headcount",
            },
        )
        return empty

    async def _one() -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=_TIMEOUT, headers=_HEADERS) as client:
            response = await client.get(_FIRMO_API_URL, params={"api_key": key, "company": company})
            response.raise_for_status()
            payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("partner firmographics payload is not an object")
        data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        if not isinstance(data, dict):
            raise ValueError("partner firmographics missing data object")
        return {
            "headcount": _as_int_any(data.get("headcount") or data.get("num_employees")),
            "funding": _as_money(data.get("funding") or data.get("last_funding")),
            "total_funding": _as_money(
                data.get("total_funding") or data.get("totalFunding") or data.get("raised")
            ),
        }

    try:
        return await async_retry(_one, config=_RETRY_CONFIG)
    except (httpx.HTTPError, OSError, ValueError):
        return empty


def _as_int_any(value: Any) -> int | None:
    """Coerce a JSON value to int/None (numbers and numeric strings)."""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


# ── Public API ─────────────────────────────────────────────────────────
async def get_company_firmographics(company: str) -> dict[str, Any]:
    """Return B2B firmographics for a company (see module docstring).

    Args:
        company: Company name (e.g. ``"Acme Trading Co"``).

    Returns:
        A dict with all nine keys: name, headcount, funding, total_funding,
        tech_stack, industry, hiring_openings, linkedin_url, website. Each
        field degrades to ``None`` / ``0`` / ``[]`` independently; the call
        itself never raises.
    """
    try:
        return await _get_company_firmographics(company)
    except Exception:
        logger.exception("supply_firmographics_crashed", extra={"company": company})
        return _empty_firmographics(company)


async def _get_company_firmographics(company: str) -> dict[str, Any]:
    name = company.strip()
    record = _empty_firmographics(name)
    if not name:
        return record
    slug = _normalize_slug(name)

    website = await _find_website(slug)
    record["website"] = website

    html = await _fetch_html(website) if website else None
    if html and _is_anti_bot_page(html):
        logger.warning(
            "firmographics_anti_bot",
            extra={"company": name, "website": website},
        )
        # HTML signals are unreliable behind a challenge; degrade to
        # nothing rather than emit garbage.
        html = None
    if html:
        record["tech_stack"] = _detect_tech_stack(html)
        record["linkedin_url"] = _extract_linkedin(html)
        record["industry"] = _detect_industry(html)

    record["hiring_openings"] = await _count_hiring_openings(slug)
    partner = await _partner_firmographics(name)
    record.update(partner)
    return record
