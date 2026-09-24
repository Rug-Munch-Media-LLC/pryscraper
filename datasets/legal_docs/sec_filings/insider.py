"""SEC Form 4 insider-trade retrieval and owner enrichment."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

import logging
from typing import Any

from datasets.legal_docs.sec_filings.identifiers import _as_text, _document_url
from datasets.legal_docs.sec_filings.search import _fts_hits
from datasets.legal_docs.sec_filings.tickers import _cik_for_ticker
from datasets.legal_docs.sec_filings.transport import _fetch_json

logger = logging.getLogger(__name__)
_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"


async def insider_trades(ticker: str, limit: int = 20) -> list[dict[str, Any]]:
    """Return recent Form 4 filings for a ticker; never raises."""
    try:
        return await _insider_trades(ticker, limit)
    except Exception:
        logger.exception("legal_sec_insider_crashed", extra={"ticker": ticker})
        return []


async def _insider_trades(ticker: str, limit: int) -> list[dict[str, Any]]:
    ticker = ticker.strip()
    if not ticker:
        return []
    cik = await _cik_for_ticker(ticker)
    if not cik:
        return []
    payload = await _fetch_json(_SUBMISSIONS_URL.format(cik=cik))
    if not isinstance(payload, dict):
        return []
    filings = payload.get("filings")
    recent = filings.get("recent") if isinstance(filings, dict) else payload.get("recent")
    if not isinstance(recent, dict):
        return []
    forms = recent.get("form")
    if not isinstance(forms, list):
        return []
    accessions = recent.get("accessionNumber")
    primaries = recent.get("primaryDocument")
    filing_dates = recent.get("filingDate")
    report_dates = recent.get("reportDate")
    rows: list[dict[str, Any]] = []
    for index, form in enumerate(forms):
        if str(form).strip() != "4":
            continue
        if len(rows) >= max(1, min(int(limit), 100)):
            break
        accession = (
            _as_text(accessions[index])
            if isinstance(accessions, list) and index < len(accessions)
            else None
        )
        primary = (
            _as_text(primaries[index])
            if isinstance(primaries, list) and index < len(primaries)
            else None
        )
        if not accession:
            continue
        filer_cik = accession[:10]
        rows.append(
            {
                "ticker": ticker.upper(),
                "cik": cik,
                "filer_cik": filer_cik,
                "company_name": _as_text(payload.get("name")),
                "owner": None,
                "form_type": "4",
                "filing_date": _as_text(filing_dates[index])
                if isinstance(filing_dates, list) and index < len(filing_dates)
                else None,
                "report_date": _as_text(report_dates[index])
                if isinstance(report_dates, list) and index < len(report_dates)
                else None,
                "accession_number": accession,
                "primary_document": primary,
                "document_url": _document_url(filer_cik, accession, primary) if primary else None,
                "source": "sec_edgar",
            }
        )
    if not rows:
        return []
    owners = await _owners_by_accession(ticker, cik)
    for row in rows:
        row["owner"] = owners.get(row["accession_number"] or "")
    return rows


async def _owners_by_accession(ticker: str, cik: str) -> dict[str, str]:
    """Map accession numbers to reporting-owner display names."""
    hits = await _fts_hits({"q": ticker.upper(), "ciks": cik, "forms": "4", "page_size": 100})
    owners: dict[str, str] = {}
    for source in hits:
        accession = _as_text(source.get("adsh"))
        names = source.get("display_names")
        if accession and isinstance(names, list) and names:
            owners[accession] = str(names[0])
    return owners
