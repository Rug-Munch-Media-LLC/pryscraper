"""Google Maps + Yelp review extraction for Pry.

Full-history review data that goes beyond the 5-review API cap. Lead-gen
use case: capture what customers actually say about a local business, not
just the aggregate rating.

Data sources:

* **Google Maps** — the place page (``google.com/maps?cid=...``) embeds a
  handful of reviews in two places:
  1. ``application/ld+json`` blocks with ``@type: Review`` nodes (author,
     rating, body, date) — stable and explicit.
  2. The ``window._p`` / ``window.APP_INITIALIZATION_STATE`` JS blobs.
     Review tuples are nested in the blob with no documented schema; the
     parser below is deliberately shape-based (author string + whole-number
     rating 1-5 + a long text string + optional date). Google moves these
     indexes without notice, so **blob review extraction is best-effort** —
     a wrong shape simply yields no reviews, never an exception.
* **Yelp** — the business page (``yelp.com/biz/{slug}``) embeds reviews in
  the ``data-hydrated-app-id="yelp-biz-page"`` JSON script (stable) with an
  HTML review-card fallback. Pagination follows Yelp's ``start`` parameter
  (``sort_by=date_desc``), capped by ``PRY_LOCAL_YELP_MAX_PAGES`` so we
  never hammer the site.

Anti-bot note:
    Both sources are JavaScript-heavy and frequently gate plain HTTP behind
    consent / "unusual traffic" / captcha walls. When that happens the
    module logs ``google_maps_anti_bot`` / ``yelp_anti_bot`` and returns
    ``[]`` — the escalation path is the repo's browser/stealth tier
    (``camoufox_integration``, ``stealth_engine``), not this module.

Contract:
    * ``get_reviews(place_id, source="google", limit=20)`` → list of
      ``{author, rating, text, date, source}`` records.

Async and never raises; on any failure returns ``[]``. robots.txt is
respected (best-effort, fail-open — see ``_robots_allowed``).
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import asyncio
import html
import json
import logging
import os
import re
import time
from typing import TYPE_CHECKING, Any
from urllib.parse import quote, urlparse

import httpx
from lxml import html as lxml_html

from datasets.local_data.places import _extract_blobs, _iter_values, _place_url
from pry.api.client import get_client

if TYPE_CHECKING:
    from collections.abc import Iterator

logger = logging.getLogger(__name__)

# ── Configuration ────────────────────────────────────────────────────────
HTTP_TIMEOUT = httpx.Timeout(connect=8.0, read=20.0, write=10.0, pool=8.0)
MAX_RETRIES = 3
RETRY_BASE = 0.8
MAX_BACKOFF = 6.0
RESULT_CACHE_TTL = 30.0  # in-memory result cache TTL (seconds)
ROBOTS_CACHE_TTL = 300.0  # robots.txt per-host cache TTL (seconds)
YELP_MAX_PAGES = 5  # pagination cap for the "full history" sweep

YELP_BIZ_URL = "https://www.yelp.com/biz/{slug}"

# Browser-ish headers: both Google Maps and Yelp serve the JS page (with
# embedded JSON) to normal user agents; a bare "pry/3.0" UA gets the no-JS
# shell.
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

_ANTI_BOT_SIGNALS = (
    "unusual traffic",
    "unusual activity",
    "are you a robot",
    "enable javascript",
    "not a robot",
    "recaptcha",
    "captcha",
    "consent.google.com",
)

_LD_RE = re.compile(
    r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.DOTALL | re.IGNORECASE,
)
_YELP_BIZ_JSON_RE = re.compile(
    r'<script[^>]*data-hydrated-app-id=["\']yelp-biz-page["\'][^>]*>(.*?)</script>',
    re.DOTALL | re.IGNORECASE,
)
_WS_RE = re.compile(r"\s+")
_DATE_RE = re.compile(
    r"(\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{4}|[a-z]{3,9}\s+\d{1,2},?\s+\d{4}|"
    r"\d+\s+(year|month|week|day|hour)s?\s+ago)",
    re.IGNORECASE,
)

_cache: dict[str, tuple[float, Any]] = {}
_robots_cache: dict[str, tuple[float, bool]] = {}


def _clear_cache() -> None:
    """Clear all in-memory caches (used by tests)."""
    _cache.clear()
    _robots_cache.clear()


# ── Small coercion helpers ───────────────────────────────────────────────
def _opt_float(value: Any) -> float | None:
    """Coerce a value to float; None on any failure."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _clean_text(value: Any) -> str:
    """Collapse whitespace + unescape HTML entities; "" for empty input."""
    return html.unescape(_WS_RE.sub(" ", str(value or "")).strip())


