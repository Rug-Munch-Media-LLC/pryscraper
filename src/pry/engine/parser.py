"""Pry — document parser for PDF, DOCX, images, CSV, JSON, HTML.
Uses asyncio subprocess for CPU-bound OCR to avoid blocking the event loop.
Temp files are always cleaned up in finally blocks.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

import asyncio
import contextlib
import io
import os
import tempfile
from pathlib import Path
from typing import Any


class DocumentParser:
    """Parse PDFs, DOCX, images, and other document formats to clean text.
    CPU-bound operations (OCR, PDF parsing) run in executor threads."""

    async def parse(self, url: str, timeout_s: int = 60) -> dict[str, Any]:
        import httpx

        from pry.engine.fetch_guard import guard_get

        # SSRF guard: ``url`` is the caller's request body (``POST /v1/parse``),
        # so it is validated before the first request AND every redirect hop is
        # re-validated by guard_get. ``follow_redirects`` therefore stays False
        # on the client — safe_get follows redirects itself so each Location can
        # be re-checked; leaving it True here would follow them unvalidated.
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout_s)) as client:
            resp = await guard_get(client, url, timeout=timeout_s)
            resp.raise_for_status()
            content = resp.content
            content_type = resp.headers.get("content-type", "")
            filename = Path(url).name.lower()

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._parse_bytes, content, content_type, filename)

    def _parse_bytes(self, data: bytes, content_type: str, filename: str = "") -> dict[str, Any]:
        if filename.endswith(".pdf") or "pdf" in content_type:
            return self._parse_pdf(data)
        elif filename.endswith(".docx") or "word" in content_type:
            return self._parse_docx(data)
        elif filename.endswith((".md", ".markdown")) or "markdown" in content_type:
            return {
                "text": data.decode("utf-8", errors="replace"),
                "format": "markdown",
                "pages": 1,
            }
        elif filename.endswith(".csv") or "csv" in content_type:
            return {"text": data.decode("utf-8", errors="replace"), "format": "csv", "pages": 1}
        elif filename.endswith(".json") or "json" in content_type:
            return {"text": data.decode("utf-8", errors="replace"), "format": "json", "pages": 1}
        elif filename.endswith((".html", ".htm")) or "html" in content_type:
            import trafilatura

            text = data.decode("utf-8", errors="replace")
            extracted = trafilatura.extract(text, output_format="markdown")
            return {"text": extracted or text[:500000], "format": "html", "pages": 1}
        elif (
            filename.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp")) or "image" in content_type
        ):
            return self._parse_image(data)
        elif filename.endswith(".txt") or "text" in content_type:
            return {"text": data.decode("utf-8", errors="replace"), "format": "text", "pages": 1}
        else:
            try:
                text = data.decode("utf-8", errors="replace")
                return {"text": text[:500000], "format": "unknown", "pages": 1}
            except UnicodeDecodeError:
                return {
                    "text": f"[Binary file: {filename}, {len(data)} bytes]",
                    "format": "binary",
                    "pages": 0,
                }

    def _parse_pdf(self, data: bytes) -> dict[str, Any]:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        pages = []
        for page in reader.pages:
            text = page.extract_text()
            if text:
                pages.append(text)
        pdf_metadata = reader.metadata
        return {
            "text": "\n\n".join(pages),
            "format": "pdf",
            "pages": len(pages),
            "metadata": {
                "title": (pdf_metadata.get("/Title", "") if pdf_metadata else "") or "",
                "author": (pdf_metadata.get("/Author", "") if pdf_metadata else "") or "",
            },
        }

    def _parse_docx(self, data: bytes) -> dict[str, Any]:
        from docx import Document

        doc = Document(io.BytesIO(data))
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        return {"text": "\n\n".join(paragraphs), "format": "docx", "pages": 1}

    def _parse_image(self, data: bytes) -> dict[str, Any]:
        """OCR via tesseract. Temp file cleaned up in finally block."""
        fname = None
        try:
            from PIL import Image

            img = Image.open(io.BytesIO(data))
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
                img.save(f, format="PNG")
                fname = f.name
            result = __import__("subprocess").run(
                ["tesseract", fname, "stdout", "--oem", "1", "-l", "eng"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            return {"text": result.stdout, "format": "image", "pages": 1}
        except OSError as e:
            return {"text": f"[Image OCR failed: {e}]", "format": "image", "pages": 0}
        finally:
            if fname and os.path.exists(fname):
                with contextlib.suppress(OSError):
                    os.unlink(fname)
