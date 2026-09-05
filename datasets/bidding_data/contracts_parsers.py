"""Mappers: raw source payloads -> canonical contract records.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import re
from typing import Any

from datasets.bidding_data.contracts_common import (
    _FEDCONNECT_BASE,
    _as_text,
    _canonical_type,
)

_FEDCONNECT_LINK_RE = re.compile(r'PublicSearch\.aspx\?doc=([^"&\s]+)">([^<]+)</a>', re.IGNORECASE)
_FEDCONNECT_TITLE_RE = re.compile(r"<title>([^<]+)</title>", re.IGNORECASE | re.DOTALL)


def _sam_map(raw: dict[str, Any]) -> dict[str, Any]:
    """Map a SAM.gov Opportunities v2 object onto the canonical record."""
    notice_id = _as_text(raw.get("noticeId"))
    url = _as_text(raw.get("url"))
    if not url and notice_id:
        url = f"https://sam.gov/opp/{notice_id}/view"
    notice_type = _as_text(raw.get("typeOfNotice")) or _as_text(raw.get("noticeType"))
    return {
        "id": f"sam:{notice_id}" if notice_id else None,
        "title": _as_text(raw.get("title")),
        "agency": _as_text(raw.get("agency")),
        "type": _canonical_type(notice_type),
        "notice_type": notice_type,
        "naics": _as_text(raw.get("naicsCode")),
        "set_aside": _as_text(raw.get("setAside"))
        or _as_text(raw.get("typeOfSetAsideDescription")),
        "due_date": _as_text(raw.get("responseDeadLine")) or _as_text(raw.get("responseDate")),
        "award_date": _as_text(raw.get("awardDate")),
        "value": _as_text(raw.get("estimatedValue")),
        "url": url,
        "source": "sam_gov",
    }


def _ted_map(raw: dict[str, Any]) -> dict[str, Any] | None:
    """Map a TED v3 notice search result onto the canonical record."""
    pub = _as_text(raw.get("publicationNumber"))
    if not pub:
        return None
    buyer = raw.get("buyer")
    buyer_name = _as_text(buyer.get("name")) if isinstance(buyer, dict) else None
    notice_type = _as_text(raw.get("noticeType")) or _as_text(raw.get("noticeTypeName"))
    value = raw.get("value")
    if isinstance(value, dict):
        value = value.get("value")
    return {
        "id": f"ted:{pub}",
        "title": _as_text(raw.get("title")) or _as_text(raw.get("noticeTitle")),
        "agency": buyer_name,
        "type": _canonical_type(notice_type),
        "notice_type": notice_type,
        "naics": None,
        "set_aside": None,
        "due_date": _as_text(raw.get("deadlineDate")) or _as_text(raw.get("tenderDeadline")),
        "award_date": _as_text(raw.get("awardDate")),
        "value": _as_text(value),
        "url": f"https://ted.europa.eu/en/notice/-/detail/{pub}",
        "source": "ted",
    }


def _ny_map(raw: dict[str, Any]) -> dict[str, Any]:
    """Map an NYSCR record onto the canonical record."""
    nid = _as_text(raw.get("id"))
    return {
        "id": f"ny:{nid}" if nid else None,
        "title": _as_text(raw.get("title")),
        "agency": _as_text(raw.get("agencyName")) or _as_text(raw.get("agency")),
        "type": "solicitation",
        "notice_type": "Contract Notice",
        "naics": _as_text(raw.get("naicsCode")),
        "set_aside": None,
        "due_date": _as_text(raw.get("dueDate")) or _as_text(raw.get("bidDueDate")),
        "award_date": None,
        "value": _as_text(raw.get("estimatedValue")),
        "url": _as_text(raw.get("url"))
        or (f"https://www.nycr.ny.gov/api/contracts/{nid}" if nid else None),
        "source": "ny_contract_reporter",
    }


def _fedconnect_map(doc: str, title: str) -> dict[str, Any]:
    """Build a canonical record from a FedConnect document link."""
    return {
        "id": f"fedconnect:{doc}",
        "title": title.strip() or f"FedConnect opportunity {doc}",
        "agency": None,
        "type": "solicitation",
        "notice_type": "FedConnect Opportunity",
        "naics": None,
        "set_aside": None,
        "due_date": None,
        "award_date": None,
        "value": None,
        "url": f"{_FEDCONNECT_BASE}?doc={doc}",
        "source": "fedconnect",
    }
