"""Google Play embedded-JSON constants, mappers, and extractors.

Shared, stateless building blocks for the Google Play store scrapers:
URLs/headers, small value mappers, embedded-JSON walking helpers, and
the ``__NEXT_DATA__`` / ``AF_initDataCallback`` extractors.

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
from typing import TYPE_CHECKING, Any

import httpx

if TYPE_CHECKING:
    from collections.abc import Iterator

_SEARCH_URL = "https://play.google.com/store/search"
_DETAILS_URL = "https://play.google.com/store/apps/details"
_REVIEWS_URL = "https://play.google.com/store/getreviews"
_STORE_URL_TMPL = "https://play.google.com/store/apps/details?id={package}"
_TIMEOUT = httpx.Timeout(20.0)
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
}
_MAX_LIMIT = 100
_NEXT_DATA_RE = re.compile(
    r'<script[^>]*id="__NEXT_DATA__"[^>]*type="application/json"[^>]*>(.*?)</script>',
    re.DOTALL,
)
_AF_INIT_RE = re.compile(r"AF_initDataCallback\((\{.*?\})\);?\s*$", re.DOTALL)
_MAGIC_PREFIX = ")]}'"
_ANTI_BOT_MARKERS = (
    "unusual traffic",
    "captcha",
    "recaptcha",
    "enable javascript",
    "are you a robot",
    "verify you're human",
    "verify you are human",
    "access denied",
    "pardon the interruption",
    "sorry, something went wrong",
)


class _AntiBotError(Exception):
    """Internal marker: the store answered with an anti-bot page."""


# ── Small mappers ─────────────────────────────────────────────────────
def _as_text(value: Any) -> str:
    """Return ``value`` as text, or '' for None."""
    if value is None:
        return ""
    return str(value).strip()


def _as_float(value: Any) -> float | None:
    """Return ``value`` as float, or None when it cannot be parsed."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> int | None:
    """Return ``value`` as int, or None when it cannot be parsed."""
    if value is None:
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _format_price(price: Any, price_value: Any) -> str:
    """Return a storefront price string, or '' for free/unknown."""
    text = _as_text(price)
    if text:
        return text
    value = _as_float(price_value)
    if value is None or value <= 0:
        return ""
    if value == int(value):
        return f"${int(value)}"
    return f"${value:.2f}"


# ── Embedded-JSON walking ─────────────────────────────────────────────
def _iter_dicts(obj: Any) -> Iterator[dict[str, Any]]:
    """Yield every dict in a nested JSON structure (depth-first)."""
    if isinstance(obj, dict):
        yield obj
        for value in obj.values():
            yield from _iter_dicts(value)
    elif isinstance(obj, list):
        for item in obj:
            yield from _iter_dicts(item)


def _is_app_entry(entry: dict[str, Any]) -> bool:
    """True when ``entry`` looks like a Play app record in embedded JSON."""
    return isinstance(entry.get("appId"), str) and bool(entry.get("title") or entry.get("appName"))


def _find_app_entry(obj: Any, package: str | None = None) -> dict[str, Any] | None:
    """Find the first app-shaped dict in embedded JSON.

    When ``package`` is given, prefer the entry whose ``appId`` matches.
    """
    preferred: dict[str, Any] | None = None
    for entry in _iter_dicts(obj):
        if not _is_app_entry(entry):
            continue
        if package is not None and entry.get("appId") == package:
            return entry
        if preferred is None:
            preferred = entry
    return preferred


def _iter_review_rows(obj: Any) -> Iterator[list[Any]]:
    """Yield rows that look like Play review records in getreviews JSON.

    A getreviews row is a positional list of ~14 slots:
    ``[reviewId, userName, avatar, date, ts, commentary, null, [score],
    [reply], null, null, appVersion, appVersionCode, thumbsUp, ...]``.
    """
    if isinstance(obj, list):
        if (
            len(obj) >= 11
            and isinstance(obj[0], str)
            and isinstance(obj[1], str)
            and isinstance(obj[5], str)
        ):
            yield obj
        for item in obj:
            yield from _iter_review_rows(item)


# ── Page extractors ───────────────────────────────────────────────────
def _extract_next_data(html: str) -> Any:
    """Parse the ``__NEXT_DATA__`` JSON blob out of a Play HTML page."""
    match = _NEXT_DATA_RE.search(html)
    if not match:
        return None
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError:
        return None


def _extract_af_init(html: str) -> list[Any]:
    """Parse legacy ``AF_initDataCallback`` JSON payloads out of a page."""
    payloads: list[Any] = []
    for match in _AF_INIT_RE.finditer(html):
        block = match.group(1)
        # Callback blocks are JS object literals; the useful bit is the
        # ``data: {...}`` value, which we extract with a tolerant brace scan.
        data_start = block.find("data:")
        if data_start == -1:
            continue
        try:
            payloads.append(json.loads(block[data_start + len("data:") :]))
        except json.JSONDecodeError:
            continue
    return payloads
