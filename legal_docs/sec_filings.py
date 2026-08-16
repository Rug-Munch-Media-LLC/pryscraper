"""SEC EDGAR company filings — free Full-Text Search + submissions APIs.

Uses two free, key-less SEC EDGAR endpoints:

* Full-Text Search: ``https://efts.sec.gov/LATEST/search-index?q=...`` —
  full-text search over filing text; supports ``forms`` and ``ciks``
  filters. Returns JSON with ``hits.hits``.
* Company submissions: ``https://data.sec.gov/submissions/CIK##########.json``
  — recent filing index for a company, incl. Form 4 (insider trade) rows.
* Ticker lookup: ``https://www.sec.gov/files/company_tickers.json`` — the
  ~1MB ticker -> CIK mapping (cached in-process, TTL 12h).

SEC requires a descriptive User-Agent — see https://www.sec.gov/os/accessing-edgar-data.
Backoff: 2 retries, exponential (0.4s -> 1.6s).

Contract
--------
* :func:`search_filings` — async, never raises, returns ``list``. Searches
  filings for a ticker by form type (default ``8-K``).
* :func:`get_filing` — async, never raises, returns ``dict``. Looks up one
  filing by accession number (e.g. ``0000320193-24-000005``) and enriches it
  with the filing-directory index.
* :func:`insider_trades` — async, never raises, returns ``list``. Recent
  Form 4 (insider transaction) filings for a ticker.

Result shapes
-------------
``search_filings`` returns a list of:

    {
        "accession_number": "0000320193-24-000005",
        "filing_date": "2024-02-01",
        "form_type": "8-K",
        "ticker": "AAPL",
        "cik": "0000320193",
        "company_names": ["Apple Inc.  (AAPL)  (CIK 0000320193)"],
        "items": ["8.01", "9.01"],
        "documents": [{"type": "8-K", "url": "https://www.sec.gov/Archives/edgar/data/..."}],
        "source": "sec_edgar",
    }

``get_filing`` adds ``primary_document``, ``filing_index`` and ``files``
(when the filing directory ``index.json`` is reachable).

``insider_trades`` returns a list of:

    {
        "ticker": "AAPL",
        "cik": "0000320193",
        "company_name": "Apple Inc.",
        "owner": "SMITH JOHN",           # from FTS display_names when available
        "form_type": "4",
        "filing_date": "2026-08-13",
        "report_date": "2026-08-11",
        "accession_number": "0001140361-26-032884",
        "primary_document": "xslF345X06/form4.xml",
        "document_url": "https://www.sec.gov/Archives/edgar/data/1140361/000114036126032884/xslF345X06/form4.xml",
        "source": "sec_edgar",
    }

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from retry import RetryConfig, async_retry

logger = logging.getLogger(__name__)

_FTS_URL = "https://efts.sec.gov/LATEST/search-index"
_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
_ARCHIVES_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession_no_dashes}/"

_TIMEOUT = httpx.Timeout(20.0)
_RETRY_CONFIG = RetryConfig(
    max_retries=2,
    base_delay=0.4,
    max_delay=1.6,
    retryable_exceptions=(httpx.HTTPError,),
)
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; pryscraper-legal/1.0; +https://git.rugmunch.io/RugMunchMedia/pryscraper)",
    "Accept": "application/json",
}

# Ticker mapping cache (company_tickers.json is ~1MB; refresh 12h).
_TICKERS_CACHE_TTL = 12 * 60 * 60
_TICKERS_CACHE: dict[str, Any] | None = None
_TICKERS_CACHE_TS = 0.0

# Accession normalization helper.
_ACC_NO_DASHES = str.maketrans("", "", "-")


def _cik_to_padded(cik: Any) -> str | None:
    """Zero-pad a CIK (int or str) to 10 digits; None when not numeric."""
    try:
        return str(int(cik)).zfill(10)
    except (TypeError, ValueError):
        return None


def _cik_to_plain(cik: Any) -> str | None:
    """CIK without leading zeros (as used in Archives URL paths)."""
    padded = _cik_to_padded(cik)
    return str(int(padded)) if padded else None


def _as_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _accession_plain(accession: str) -> str:
    """Strip dashes from an accession number (for URL paths)."""
    return accession.translate(_ACC_NO_DASHES)


def _document_url(cik: str, accession: str, filename: str) -> str:
    """Build the canonical SEC filing-directory document URL."""
    plain_cik = _cik_to_plain(cik) or cik
    base = _ARCHIVES_URL.format(cik=plain_cik, accession_no_dashes=_accession_plain(accession))
    return f"{base}{filename}"


async def _fetch_json(url: str, params: dict[str, Any] | None = None) -> Any:
    """GET ``url`` and return parsed JSON (any type) or ``None`` on failure."""

    async def _one() -> Any:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT, headers=_HEADERS, follow_redirects=True
        ) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            return response.json()

    try:
        return await async_retry(_one, config=_RETRY_CONFIG)
    except (httpx.HTTPError, OSError, ValueError):
        return None


# ── Ticker -> CIK mapping (cached) ─────────────────────────────────────
async def _tickers_index() -> dict[str, dict[str, Any]] | None:
    """Load + cache ``company_tickers.json`` (``{ticker: {cik_str, ticker, title}}``)."""
    global _TICKERS_CACHE, _TICKERS_CACHE_TS
    now = time.monotonic()
    if _TICKERS_CACHE is not None and (now - _TICKERS_CACHE_TS) < _TICKERS_CACHE_TTL:
        return _TICKERS_CACHE
    payload = await _fetch_json(_TICKERS_URL)
    if not isinstance(payload, dict):
        return _TICKERS_CACHE  # stale cache is better than nothing; None first call
    index: dict[str, dict[str, Any]] = {}
    for raw in payload.values():
        if not isinstance(raw, dict):
            continue
        ticker = _as_text(raw.get("ticker"))
        if not ticker:
            continue
        index[ticker.upper()] = {
            "cik": _cik_to_padded(raw.get("cik_str")),
            "ticker": ticker,
            "title": _as_text(raw.get("title")),
        }
    if index:
        _TICKERS_CACHE = index
        _TICKERS_CACHE_TS = now
    return index


async def _cik_for_ticker(ticker: str) -> str | None:
    """Resolve a ticker (case-insensitive) to its zero-padded 10-digit CIK."""
    index = await _tickers_index()
    if not index:
        return None
    entry = index.get(ticker.strip().upper())
    return entry.get("cik") if entry else None


# ── FTS helper ─────────────────────────────────────────────────────────
async def _fts_hits(params: dict[str, Any]) -> list[dict[str, Any]]:
    """Run an EDGAR Full-Text Search and return the list of hit sources."""
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
            # Keep the hit-level ``_id`` (``{adsh}:{filename}``) with the
            # source so document URLs can be reconstructed downstream.
            merged = dict(source)
            if "_id" not in merged:
                merged["_id"] = hit.get("_id")
            out.append(merged)
    return out


def _map_filing_hit(source: dict[str, Any], ticker_hint: str | None) -> dict[str, Any]:
    """Map an FTS ``_source`` onto the canonical filing record."""
    ciks = source.get("ciks") or []
    cik = _cik_to_padded(ciks[0]) if isinstance(ciks, list) and ciks else None
    accession = _as_text(source.get("adsh"))
    documents: list[dict[str, Any]] = []
    if accession and cik:
        # Reconstruct the document URL from the filing directory: the FTS
        # ``_id`` is ``{adsh}:{filename}``.
        hit_id = source.get("_id") or ""
        filename = hit_id.split(":", 1)[1] if ":" in hit_id else None
        if not filename:
            filename = _as_text(source.get("file_type"))  # degraded fallback
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


# ── Public API ─────────────────────────────────────────────────────────
async def search_filings(
    ticker: str, form_type: str = "8-K", limit: int = 20
) -> list[dict[str, Any]]:
    """Search SEC EDGAR filings for a ticker by form type.

    Args:
        ticker: Company ticker (case-insensitive).
        form_type: SEC form type to filter by (default ``"8-K"``).
        limit: Max results to return (1-100).

    Returns:
        List of filing records (see module docstring). ``[]`` on failure
        (unknown ticker, network error, bad payload). Never raises.
    """
    try:
        return await _search_filings(ticker, form_type, limit)
    except Exception:
        logger.exception(
            "legal_sec_search_crashed", extra={"ticker": ticker, "form_type": form_type}
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
    # SEC's FTS page_size is not always honored — slice locally so the
    # ``limit`` contract is guaranteed.
    return [_map_filing_hit(h, ticker) for h in hits[: max(1, min(int(limit), 100))]]


async def get_filing(accession_no: str) -> dict[str, Any]:
    """Look up a single SEC filing by accession number.

    Args:
        accession_no: Accession number (e.g. ``"0000320193-24-000005"``).

    Returns:
        Filing record enriched with the filing-directory index, or ``{}`` on
        failure (unknown accession, network error). Never raises.
    """
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
    hit = next((h for h in hits if _as_text(h.get("adsh")) == accession_no), None)
    if hit is None and hits:
        hit = hits[0]  # tolerant: SEC sometimes normalizes the accession form
    if hit is None:
        return {}
    record = _map_filing_hit(hit, None)
    cik = record.get("cik")
    if not cik:
        return record
    # Enrich with the filing-directory index.json (data.sec.gov Archives).
    index_url = _ARCHIVES_URL.format(
        cik=_cik_to_plain(cik), accession_no_dashes=_accession_plain(accession_no)
    )
    index = await _fetch_json(f"{index_url}index.json")
    if isinstance(index, dict):
        directory: dict[Any, Any] = {}
        raw_directory = index.get("directory")
        if isinstance(raw_directory, dict):
            directory = raw_directory
        items = directory.get("item")
        if isinstance(items, list):
            files = [it.get("name") for it in items if isinstance(it, dict) and it.get("name")]
            record["files"] = files
        record["filing_index"] = f"{index_url}index.json"
    return record


async def insider_trades(ticker: str, limit: int = 20) -> list[dict[str, Any]]:
    """Return recent Form 4 (insider transaction) filings for a ticker.

    Uses the company submissions feed (``data.sec.gov/submissions/...``) to
    find Form 4 filings, then enriches them with owner names from the EDGAR
    Full-Text Search ``display_names`` when available.

    Args:
        ticker: Company ticker (case-insensitive).
        limit: Max results to return (1-100).

    Returns:
        List of insider-trade records (see module docstring). ``[]`` on
        failure (unknown ticker, network error). Never raises.
    """
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
    # SEC changed the submissions layout: new schema nests under
    # ``filings.recent``; legacy schema had ``recent`` at the top level.
    recent = payload.get("filings") if isinstance(payload.get("filings"), dict) else payload
    recent = recent.get("recent") if isinstance(recent, dict) else None
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
    for i, form in enumerate(forms):
        if str(form).strip() != "4":
            continue
        if len(rows) >= max(1, min(int(limit), 100)):
            break
        accession = (
            _as_text(accessions[i])
            if isinstance(accessions, list) and i < len(accessions)
            else None
        )
        primary = (
            _as_text(primaries[i]) if isinstance(primaries, list) and i < len(primaries) else None
        )
        if not accession:
            continue
        # The accession prefix is the FILER's zero-padded CIK (for Form 4 the
        # filer is the insider, not the issuer) — use it for the document URL.
        filer_cik = accession[:10]
        rows.append(
            {
                "ticker": ticker.upper(),
                "cik": cik,
                "filer_cik": filer_cik,
                "company_name": _as_text(payload.get("name")),
                "owner": None,
                "form_type": "4",
                "filing_date": _as_text(filing_dates[i])
                if isinstance(filing_dates, list) and i < len(filing_dates)
                else None,
                "report_date": _as_text(report_dates[i])
                if isinstance(report_dates, list) and i < len(report_dates)
                else None,
                "accession_number": accession,
                "primary_document": primary,
                "document_url": _document_url(filer_cik, accession, primary) if primary else None,
                "source": "sec_edgar",
            }
        )
    if not rows:
        return []
    # Enrich owner names from FTS display_names (one extra free call, keyed by accession).
    owners = await _owners_by_accession(ticker, cik)
    for row in rows:
        row["owner"] = owners.get(row["accession_number"] or "")
    return rows


async def _owners_by_accession(ticker: str, cik: str) -> dict[str, str]:
    """Map accession -> reporting-owner display name for Form 4 filings."""
    hits = await _fts_hits({"q": ticker.upper(), "ciks": cik, "forms": "4", "page_size": 100})
    owners: dict[str, str] = {}
    for source in hits:
        accession = _as_text(source.get("adsh"))
        if not accession:
            continue
        names = source.get("display_names")
        if isinstance(names, list) and names:
            owners[accession] = str(names[0])
    return owners
