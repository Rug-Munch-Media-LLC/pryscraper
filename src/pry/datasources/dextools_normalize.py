# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
"""HTML -> normalized Dextools rows (pure; no network).

Schema: see ``pry.datasources.dextools_types`` (``ROW_FIELDS``). Extraction is
strictly evidence-based: a field is filled only when the rendered page states
it in a recognisable form; otherwise it stays ``None``.
"""

from __future__ import annotations

import html as html_mod
import json
import logging
import re
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

from pry.datasources.dextools_types import ROW_FIELDS

logger = logging.getLogger(__name__)

_META = re.compile(
    r'<meta[^>]+(?:property|name)="(og:[^"]+|twitter:[^"]+)"[^>]+content="([^"]*)"', re.I
)
_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.S | re.I)
_PAIR = re.compile(
    r'href="(?:https://www\.dextools\.io)?/app/([a-z0-9_-]+)/pair-explorer/([^"/?#]+)"', re.I
)
_SYMBOL_NAME = re.compile(r"\(\s*([A-Za-z0-9$._-]{2,20})\s*\)")
_PRICE = re.compile(r"(?:price|Price)\s*[^$]{0,16}\$\s?([0-9][0-9,]*(?:\.[0-9]+)?)")
_LIQ = re.compile(r"[Ll]iquidity\s*[^$]{0,16}\$\s?([0-9][0-9,]*(?:\.[0-9]+)?)")
_VOL = re.compile(r"24[hH]\s*[Vv]ol(?:ume)?\s*[^$]{0,16}\$\s?([0-9][0-9,]*(?:\.[0-9]+)?)")
_SOCIAL = re.compile(
    r'href="(https?://(?:www\.)?(?:x\.com|twitter\.com|t\.me|telegram\.me|discord\.gg|discord\.com)/[^"]+)"',
    re.I,
)


def _num(pattern: re.Pattern[str], text: str) -> float | None:
    match = pattern.search(text)
    return float(match.group(1).replace(",", "")) if match else None


def normalize_page(url: str, page_html: str, fetched_at: str | None = None) -> list[dict[str, Any]]:
    """Normalize one rendered Dextools page into rows (one per pair link, plus the page's own pair)."""
    parts = urlsplit(url)
    segments = [seg for seg in parts.path.split("/") if seg]
    chain = (
        segments[1]
        if len(segments) > 1 and segments[0] == "app"
        else (segments[0] if segments else "unknown")
    )

    meta = {key.lower(): html_mod.unescape(value) for key, value in _META.findall(page_html)}
    title_match = _TITLE.search(page_html)
    title = (
        html_mod.unescape(re.sub(r"<[^>]+>", "", title_match.group(1))).strip()
        if title_match
        else ""
    )
    headline = meta.get("og:title") or title
    symbol_match = _SYMBOL_NAME.search(headline)

    text = html_mod.unescape(re.sub(r"<script.*?</script>", " ", page_html, flags=re.S | re.I))
    text = re.sub(r"<[^>]+>", " ", text)

    row: dict[str, Any] = dict.fromkeys(ROW_FIELDS)
    row.update(
        {
            "chain": chain,
            "symbol": symbol_match.group(1) if symbol_match else None,
            "name": headline.split("(")[0].strip() or None,
            "price_usd": _num(_PRICE, text),
            "liquidity_usd": _num(_LIQ, text),
            "volume_24h_usd": _num(_VOL, text),
            "socials": sorted(set(_SOCIAL.findall(page_html))),
            "source_url": url,
            "fetched_at": fetched_at or datetime.now(UTC).isoformat(timespec="seconds"),
        }
    )
    if "pair-explorer" in parts.path:
        row["address"] = parts.path.rstrip("/").rsplit("/", 1)[-1]

    rows: list[dict[str, Any]] = [row] if row["address"] else []
    seen = {row["address"]}
    for link_chain, address in _PAIR.findall(page_html):
        if address in seen:
            continue
        seen.add(address)
        child = dict.fromkeys(ROW_FIELDS)
        child.update(
            {
                "chain": link_chain,
                "address": address,
                "socials": [],
                "source_url": url,
                "fetched_at": row["fetched_at"],
            }
        )
        rows.append(child)
    return rows


def rows_from_json(payload: str) -> list[dict[str, Any]]:
    """Rows from an embedded ``__NEXT_DATA__``-style JSON blob (returns [] when absent)."""
    match = re.search(r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>', payload, re.S)
    if not match:
        return []
    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError:
        logger.debug("best-effort fallback", exc_info=True)
        return []
    return data.get("rows", []) if isinstance(data, dict) else []
