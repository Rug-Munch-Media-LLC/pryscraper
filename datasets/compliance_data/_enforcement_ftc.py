"""FTC (cases & proceedings listing) source for ``compliance_data.enforcement``.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import html
import re
from typing import Any

from datasets.compliance_data._enforcement_data import _FTC_LIST_URL
from datasets.compliance_data._enforcement_helpers import (
    _as_text,
    _normalize_date,
    _sort_records,
    _strip_tags,
)
from datasets.compliance_data._enforcement_transport import _fetch_html

_FTC_ARTICLE_RE = re.compile(
    r'<article about="([^"]+)" class="node node--type-case[^"]*">(.*?)</article>', re.S
)
_FTC_TITLE_RE = re.compile(r'<h[1-6][^>]*class="[^"]*node-title[^"]*"[^>]*>(.*?)</h[1-6]>', re.S)


def _ftc_company_from_title(title: str | None) -> str | None:
    """Best-effort company extraction from an FTC case title."""
    if not title:
        return None
    text = title.strip()
    match = re.match(r"^(.*?), In the Matter of$", text)
    if match:
        return match.group(1).strip()
    match = re.match(r"^FTC v\.\s+(.+?)(?:,\s*(?:et al\.?|and others))?\.?$", text)
    if match:
        return match.group(1).strip()
    return text


def _parse_ftc_listing(page: str) -> list[dict[str, Any]]:
    """Parse the FTC cases & proceedings page into raw case rows."""
    rows: list[dict[str, Any]] = []
    for about, block in _FTC_ARTICLE_RE.findall(page):
        title_match = _FTC_TITLE_RE.search(block)
        title = _strip_tags(title_match.group(1)) if title_match else None
        time_match = re.search(r'<time datetime="([^"]+)"', block)
        docket_match = re.search(
            r'field--name-field-docket-number.*?field__item">([^<]+)<', block, re.S
        )
        type_match = re.search(
            r'field--name-field-case-action-type.*?field__item">([^<]+)<', block, re.S
        )
        slug = about.rstrip("/").rsplit("/", 1)[-1]
        if not title and not slug:
            continue
        rows.append(
            {
                "slug": slug,
                "title": title or slug,
                "date": _normalize_date(_as_text(time_match.group(1) if time_match else None)),
                "docket": _as_text(docket_match.group(1) if docket_match else None),
                "action_type": _as_text(type_match.group(1) if type_match else None),
                "url": f"https://www.ftc.gov{about}" if about.startswith("/") else about,
            }
        )
    return rows


def _map_ftc(raw: dict[str, Any]) -> dict[str, Any]:
    title = _as_text(raw.get("title"))
    return {
        "agency": "ftc",
        "id": f"ftc:{raw.get('slug')}" if raw.get("slug") else None,
        "title": title,
        "type": _as_text(raw.get("action_type")) or "FTC Case",
        "company": _ftc_company_from_title(title),
        "date": _as_text(raw.get("date")),
        "penalty_amount": None,
        "url": _as_text(raw.get("url")),
        "source": "ftc.gov",
    }


def _filter_ftc_rows(rows: list[dict[str, Any]], query: str) -> list[dict[str, Any]]:
    needle = query.strip().lower()
    if not needle:
        return rows
    return [
        row
        for row in rows
        if needle
        in " ".join(str(row.get(key) or "") for key in ("title", "docket", "action_type")).lower()
    ]


async def _fetch_ftc(query: str, limit: int) -> list[dict[str, Any]]:
    page = await _fetch_html(_FTC_LIST_URL)
    if page is None:
        return []
    rows = _filter_ftc_rows(_parse_ftc_listing(page), query)
    return _sort_records([_map_ftc(row) for row in rows], limit)


async def _get_ftc_action(value: str) -> dict[str, Any]:
    page = await _fetch_html(f"{_FTC_LIST_URL}/{value}")
    if page is None:
        return {}
    title_match = re.search(r"<title>(.*?)</title>", page, re.S)
    desc_match = re.search(r'<meta name="description" content="([^"]+)"', page, re.S)
    title = _strip_tags(title_match.group(1) if title_match else None)
    summary = _as_text(html.unescape(desc_match.group(1)) if desc_match else None)
    if not title:
        return {}
    return {
        "agency": "ftc",
        "id": f"ftc:{value}",
        "title": title,
        "summary": summary,
        "defendants": [_ftc_company_from_title(title)] if _ftc_company_from_title(title) else [],
        "penalties": [],
        "url": f"{_FTC_LIST_URL}/{value}",
    }
