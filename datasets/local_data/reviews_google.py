"""Google Maps review extraction (JSON-LD + blob tuples, shape-based).

The Maps place page (``google.com/maps?cid=...``) embeds reviews in two
places:

1. ``application/ld+json`` blocks with ``@type: Review`` nodes (author,
   rating, body, date) — stable and explicit.
2. The ``window._p`` / ``window.APP_INITIALIZATION_STATE`` JS blobs.
   Review tuples are nested in the blob with no documented schema; the
   parser below is deliberately shape-based (author string + whole-number
   rating 1-5 + a long text string + optional date). Google moves these
   indexes without notice, so **blob review extraction is best-effort** —
   a wrong shape simply yields no reviews, never an exception.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import json
import logging
import re
from typing import Any

from datasets.local_data.places import _extract_blobs, _iter_values, _place_url
from datasets.local_data.reviews_common import (
    _DATE_RE,
    _cache_get,
    _cache_set,
    _clean_text,
    _http_get,
    _is_anti_bot,
    _iter_dicts,
    _normalize_date,
    _opt_float,
    _robots_allowed,
)

logger = logging.getLogger(__name__)

_LD_RE = re.compile(
    r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.DOTALL | re.IGNORECASE,
)


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


# ── Fetcher ──────────────────────────────────────────────────────────────
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


__all__ = ["_cache_get", "_cache_set", "_reviews_google"]
