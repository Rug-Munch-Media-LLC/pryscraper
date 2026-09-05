"""Google Maps + Yelp review extraction for Pry.

Full-history review data that goes beyond the 5-review API cap. Lead-gen
use case: capture what customers actually say about a local business, not
just the aggregate rating.

This module is a thin facade; the implementation lives in:

* :mod:`datasets.local_data.reviews_common` — HTTP, robots.txt, caching,
  coercion helpers shared by both platforms.
* :mod:`datasets.local_data.reviews_google` — Google Maps JSON-LD +
  blob-tuple parsers and the Maps fetcher.
* :mod:`datasets.local_data.reviews_yelp` — Yelp embedded-JSON + HTML-card
  parsers and the paginated Yelp fetcher.

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

import logging
from typing import Any

from datasets.local_data.reviews_common import (  # noqa: F401 — re-exports
    HTTP_TIMEOUT,
    MAX_BACKOFF,
    MAX_RETRIES,
    RESULT_CACHE_TTL,
    RETRY_BASE,
    ROBOTS_CACHE_TTL,
    _cache_get,
    _cache_set,
    _clean_text,
    _clear_cache,
    _env_int,
    _http_get,
    _is_anti_bot,
    _iter_dicts,
    _normalize_date,
    _opt_float,
    _retry_delay,
    _robots_allowed,
)
from datasets.local_data.reviews_google import _reviews_google
from datasets.local_data.reviews_yelp import _reviews_yelp

logger = logging.getLogger(__name__)

__all__ = ["get_reviews"]


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