def _normalize_date(value: str) -> str:
    """Trim an ISO datetime ("2024-03-15 10:00:00") to its date part."""
    m = re.match(r"^(\d{4}-\d{2}-\d{2})", value.strip())
    return m.group(1) if m else value.strip()


def _env_int(name: str, default: int) -> int:
    """Parse an env var as a positive int; ``default`` on failure."""
    raw = os.environ.get(name, "").strip()
    try:
        return max(1, int(raw))
    except ValueError:
        return default


def _cache_get(key: str) -> Any | None:
    """Return a cached value, or None when expired/missing."""
    entry = _cache.get(key)
    if entry is None:
        return None
    ts, value = entry
    if time.monotonic() - ts > RESULT_CACHE_TTL:
        _cache.pop(key, None)
        return None
    return value


def _cache_set(key: str, value: Any) -> None:
    """Store a value under ``key``."""
    _cache[key] = (time.monotonic(), value)


def _retry_delay(resp: httpx.Response | None, attempt: int) -> float:
    """Exponential backoff, honoring Retry-After when present."""
    if resp is not None:
        raw = resp.headers.get("Retry-After")
        if raw:
            try:
                return min(float(raw), MAX_BACKOFF)
            except ValueError:
                pass  # malformed Retry-After header — fall back to default backoff
    return min(RETRY_BASE * (2**attempt), MAX_BACKOFF)


# ── HTTP with timeout + backoff ──────────────────────────────────────────
async def _http_get(
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    retries: int = MAX_RETRIES,
) -> httpx.Response | None:
    """GET with browser headers, timeouts, and exponential backoff.

    Retries on 429 (honoring Retry-After) and 5xx. Never raises: returns
    None on transport errors or after exhausting retries.
    """
    merged = dict(_HEADERS)
    if headers:
        merged.update(headers)
    client = await get_client()
    attempt = 0
    while True:
        try:
            resp = await client.get(
                url,
                params=params,
                headers=merged,
                timeout=HTTP_TIMEOUT,
                follow_redirects=True,
            )
        except httpx.HTTPError as exc:
            logger.warning("http_error", extra={"url": url, "error": str(exc)[:200]})
            return None
        if resp.status_code == 429 or resp.status_code >= 500:
            if attempt >= retries:
                logger.warning(
                    "http_retries_exhausted", extra={"url": url, "status": resp.status_code}
                )
                return None
            delay = _retry_delay(resp, attempt)
            logger.info(
                "http_backoff", extra={"url": url, "status": resp.status_code, "delay": delay}
            )
            await asyncio.sleep(delay)
            attempt += 1
            continue
        return resp


# ── robots.txt (best-effort, fail-open) ──────────────────────────────────
async def _robots_allowed(url: str) -> bool:
    """Check robots.txt for ``url`` with a short per-host cache.

    Fails open (returns True) when robots.txt cannot be fetched or when
    ``PRY_LOCAL_RESPECT_ROBOTS`` is set to anything other than
    "1"/"true"/"yes"/"on". Reuses :func:`compliance.policy.check_robots_txt`.
    """
    if os.environ.get("PRY_LOCAL_RESPECT_ROBOTS", "1").strip().lower() not in (
        "1",
        "true",
        "yes",
        "on",
    ):
        return True
    parsed = urlparse(url)
    key = f"{parsed.scheme}://{parsed.netloc}"
    now = time.monotonic()
    cached = _robots_cache.get(key)
    if cached and now - cached[0] < ROBOTS_CACHE_TTL:
        return cached[1]
    allowed = True
    try:
        from compliance.policy import check_robots_txt  # lazy: heavy import

        result = await check_robots_txt(url)
        allowed = bool(result.get("crawl_allowed", True))
        if not allowed:
            logger.warning(
                "robots_blocked",
                extra={"url": url, "matched": result.get("matched_disallow")},
            )
    except Exception:  # noqa: BLE001 — fail open; never break on robots errors
        allowed = True
    _robots_cache[key] = (now, allowed)
    return allowed


# ── URL building ─────────────────────────────────────────────────────────
def _yelp_url(slug: str, start: int = 0) -> str:
    """Build a Yelp business-page URL with date-sorted pagination."""
    base = YELP_BIZ_URL.format(slug=quote(slug))
    query = "sort_by=date_desc"
    if start:
        query += f"&start={start}"
    return f"{base}?{query}"


