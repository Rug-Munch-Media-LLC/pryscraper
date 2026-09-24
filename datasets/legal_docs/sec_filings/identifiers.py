"""Identifier normalization and SEC archive URL construction."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

from typing import Any

_ARCHIVES_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession_no_dashes}/"
_ACC_NO_DASHES = str.maketrans("", "", "-")


def _cik_to_padded(cik: Any) -> str | None:
    """Zero-pad a CIK to ten digits; return ``None`` when not numeric."""
    if isinstance(cik, bool):
        return None
    text = str(cik).strip()
    digits = text[1:] if text[:1] in {"+", "-"} else text
    if not digits.isdecimal():
        return None
    return str(int(text)).zfill(10)


def _cik_to_plain(cik: Any) -> str | None:
    """Return a CIK without leading zeros for archive URL paths."""
    padded = _cik_to_padded(cik)
    return str(int(padded)) if padded else None


def _as_text(value: Any) -> str | None:
    """Return stripped text, or ``None`` for empty values."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _accession_plain(accession: str) -> str:
    """Strip dashes from an accession number for URL paths."""
    return accession.translate(_ACC_NO_DASHES)


def _document_url(cik: str, accession: str, filename: str) -> str:
    """Build the canonical SEC filing-directory document URL."""
    plain_cik = _cik_to_plain(cik) or cik
    base = _ARCHIVES_URL.format(
        cik=plain_cik,
        accession_no_dashes=_accession_plain(accession),
    )
    return f"{base}{filename}"
