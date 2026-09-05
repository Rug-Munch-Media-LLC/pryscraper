"""Parsers and normalizers for docket sources.

Maps CourtListener v4 docket objects (list, detail, RECAP search hits) and
signature-parsed Justia / NY eCourts HTML onto the canonical docket record.

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
from urllib.parse import quote

from datasets.legal_docs.dockets_http import _JUSTIA_BASE, _NY_ECOURTS_URL


def _as_text(value: Any) -> str | None:
    """Coerce a JSON value to str/None ('' -> None)."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _as_int(value: Any) -> int | None:
    """Coerce a JSON value to int/None."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _map_docket(raw: dict[str, Any]) -> dict[str, Any]:
    """Map a CourtListener v4 docket object onto the canonical record."""
    docket_id = _as_int(raw.get("id"))
    url = f"https://www.courtlistener.com/docket/{docket_id}/" if docket_id else None
    return {
        "id": docket_id,
        "case_name": _as_text(raw.get("case_name")),
        "docket_number": _as_text(raw.get("docket_number")),
        "court": _as_text(raw.get("court")),
        "date_filed": _as_text(raw.get("date_filed")),
        "date_terminated": _as_text(raw.get("date_terminated")),
        "nature_of_suit": _as_text(raw.get("nature_of_suit")),
        "cause": _as_text(raw.get("cause")),
        "url": url,
        "source": "courtlistener",
    }


def _map_docket_detail(raw: dict[str, Any]) -> dict[str, Any]:
    """Map a full CourtListener v4 docket object (detail view) — superset of :func:`_map_docket`."""
    record = _map_docket(raw)
    record.update(
        {
            "description": _as_text(raw.get("description")),
            "jury_demand": _as_text(raw.get("jury_demand")),
            "jurisdiction_type": _as_text(raw.get("jurisdiction_type")),
            "date_argued": _as_text(raw.get("date_argued")),
            "date_reargued": _as_text(raw.get("date_reargued")),
            "date_last_filing": _as_text(raw.get("date_last_filing")),
            "appeal_from": _as_text(raw.get("appeal_from")),
            "panel": _as_text(raw.get("panel")),
        }
    )
    return record


def _map_recap(raw: dict[str, Any]) -> dict[str, Any]:
    """Map a CourtListener v4 search-API docket hit (RECAP archive) onto the canonical record.

    The ``/search/`` endpoint uses camelCase field names and returns a
    ``source`` facet (``RECAP`` / ``PACER``) instead of the docket's own
    fields; normalize both naming conventions here.
    """
    docket_id = _as_int(raw.get("id"))
    url = _as_text(raw.get("absoluteURL"))
    if not url and docket_id:
        url = f"https://www.courtlistener.com/docket/{docket_id}/"
    return {
        "id": docket_id,
        "case_name": _as_text(raw.get("caseName") or raw.get("case_name")),
        "docket_number": _as_text(raw.get("docketNumber") or raw.get("docket_number")),
        "court": _as_text(raw.get("court") or raw.get("court_id")),
        "date_filed": _as_text(raw.get("dateFiled") or raw.get("date_filed")),
        "date_terminated": _as_text(raw.get("dateTerminated") or raw.get("date_terminated")),
        "nature_of_suit": _as_text(raw.get("natureOfSuit") or raw.get("suitNature")),
        "cause": _as_text(raw.get("cause")),
        "url": url,
        "source": "recap",
    }


def _strip_tags(text: str) -> str:
    """Strip HTML tags into plain text (Justia scrape helper)."""
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


# Justia docket search results are signature-parsed (no anti-bot JSON); the
# page may change layout, in which case extraction degrades to [].
_JUSTIA_SEARCH_RE = re.compile(
    r'<a\s+href="(/docket/[^"]+)"[^>]*>(.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)
_JUSTIA_BLOCK_RE = re.compile(
    r'<div[^>]*class="[^"]*(?:case-block|case-info|docket)[^"]*"[^>]*>(.*?)</div>',
    re.IGNORECASE | re.DOTALL,
)
_JUSTIA_FIELD_RE = {
    # A capitalized phrase ending in Court/Circuit/District, optionally
    # "… of <place>" (e.g. "Southern District of New York").
    "court": re.compile(r"((?:[A-Z][A-Za-z]+ ){1,4}(?:Court|Circuit|District)(?: of [A-Za-z ]+)?)"),
    "docket_number": re.compile(r"(\d{1,2}:\d{2}-[a-z]{2}-\d{3,5})", re.IGNORECASE),
    "date_filed": re.compile(r"\b(\d{4}-\d{2}-\d{2})\b"),
}
_JUSTIA_H1_RE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.IGNORECASE | re.DOTALL)
_JUSTIA_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)


def _justia_url(link: str) -> str:
    """Resolve a Justia docket link to an absolute URL."""
    if link.startswith("http"):
        return link
    return f"{_JUSTIA_BASE}{link}"


def _justia_docket_id(url: str) -> str | None:
    """Last path segment of a Justia docket URL (used as a stable id)."""
    tail = url.rstrip("/").rsplit("/", 1)[-1]
    return tail or None


def _map_justia_search(
    name: str,
    link: str,
    block_text: str,
) -> dict[str, Any]:
    """Build a canonical record from a Justia search-result block."""
    url = _justia_url(link)
    docket_number = None
    court = None
    date_filed = None
    # Run field regexes over the tag-stripped block text so court names are
    # not matched inside href slugs (e.g. "...-southern-district-court-...").
    clean = _strip_tags(block_text)
    match = _JUSTIA_FIELD_RE["docket_number"].search(clean)
    if match:
        docket_number = match.group(1)
    match = _JUSTIA_FIELD_RE["court"].search(clean)
    if match:
        court = _strip_tags(match.group(1))
    match = _JUSTIA_FIELD_RE["date_filed"].search(clean)
    if match:
        date_filed = match.group(1)
    return {
        "id": _justia_docket_id(url),
        "case_name": _strip_tags(name),
        "docket_number": docket_number,
        "court": court,
        "date_filed": date_filed,
        "date_terminated": None,
        "nature_of_suit": None,
        "cause": None,
        "url": url,
        "source": "justia",
    }


def _parse_justia_search(html_text: str, limit: int) -> list[dict[str, Any]]:
    """Signature-parse a Justia dockets search page into canonical records."""
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    # Prefer per-result blocks; fall back to bare link+text pairs.
    blocks = _JUSTIA_BLOCK_RE.findall(html_text) or [
        f'<a href="{link}">{name}</a>' for link, name in _JUSTIA_SEARCH_RE.findall(html_text)
    ]
    for block in blocks:
        if len(records) >= limit:
            break
        match = _JUSTIA_SEARCH_RE.search(block)
        if not match:
            continue
        link, name = match.group(1), match.group(2)
        if not name or not link:
            continue
        url = _justia_url(link)
        if url in seen:
            continue
        seen.add(url)
        record = _map_justia_search(name, link, block)
        if record["case_name"]:
            records.append(record)
    return records[:limit]


def _parse_justia_docket(html_text: str, slug: str) -> dict[str, Any]:
    """Signature-parse a Justia docket page for docket metadata.

    Best-effort: extracts case name (h1/title), docket number, court and
    the earliest date found. Fields Justia does not expose are left ``None``.
    """
    name: str | None = None
    match = _JUSTIA_H1_RE.search(html_text)
    if match:
        name = _strip_tags(match.group(1))
    if not name:
        match = _JUSTIA_TITLE_RE.search(html_text)
        if match:
            title = _strip_tags(match.group(1))
            name = title.split(" - ")[0] if title else None
    docket_number = None
    match = _JUSTIA_FIELD_RE["docket_number"].search(html_text)
    if match:
        docket_number = match.group(1)
    court = None
    match = _JUSTIA_FIELD_RE["court"].search(html_text)
    if match:
        court = _strip_tags(match.group(1))
    date_filed = None
    match = _JUSTIA_FIELD_RE["date_filed"].search(html_text)
    if match:
        date_filed = match.group(1)
    url = f"{_JUSTIA_BASE}/docket/{slug}"
    return {
        "id": slug,
        "case_name": name,
        "docket_number": docket_number,
        "court": court,
        "date_filed": date_filed,
        "date_terminated": None,
        "nature_of_suit": None,
        "cause": None,
        "url": url,
        "description": None,
        "jury_demand": None,
        "jurisdiction_type": None,
        "date_argued": None,
        "date_reargued": None,
        "date_last_filing": None,
        "appeal_from": None,
        "panel": None,
        "source": "justia",
    }


# NY eCourts civil case search (https://iapps.courts.state.ny.us/webcivil/).
# The results page renders a table of matching cases; rows are signature-
# parsed (the page may change layout, in which case extraction degrades to
# []). An index number looks like "651256/2023".
_NY_ECOURTS_ROW_RE = re.compile(
    r'<tr[^>]*class="[^"]*data[^"]*"[^>]*>(.*?)</tr>', re.IGNORECASE | re.DOTALL
)
_NY_ECOURTS_CELL_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.IGNORECASE | re.DOTALL)
_NY_INDEX_RE = re.compile(r"\b(\d{3,6}/\d{4})\b")
# The webcivil civil-case search form fields (documented by NY courts; the
# query is placed in ``defendant`` for free-text name search and in
# ``index_number`` for the docket lookup path).
_NY_ECOURTS_FORM: dict[str, str] = {
    "param": "primary",
    "idx": "0",
    "court_type": "CIV",
    "court_type_1": "ALL",
    "case_type": "Civil",
    "case_status": "ALL",
    "filing_date": "",
    "filing_date1": "",
    "docket_number": "",
    "plaintiff": "",
    "defendant": "",
    "judge": "",
    "index_number": "",
    "submit": "Search",
}


def _ny_date(value: str | None) -> str | None:
    """Normalize a NY eCourts ``MM/DD/YYYY`` filing date to ``YYYY-MM-DD``."""
    if not value:
        return None
    text = value.strip()
    match = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})$", text)
    if match:
        month, day, year = match.groups()
        return f"{year}-{int(month):02d}-{int(day):02d}"
    return text or None


def _parse_ny_ecourts(html_text: str, limit: int) -> list[dict[str, Any]]:
    """Signature-parse the NY eCourts civil case-search results table.

    Each result row exposes the index number, case type, filing date, judge,
    plaintiff(s) and defendant(s). Parsing is best-effort: layout changes
    degrade to ``[]``.
    """
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in _NY_ECOURTS_ROW_RE.findall(html_text):
        if len(records) >= limit:
            break
        cells = [
            cell
            for cell in (_strip_tags(cell) for cell in _NY_ECOURTS_CELL_RE.findall(row))
            if cell
        ]
        index_number: str | None = None
        idx = 0
        for pos, cell in enumerate(cells):
            match = _NY_INDEX_RE.search(cell)
            if match:
                index_number = match.group(1)
                idx = pos
                break
        if not index_number or index_number in seen:
            continue
        seen.add(index_number)
        # eCourts rows are: index number, case type, filing date, [judge],
        # plaintiff(s), defendant(s). The judge cell is often "&nbsp;" and
        # gets dropped, so anchor on the index cell for type/date and take
        # plaintiff/defendant from the last two cells.
        case_type = cells[idx + 1] if idx + 1 < len(cells) else None
        filing_date = _ny_date(cells[idx + 2] if idx + 2 < len(cells) else None)
        plaintiff = cells[-2] if len(cells) >= 5 else None
        defendant = cells[-1] if len(cells) >= 5 else None
        case_name = defendant or plaintiff or f"NY eCourts docket {index_number}"
        records.append(
            {
                "id": index_number,
                "case_name": case_name,
                "docket_number": index_number,
                "court": "New York State Supreme Court (Civil)",
                "date_filed": filing_date,
                "date_terminated": None,
                "nature_of_suit": case_type,
                "cause": None,
                "url": f"{_NY_ECOURTS_URL}?index_number={quote(index_number)}",
                "source": "state_ny",
            }
        )
    return records[:limit]