def _is_anti_bot(html_text: str) -> bool:
    """Detect consent/captcha/"unusual traffic" walls in the first 300 KB."""
    low = html_text[:300_000].lower()
    return any(sig in low for sig in _ANTI_BOT_SIGNALS)


# ── Shared nested walker ─────────────────────────────────────────────────
def _iter_dicts(obj: Any, depth: int = 0) -> Iterator[dict[str, Any]]:
    """Yield nested dict values up to ``depth``."""
    if depth > 6:
        return
    if isinstance(obj, dict):
        yield obj
        for value in obj.values():
            yield from _iter_dicts(value, depth + 1)
    elif isinstance(obj, list):
        for item in obj:
            yield from _iter_dicts(item, depth + 1)


# ── Google Maps: JSON-LD reviews ─────────────────────────────────────────
def _is_review_node(d: dict[str, Any]) -> bool:
    """True for JSON-LD nodes that look like a Review."""
    types = d.get("@type") or d.get("type") or []
    if isinstance(types, str):
        types = [types]
    if any(isinstance(t, str) and t.lower() == "review" for t in types):
        return True
    # Loose fallback: a node with body + rating is a review.
    return bool(d.get("reviewBody") and (d.get("reviewRating") or d.get("rating")))


def _review_from_jsonld(d: dict[str, Any]) -> dict[str, Any] | None:
    """Normalize a JSON-LD Review node into a review record."""
    author_value = d.get("author") or {}
    if isinstance(author_value, dict):
        author = _clean_text(author_value.get("name"))
    elif isinstance(author_value, str):
        author = _clean_text(author_value)
    else:
        author = ""
    rating_value = d.get("reviewRating") or d.get("rating") or {}
    if isinstance(rating_value, dict):
        rating = _opt_float(rating_value.get("ratingValue"))
    elif isinstance(rating_value, (int, float)):
        rating = _opt_float(rating_value)
    else:
        rating = None
    text = _clean_text(d.get("reviewBody") or d.get("description"))
    date = _normalize_date(_clean_text(d.get("datePublished")))
    if not author or rating is None or not text:
        return None
    return {
        "author": author,
        "rating": float(rating),
        "text": text,
        "date": date,
        "source": "google",
    }


def _jsonld_reviews(html_text: str) -> list[dict[str, Any]]:
    """Parse application/ld+json blocks, returning Review records."""
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for m in _LD_RE.finditer(html_text):
        try:
            data = json.loads(m.group(1))
        except (json.JSONDecodeError, ValueError):
            continue
        for d in _iter_dicts(data):
            if not _is_review_node(d):
                continue
            rec = _review_from_jsonld(d)
            if not rec:
                continue
            key = (rec["author"].lower(), rec["text"][:60].lower())
            if key not in seen:
                seen.add(key)
                out.append(rec)
    return out


# ── Google Maps: blob review tuples (shape-based, best-effort) ───────────
def _rating_is_whole(value: Any) -> bool:
    """True for a whole-number star rating in the 1-5 range."""
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and 1 <= value <= 5
        and float(value).is_integer()
    )


def _plausible_name(value: Any) -> bool:
    """True for a string that could be a reviewer name (not a URL)."""
    if not isinstance(value, str) or not value.strip():
        return False
    if value.startswith(("http://", "https://")):
        return False
    return len(value) < 80 and bool(re.search(r"[A-Za-z]", value))


def _plausible_review_text(value: Any) -> bool:
    """True for a string long enough to be review prose, not a field value."""
    if not isinstance(value, str) or len(value) < 20:
        return False
    if value.startswith(("http://", "https://")):
        return False
    return len(value.split()) >= 3 and any(ch.isalpha() for ch in value)


def _looks_like_date_text(value: Any) -> bool:
    """True for a string matching a relative ("2 months ago") or absolute date."""
    return isinstance(value, str) and bool(_DATE_RE.search(value))


