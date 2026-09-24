"""SEC EDGAR full-text filing search and result mapping."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

import logging
from typing import Any

from datasets.legal_docs.sec_filings.identifiers import (
    _as_text,
    _cik_to_padded,
    _document_url,
)
from datasets.legal_docs.sec_filings.tickers import _cik_for_ticker
from datasets.legal_docs.sec_filings.transport import _fetch_json

logger = logging.getLogger(__name__)
_FTS_URL = "https://efts.sec.gov/LATEST/search-index"


async def _fts_hits(params: dict[str, Any]) -> list[dict[str, Any]]:
    """Run an EDGAR full-text search and return hit sources."""
    payload = await _fetch_json(_FTS_URL, params)
    if not isinstance(payload, dict):
        return []
    hits = payload.get("hits")
    if not isinstance(hits, dict):
        return []
    hit_list = hits.get("hits")
    if not isinstance(hit_list, list):
        return []
    out: list[dict[str, Any]] = []
    for hit in hit_list:
        if not isinstance(hit, dict):
            continue
        source = hit.get("_source")
        if isinstance(source, dict):
            merged = dict(source)
            if "_id" not in merged:
                merged["_id"] = hit.get("_id")
            out.append(merged)
    return out


def _map_filing_hit(source: dict[str, Any], ticker_hint: str | None) -> dict[str, Any]:
    """Map an EDGAR hit onto the canonical filing record."""
    ciks = source.get("ciks") or []
    cik = _cik_to_padded(ciks[0]) if isinstance(ciks, list) and ciks else None
    accession = _as_text(source.get("adsh"))
    documents: list[dict[str, Any]] = []
    if accession and cik:
        hit_id = source.get("_id") or ""
        filename = hit_id.split(":", 1)[1] if ":" in hit_id else None
        filename = filename or _as_text(source.get("file_type"))
        if filename:
            documents.append(
                {
                    "type": _as_text(source.get("form")) or "filing",
                    "url": _document_url(cik, accession, filename),
                }
            )
    return {
        "accession_number": accession,
        "filing_date": _as_text(source.get("file_date")),
        "form_type": _as_text(source.get("form")),
        "ticker": (ticker_hint or "").upper() or None,
        "cik": cik,
        "company_names": source.get("display_names")
        if isinstance(source.get("display_names"), list)
        else [],
        "items": source.get("items") if isinstance(source.get("items"), list) else [],
        "documents": documents,
        "source": "sec_edgar",
    }


async def search_filings(
    ticker: str, form_type: str = "8-K", limit: int = 20
) -> list[dict[str, Any]]:
    """Search SEC EDGAR filings for a ticker; never raises."""
    try:
        return await _search_filings(ticker, form_type, limit)
    except Exception:
        logger.exception(
            "legal_sec_search_crashed",
            extra={"ticker": ticker, "form_type": form_type},
        )
        return []


async def _search_filings(ticker: str, form_type: str, limit: int) -> list[dict[str, Any]]:
    ticker = ticker.strip()
    if not ticker:
        return []
    cik = await _cik_for_ticker(ticker)
    params: dict[str, Any] = {
        "q": ticker.upper(),
        "forms": form_type.strip() or "8-K",
        "page_size": max(1, min(int(limit), 100)),
    }
    if cik:
        params["ciks"] = cik
    hits = await _fts_hits(params)
    return [_map_filing_hit(hit, ticker) for hit in hits[: max(1, min(int(limit), 100))]]
