"""Single SEC filing lookup with archive-directory enrichment."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

import logging
from typing import Any

from datasets.legal_docs.sec_filings.identifiers import (
    _ARCHIVES_URL,
    _accession_plain,
    _as_text,
    _cik_to_plain,
)
from datasets.legal_docs.sec_filings.search import _fts_hits, _map_filing_hit
from datasets.legal_docs.sec_filings.transport import _fetch_json

logger = logging.getLogger(__name__)


async def get_filing(accession_no: str) -> dict[str, Any]:
    """Look up one SEC filing by accession number; never raises."""
    try:
        return await _get_filing(accession_no)
    except Exception:
        logger.exception("legal_sec_get_filing_crashed", extra={"accession_no": accession_no})
        return {}


async def _get_filing(accession_no: str) -> dict[str, Any]:
    accession_no = accession_no.strip()
    if not accession_no:
        return {}
    hits = await _fts_hits({"q": accession_no})
    hit = next(
        (candidate for candidate in hits if _as_text(candidate.get("adsh")) == accession_no),
        None,
    )
    if hit is None and hits:
        hit = hits[0]
    if hit is None:
        return {}
    record = _map_filing_hit(hit, None)
    cik = record.get("cik")
    if not cik:
        return record
    index_url = _ARCHIVES_URL.format(
        cik=_cik_to_plain(cik),
        accession_no_dashes=_accession_plain(accession_no),
    )
    index = await _fetch_json(f"{index_url}index.json")
    if isinstance(index, dict):
        raw_directory = index.get("directory")
        directory = raw_directory if isinstance(raw_directory, dict) else {}
        items = directory.get("item")
        if isinstance(items, list):
            record["files"] = [
                item.get("name") for item in items if isinstance(item, dict) and item.get("name")
            ]
        record["filing_index"] = f"{index_url}index.json"
    return record
