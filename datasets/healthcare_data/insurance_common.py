"""Shared constants + parsing helpers for insurance quote/rate scraping.

Split out of ``insurance.py`` (god-file reduction). The ``insurance.py``
facade re-exports everything here so the surface is unchanged.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import json
import re

import httpx

from pry.engine.retry import RetryConfig

_COVERAGE_TYPES = {"auto", "home"}

# Public quote-form entry points per coverage type. All are captcha/JS-gated
# in practice; we probe them to prove it rather than assume.
_PROVIDERS: dict[str, tuple[tuple[str, str], ...]] = {
    "auto": (
        ("progressive", "https://www.progressive.com/auto/"),
        ("geico", "https://www.geico.com/quote/auto/"),
        ("statefarm", "https://www.statefarm.com/insurance/auto/start"),
    ),
    "home": (
        ("lemonade", "https://www.lemonade.com/homeowners/"),
        ("progressive", "https://www.progressive.com/homeowners/"),
        ("travelers", "https://www.travelers.com/quote/homeowners"),
    ),
}

_RATE_PAGES: dict[str, str] = {
    "auto": "https://www.iii.org/fact-statistic/facts-statistics-auto-insurance",
    "home": "https://www.iii.org/fact-statistic/facts-statistics-homeowners-and-renters-insurance",
}

_PROBE_TIMEOUT = httpx.Timeout(10.0)
_TIMEOUT = httpx.Timeout(20.0)
_PROBE_RETRY = RetryConfig(
    max_retries=1, base_delay=0.3, max_delay=0.6, retryable_exceptions=(httpx.HTTPError,)
)
_RETRY_CONFIG = RetryConfig(
    max_retries=2,
    base_delay=0.4,
    max_delay=1.6,
    retryable_exceptions=(httpx.HTTPError,),
)
_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
}

# Markers that indicate a captcha / bot-challenge / JS-app-shell page.
_GATING_MARKERS = (
    "captcha",
    "cf-challenge",
    "challenge-platform",
    "you have been blocked",
    "access denied",
    "unusual traffic",
    "verify you are human",
    "enable javascript",
    "cloudflare",
    "cf-ray",
)

_JSON_LD_RE = re.compile(
    r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.IGNORECASE | re.DOTALL,
)
_PRICE_RE = re.compile(r"\$\s?([\d,]+(?:\.\d{1,2})?)")
# Bare number (with optional $) used for rate-table *cells* — the III tables
# render many values without a leading "$".
_MONEY_RE = re.compile(r"([\d,]+(?:\.\d{1,2})?)")

_STATE_ABBR: dict[str, str] = {
    "AL": "Alabama",
    "AK": "Alaska",
    "AZ": "Arizona",
    "AR": "Arkansas",
    "CA": "California",
    "CO": "Colorado",
    "CT": "Connecticut",
    "DE": "Delaware",
    "FL": "Florida",
    "GA": "Georgia",
    "HI": "Hawaii",
    "ID": "Idaho",
    "IL": "Illinois",
    "IN": "Indiana",
    "IA": "Iowa",
    "KS": "Kansas",
    "KY": "Kentucky",
    "LA": "Louisiana",
    "ME": "Maine",
    "MD": "Maryland",
    "MA": "Massachusetts",
    "MI": "Michigan",
    "MN": "Minnesota",
    "MS": "Mississippi",
    "MO": "Missouri",
    "MT": "Montana",
    "NE": "Nebraska",
    "NV": "Nevada",
    "NH": "New Hampshire",
    "NJ": "New Jersey",
    "NM": "New Mexico",
    "NY": "New York",
    "NC": "North Carolina",
    "ND": "North Dakota",
    "OH": "Ohio",
    "OK": "Oklahoma",
    "OR": "Oregon",
    "PA": "Pennsylvania",
    "RI": "Rhode Island",
    "SC": "South Carolina",
    "SD": "South Dakota",
    "TN": "Tennessee",
    "TX": "Texas",
    "UT": "Utah",
    "VT": "Vermont",
    "VA": "Virginia",
    "WA": "Washington",
    "WV": "West Virginia",
    "WI": "Wisconsin",
    "WY": "Wyoming",
    "DC": "District of Columbia",
}


class _NotScrapeable(Exception):
    """Raised internally when a page is gated or contains no quote data."""


# ── parsing helpers ────────────────────────────────────────────────────
def _normalize_cell(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _as_money(value: str) -> float | None:
    """Parse a ``$1,234.56`` / ``1,234`` / ``1234`` cell to float."""
    match = _MONEY_RE.search(value)
    if not match:
        return None
    try:
        return float(match.group(1).replace(",", ""))
    except ValueError:
        return None


def _parse_quote_page(html: str) -> float | None:
    """Extract a premium from a provider page (JSON-LD first, then text)."""
    for match in _JSON_LD_RE.findall(html):
        try:
            data = json.loads(match)
        except json.JSONDecodeError:
            continue
        nodes = data if isinstance(data, list) else [data]
        for node in nodes:
            if not isinstance(node, dict):
                continue
            offers = node.get("offers")
            if not isinstance(offers, dict):
                continue
            for key in ("price", "lowPrice", "highPrice"):
                raw = offers.get(key)
                if raw is None:
                    continue
                text = str(raw).strip()
                if not text:
                    continue
                try:
                    return float(text.replace(",", "").replace("$", "").strip())
                except ValueError:
                    continue
    # Fall back to the first dollar figure in visible text.
    match = _PRICE_RE.search(html)
    if match:
        try:
            return float(match.group(1).replace(",", ""))
        except ValueError:
            return None
    return None


def _is_gated(status: int, content_type: str, body_lower: str) -> bool:
    if status >= 400 or status in (403, 406, 429, 503):
        return True
    if "text/html" not in content_type and "html" not in content_type:
        # JSON/JS payload or binary — not a static rate page.
        return True
    return any(marker in body_lower for marker in _GATING_MARKERS)


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in text for keyword in keywords)


def _looks_numeric(cell: str) -> bool:
    """True when a cell is a plain number (digits/commas/one dot), not prose.

    Guards against header/footnote cells like ``"Average premium (2)"``
    whose bare-number regex would otherwise match the footnote digit.
    """
    cleaned = cell.strip().lstrip("$").replace(",", "").replace(" ", "")
    if not cleaned:
        return False
    return cleaned.replace(".", "", 1).isdigit()


def _normalize_state(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def _match_state(cell: str, query: str) -> bool:
    """Match a table cell against a state name or two-letter abbreviation."""
    q = _normalize_state(query)
    if not q:
        return False
    c = _normalize_state(cell)
    abbr = _STATE_ABBR.get(q.upper())
    if abbr:
        # Two-letter query: match ONLY via the expanded full name so "CA"
        # does not substring-match "North Carolina".
        full = _normalize_state(abbr)
        return full == c or full in c
    return q == c or q in c or c in q
