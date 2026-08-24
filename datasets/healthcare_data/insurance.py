"""Insurance quotes — feasibility-flagged, with public rate-table fallback.

Car/home insurance **quote forms** (Progressive, Geico, State Farm, ...) are
captcha/JS-gated: they require a browser session to fill multi-step forms and
return live quotes. A plain HTTP scrape of those forms is not reliable. This
module is honest about that — :func:`get_insurance_quotes` probes the known
quote forms, detects the gating, and returns a documented
``{"available": False, "reason": ...}`` payload instead of fabricating
quotes.

What *is* scrapeable without auth or a browser is **public rate tables** —
aggregated average-premium tables published on static pages. This module
implements that path via :func:`get_insurance_rate_table`, which parses the
static state-by-state tables published by the Insurance Information
Institute (iii.org; no auth, no captcha) for auto and homeowners/renters
coverage.

Contract
--------
* :func:`get_insurance_quotes` — async, never raises. Returns
  ``{"available": True, "coverage_type": ..., "quotes": [...]}`` when a
  provider page is parseable, or ``{"available": False, "reason": ...,
  "quotes": []}`` when every probed form is gated / unavailable. Never
  returns fabricated premiums.
* :func:`get_insurance_rate_table` — async, never raises, returns a
  ``list`` (``[]`` on failure). Public aggregate rate-table data. Auto
  coverage returns the III most/least expensive states tables (20 states);
  home coverage returns the full III state-by-state average-premium table.

Quote record shape: ``{"provider": ..., "premium": float, "deductible":
None, "url": ...}``. Rate-table record shape: ``{"state": ..., "premium":
float, "source": "public_rate_table", "url": ...}``.

Backoff: 1 retry for quote probes (short timeout), 2 for the rate table.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

import httpx
from lxml import etree, html as lxml_html

from pry.engine.retry import RetryConfig, async_retry

logger = logging.getLogger(__name__)

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


# ── quote probing ──────────────────────────────────────────────────────
async def _probe_provider(name: str, url: str, zipcode: str | None) -> dict[str, Any] | None:
    """Fetch one quote form; None when gated or without parseable data."""

    async def _one() -> dict[str, Any]:
        params = {"zipcode": zipcode} if zipcode else None
        async with httpx.AsyncClient(
            timeout=_PROBE_TIMEOUT, headers=_BROWSER_HEADERS, follow_redirects=True
        ) as client:
            response = await client.get(url, params=params)
            status = response.status_code
            ctype = response.headers.get("content-type", "")
            body = response.text[:20000]
        if _is_gated(status, ctype, body.lower()):
            raise _NotScrapeable(name)
        premium = _parse_quote_page(body)
        if premium is None:
            raise _NotScrapeable(name)
        return {"provider": name, "premium": premium, "deductible": None, "url": url}

    try:
        return await async_retry(_one, config=_PROBE_RETRY)
    except (_NotScrapeable, httpx.HTTPError, OSError, ValueError):
        return None


# ── public rate tables ─────────────────────────────────────────────────
async def _fetch_html(url: str, request_timeout: httpx.Timeout, config: RetryConfig) -> str | None:
    async def _one() -> str:
        async with httpx.AsyncClient(
            timeout=request_timeout, headers=_BROWSER_HEADERS, follow_redirects=True
        ) as client:
            response = await client.get(url)
            response.raise_for_status()
            return response.text

    try:
        return await async_retry(_one, config=config)
    except (httpx.HTTPError, OSError):
        return None


_STATE_KEYWORDS = ("state", "jurisdiction", "region")
_PREMIUM_KEYWORDS = ("premium", "expenditure", "cost", "rate", "price")
_SKIP_STATES = {"total", "national average", "u.s.", "us", "united states"}
_SKIP_STATE_HEADERS = {"state", "rank", "jurisdiction", "region"}


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


def _parse_rate_table(html: str, page_url: str) -> list[dict[str, Any]]:
    """Parse state + premium columns out of a public rate table.

    Handles both simple tables (one state column) and the paired III tables
    that put "most expensive" and "least expensive" state data side by side
    in the same row (two state columns). Header text is gathered from the
    first two rows because the III tables use a merged-cell header layout.
    """
    try:
        doc = lxml_html.fromstring(html)
    except (ValueError, etree.ParserError):
        return []
    for table in doc.xpath("//table"):
        row_elements = table.xpath(".//tr")
        if len(row_elements) < 2:
            continue
        header_rows: list[list[str]] = []
        for tr in row_elements[:2]:
            header_rows.append(
                [_normalize_cell(cell.text_content()) for cell in tr.xpath(".//th | .//td")]
            )
        width = max(len(row) for row in header_rows)
        state_cols: list[int] = []
        premium_cols: list[int] = []
        for col in range(width):
            combined = " ".join(row[col] if col < len(row) else "" for row in header_rows).lower()
            if _contains_any(combined, _STATE_KEYWORDS) and not _contains_any(
                combined, _PREMIUM_KEYWORDS
            ):
                state_cols.append(col)
            if _contains_any(combined, _PREMIUM_KEYWORDS):
                premium_cols.append(col)
        # Pair each state column with the nearest premium column after it.
        pairs: list[tuple[int, int]] = []
        for state_col in state_cols:
            following = [p for p in premium_cols if p > state_col]
            if following:
                pairs.append((state_col, following[0]))
        if not pairs:
            continue
        rows: list[dict[str, Any]] = []
        for tr in row_elements[1:]:
            cells = [_normalize_cell(cell.text_content()) for cell in tr.xpath(".//th | .//td")]
            if len(cells) <= max(premium for _, premium in pairs):
                continue
            for state_col, premium_col in pairs:
                state = cells[state_col]
                premium = _as_money(cells[premium_col])
                if not state or not _looks_numeric(cells[premium_col]) or premium is None:
                    continue
                if state.lower() in _SKIP_STATES or state.lower() in _SKIP_STATE_HEADERS:
                    continue
                rows.append(
                    {
                        "state": state,
                        "premium": premium,
                        "source": "public_rate_table",
                        "url": page_url,
                    }
                )
        if rows:
            return rows
    return []


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


# ── Public API ─────────────────────────────────────────────────────────
async def get_insurance_quotes(profile: dict[str, Any]) -> dict[str, Any]:
    """Request car/home insurance quotes.

    Args:
        profile: dict with ``coverage_type`` (``"auto"`` (default) |
            ``"home"``) and optional ``zip``.

    Returns:
        ``{"available": True, "coverage_type": ..., "quotes":
        [{provider, premium, deductible, url}]}`` when a provider page is
        parseable, otherwise the documented ``{"available": False,
        "reason": ..., "quotes": []}`` payload. Never raises and never
        returns fabricated premiums.
    """
    try:
        return await _get_insurance_quotes(profile)
    except Exception:
        logger.exception("health_insurance_quotes_crashed")
        return {
            "available": False,
            "reason": "insurance quote lookup failed unexpectedly",
            "coverage_type": str((profile or {}).get("coverage_type") or "auto"),
            "quotes": [],
        }


async def _get_insurance_quotes(profile: dict[str, Any]) -> dict[str, Any]:
    profile = profile or {}
    coverage_type = str(profile.get("coverage_type") or "auto").strip().lower()
    if coverage_type not in _COVERAGE_TYPES:
        return {
            "available": False,
            "reason": (
                f"unsupported coverage_type {coverage_type!r}; "
                f"expected one of {sorted(_COVERAGE_TYPES)}"
            ),
            "coverage_type": coverage_type,
            "quotes": [],
        }
    zipcode = str(profile.get("zip") or "").strip() or None
    providers = _PROVIDERS.get(coverage_type, ())
    results = await asyncio.gather(
        *(_probe_provider(name, url, zipcode) for name, url in providers)
    )
    quotes = [result for result in results if result is not None]
    sources_checked = [name for name, _ in providers]
    if quotes:
        return {
            "available": True,
            "coverage_type": coverage_type,
            "quotes": quotes,
            "sources_checked": sources_checked,
        }
    return {
        "available": False,
        "coverage_type": coverage_type,
        "quotes": [],
        "sources_checked": sources_checked,
        "reason": (
            "Car/home insurance quote forms are captcha/JS-gated and cannot be "
            "scraped reliably without a paid quote API or browser automation. "
            "Use get_insurance_rate_table() for public aggregate rate-table data."
        ),
    }


async def get_insurance_rate_table(
    state: str | None = None, coverage_type: str = "auto"
) -> list[dict[str, Any]]:
    """Fetch public aggregate insurance rate-table data.

    Args:
        state: Optional US state name or two-letter abbreviation (e.g.
            ``"CA"``, ``"Texas"``) to filter rows; None returns all states.
        coverage_type: ``"auto"`` (default) or ``"home"``.

    Returns:
        A list of ``{state, premium, source, url}`` records. ``[]`` on
        failure or unsupported coverage_type. Never raises.
    """
    try:
        return await _get_insurance_rate_table(state, coverage_type)
    except Exception:
        logger.exception(
            "health_insurance_rate_table_crashed",
            extra={"state": state, "coverage_type": coverage_type},
        )
        return []


async def _get_insurance_rate_table(state: str | None, coverage_type: str) -> list[dict[str, Any]]:
    normalized_type = str(coverage_type or "auto").strip().lower()
    page_url = _RATE_PAGES.get(normalized_type)
    if page_url is None:
        return []
    html = await _fetch_html(page_url, _TIMEOUT, _RETRY_CONFIG)
    if html is None:
        return []
    rows = _parse_rate_table(html, page_url)
    query = str(state or "").strip()
    if query:
        rows = [row for row in rows if _match_state(str(row.get("state") or ""), query)]
    return rows