def _google_review_from_tuple(obj: list[Any]) -> dict[str, Any] | None:
    """Normalize a Google Maps blob review tuple into a review record.

    The Maps embed has no documented schema; tuples drift between releases.
    Discriminator (all must hold) — the tuple has at least 6 cells, an
    author-like first cell, a whole-number 1-5 rating, a long prose text,
    and either a date-like string or a long tuple (>= 10 cells). Wrong
    shapes yield None, never an exception.
    """
    if not isinstance(obj, list) or len(obj) < 6:
        return None
    author = next((c.strip() for c in obj[:6] if _plausible_name(c)), "")
    rating = next((c for c in obj if _rating_is_whole(c)), None)
    texts = [c for c in obj if _plausible_review_text(c)]
    text = max(texts, key=len) if texts else ""
    date = next((c for c in obj if _looks_like_date_text(c)), "")
    if not author or rating is None or not text:
        return None
    if not date and len(obj) < 10:
        return None
    return {
        "author": author,
        "rating": float(rating),
        "text": text,
        "date": date,
        "source": "google",
    }


def _google_reviews_from_blobs(blobs: list[Any]) -> list[dict[str, Any]]:
    """Extract review records from decoded Maps blobs (shape-based)."""
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for blob in blobs:
        for obj in _iter_values(blob):
            if not isinstance(obj, list):
                continue
            rec = _google_review_from_tuple(obj)
            if not rec:
                continue
            key = (rec["author"].lower(), rec["text"][:60].lower())
            if key in seen:
                continue
            seen.add(key)
            out.append(rec)
    return out


# ── Yelp: embedded JSON (primary) ────────────────────────────────────────
def _yelp_review_from_json(item: Any) -> dict[str, Any] | None:
    """Normalize a Yelp ``yelp-biz-page`` review object into a record."""
    if not isinstance(item, dict):
        return None
    text = _clean_text(item.get("text"))
    rating = _opt_float(item.get("rating"))
    if not text or rating is None:
        return None
    user = item.get("user")
    author = _clean_text(user.get("name")) if isinstance(user, dict) else ""
    date = _normalize_date(_clean_text(item.get("time_created")))
    return {
        "author": author,
        "rating": float(rating),
        "text": text,
        "date": date,
        "source": "yelp",
    }


def _yelp_reviews_from_json(html_text: str) -> list[dict[str, Any]]:
    """Parse the ``data-hydrated-app-id="yelp-biz-page"`` JSON payload."""
    match = _YELP_BIZ_JSON_RE.search(html_text)
    if not match:
        return []
    try:
        data = json.loads(match.group(1))
    except (json.JSONDecodeError, ValueError):
        return []
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for d in _iter_dicts(data):
        for key in ("reviews", "reviewFeed"):
            items = d.get(key)
            if not isinstance(items, list):
                continue
            for item in items:
                rec = _yelp_review_from_json(item)
                if not rec:
                    continue
                dedupe_key = (rec["author"].lower(), rec["text"][:60].lower())
                if dedupe_key in seen:
                    continue
                seen.add(dedupe_key)
                out.append(rec)
    return out


# ── Yelp: HTML review cards (fallback) ───────────────────────────────────
def _parse_star_title(value: str) -> float | None:
    """Parse "5.0 star rating" from an i-stars title/aria-label."""
    m = re.search(r"(\d+(?:\.\d+)?)\s*star", value, re.IGNORECASE)
    return _opt_float(m.group(1)) if m else None


def _node_join(node: Any, xpath: str) -> str:
    """Join all text/attr matches for ``xpath`` under ``node`` into a string."""
    return _clean_text(" ".join(node.xpath(xpath)))


def _parse_aria_review(label: str) -> tuple[str, str]:
    """Parse "review by Alice J. on 2/15/2024" → (author, date)."""
    m = re.search(r"review by\s+(.+?)(?:\s+on\s+(.+?))?$", label, re.IGNORECASE)
    if not m:
        return "", ""
    return m.group(1).strip(), (m.group(2).strip() if m.group(2) else "")


def _review_cards(tree: Any) -> list[Any]:
    """Collect Yelp review-card nodes (new aria-label layout + legacy classes)."""
    cards: list[Any] = []
    seen: set[int] = set()
    xpaths = (
        "//*[@role='region' and contains(@aria-label, 'review')]",
        "//li[contains(@aria-label, 'review')]",
        "//*[contains(concat(' ', normalize-space(@class), ' '), ' review ') "
        "and not(contains(concat(' ', normalize-space(@class), ' '), ' review-content '))]",
    )
    for xp in xpaths:
        for node in tree.xpath(xp):
            marker = id(node)
            if marker in seen:
                continue
            seen.add(marker)
            cards.append(node)
    return cards


