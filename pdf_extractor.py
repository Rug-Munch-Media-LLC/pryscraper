"""Pry — PDF Table Extraction using multiple methods.
Extracts structured tables from PDF documents (financial reports, invoices, etc.)
Uses pdfplumber, camelot, and pdfminer as fallback methods."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

import io
import logging
import os
from contextlib import suppress
from typing import Any

logger = logging.getLogger(__name__)

# Try different PDF libraries
_pdfplumber: bool = False
_camelot: bool = False
_pdfminer: bool = False

try:
    import pdfplumber  # noqa: F401

    _pdfplumber = True
except ImportError:
    pass

try:
    import camelot  # noqa: F401

    _camelot = True
except ImportError:
    pass

try:
    from pdfminer.high_level import extract_text  # noqa: F401

    _pdfminer = True
except ImportError:
    pass


class PDFTableExtractor:
    """Extract tables from PDF documents using multiple methods."""

    def __init__(self, prefer_method: str = "pdfplumber"):
        self.prefer_method = prefer_method

    def extract(self, pdf_bytes: bytes, method: str = "") -> dict[str, Any]:
        """Extract tables from a PDF document.

        Returns: {tables: [...], text: "...", page_count: N, method_used: "..."}
        """
        method = method or self.prefer_method

        # Try preferred method first
        if method == "pdfplumber" and _pdfplumber:
            return self._extract_pdfplumber(pdf_bytes)
        if method == "camelot" and _camelot:
            return self._extract_camelot(pdf_bytes)
        if method == "pdfminer" and _pdfminer:
            return self._extract_pdfminer(pdf_bytes)

        # Fallback chain
        for fallback in ["pdfplumber", "camelot", "pdfminer"]:
            if fallback == "pdfplumber" and _pdfplumber:
                return self._extract_pdfplumber(pdf_bytes)
            if fallback == "camelot" and _camelot:
                return self._extract_camelot(pdf_bytes)
            if fallback == "pdfminer" and _pdfminer:
                return self._extract_pdfminer(pdf_bytes)

        return {
            "error": "No PDF library available. Install pdfplumber, camelot, or pdfminer.six.",
            "tables": [],
            "text": "",
        }

    def _extract_pdfplumber(self, pdf_bytes: bytes) -> dict[str, Any]:
        import pdfplumber

        tables: list[dict[str, Any]] = []
        text = ""
        page_count = 0
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages:
                page_count += 1
                text += (page.extract_text() or "") + "\n"
                for table in page.extract_tables():
                    if table:
                        tables.append(
                            {
                                "page": page.page_number,
                                "rows": table,
                                "row_count": len(table),
                                "col_count": len(table[0]) if table else 0,
                            }
                        )
        return {
            "tables": tables,
            "text": text,
            "page_count": page_count,
            "table_count": len(tables),
            "method_used": "pdfplumber",
        }

    def _extract_camelot(self, pdf_bytes: bytes) -> dict[str, Any]:
        import camelot

        tables: list[dict[str, Any]] = []
        tmp_path = "/tmp/_pry_pdf.pdf"
        try:
            with open(tmp_path, "wb") as f:
                f.write(pdf_bytes)
            camelot_tables = camelot.read_pdf(tmp_path, pages="all")
            for i, table in enumerate(camelot_tables):
                tables.append(
                    {
                        "page": i + 1,
                        "rows": table.df.values.tolist(),
                        "row_count": len(table.df),
                        "col_count": len(table.df.columns),
                        "accuracy": table.accuracy,
                        "whitespace": table.whitespace,
                    }
                )
        finally:
            with suppress(OSError):
                os.unlink(tmp_path)
        return {
            "tables": tables,
            "table_count": len(tables),
            "method_used": "camelot",
        }

    def _extract_pdfminer(self, pdf_bytes: bytes) -> dict[str, Any]:
        from pdfminer.high_level import extract_text

        text = extract_text(io.BytesIO(pdf_bytes))
        return {"tables": [], "text": text, "method_used": "pdfminer"}

    def is_available(self) -> bool:
        return any([_pdfplumber, _camelot, _pdfminer])