def _yelp_reviews_from_html(html_text: str) -> list[dict[str, Any]]:
    """Parse Yelp review cards from raw HTML (legacy page fallback)."""
    try:
        tree = lxml_html.fromstring(html_text)
    except (ValueError, TypeError):
        return []
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for node in _review_cards(tree):
        aria_author, aria_date = _parse_aria_review(_node_join(node, "@aria-label"))
        author = _node_join(node, ".//*[contains(@class, 'user-display-name')]//text()")
        if not author:
            author = aria_author
        rating = _parse_star_title(_node_join(node, ".//*[contains(@class, 'i-stars')]/@title"))
        text = _node_join(node, ".//p[@lang]//text()")
        if not text:
            text = _node_join(node, ".//*[contains(@class, 'review-content')]//text()")
        date = _node_join(node, ".//meta[@itemprop='datePublished']/@content")
        if not date:
            date = aria_date
        if not date:
            for chunk in node.xpath(".//text()"):
                m = _DATE_RE.search(chunk)
                if m:
                    date = m.group(0)
                    break
        if not author or rating is None or not text:
            continue
        key = (author.lower(), text[:60].lower())
        if key in seen:
            continue
        seen.add(key)
        out.append(
            {
                "author": author,
                "rating": rating,
                "text": text,
                "date": date,
                "source": "yelp",
            }
        )
    return out


def _parse_yelp_reviews(html_text: str) -> list[dict[str, Any]]:
    """Yelp reviews: embedded JSON first, HTML cards as fallback."""
    records = _yelp_reviews_from_json(html_text)
    if records:
        return records
    return _yelp_reviews_from_html(html_text)


# ── Public API (never raises) ────────────────────────────────────────────
async def _reviews_google(place_id: str) -> list[dict[str, Any]]:
    """Fetch + parse reviews from a Google Maps place page."""
    url = _place_url(place_id)
    if not await _robots_allowed(url):
        return []
    resp = await _http_get(url)
    if resp is None or resp.status_code >= 400:
        return []
    html_text = resp.text
    if _is_anti_bot(html_text):
        logger.warning(
            "google_maps_anti_bot",
            extra={"place_id": place_id, "hint": "requires repo browser/stealth tier"},
        )
        return []
    merged: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for rec in [
        *_jsonld_reviews(html_text),
        *_google_reviews_from_blobs(_extract_blobs(html_text)),
    ]:
        key = (rec["author"].strip().lower(), rec["text"][:60].strip().lower())
        if key in seen:
            continue
        seen.add(key)
        merged.append(rec)
    return merged


async def _reviews_yelp(slug: str, limit: int) -> list[dict[str, Any]]:
    """Fetch + parse Yelp reviews, paginating by ``start`` until limit/cap."""
    if not await _robots_allowed(_yelp_url(slug, 0)):
        return []
    collected: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    max_pages = _env_int("PRY_LOCAL_YELP_MAX_PAGES", YELP_MAX_PAGES)
    for page in range(max_pages):
        url = _yelp_url(slug, page * 10)
        resp = await _http_get(url)
        if resp is None or resp.status_code >= 400:
            break
        html_text = resp.text
        if _is_anti_bot(html_text):
            logger.warning("yelp_anti_bot", extra={"slug": slug})
            break
        fresh = 0
        for rec in _parse_yelp_reviews(html_text):
            key = (rec["author"].strip().lower(), rec["text"][:60].strip().lower())
            if key in seen:
                continue
            seen.add(key)
            collected.append(rec)
            fresh += 1
        if fresh == 0 or len(collected) >= limit:
            break
    return collected


async def get_reviews(
    place_id: str, source: str = "google", limit: int = 20
) -> list[dict[str, Any]]:
    """Google Maps / Yelp review history. Never raises; [] on any failure.

    ``place_id`` is a Google Maps CID / hex / slug (source="google") or a
    Yelp business slug (source="yelp"). Reviews are deduplicated by
    (author, text) and capped at ``limit``.
    """
    try:
        src = (source or "").strip().lower()
        pid = str(place_id or "").strip()
        if src not in ("google", "yelp") or not pid:
            return []
        if limit < 1:
            limit = 1
        cache_key = f"reviews:{src}:{pid.lower()}"
        cached = _cache_get(cache_key)
        if cached is not None:
            return list(cached)[:limit]
        if src == "google":
            records = await _reviews_google(pid)
        else:
            records = await _reviews_yelp(pid, limit)
        _cache_set(cache_key, records)
        return list(records)[:limit]
    except Exception:  # public API boundary: never-raise contract
        logger.exception("get_reviews_failed")
        return []
