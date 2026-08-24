"""Pry — Image OCR using Tesseract.
Extract text from images on web pages. Uses pytesseract + Pillow."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

import io
import logging
import os
from typing import Any, ClassVar

import httpx

logger = logging.getLogger(__name__)

try:
    import pytesseract
    from PIL import Image

    _has_tesseract = True
except ImportError:
    _has_tesseract = False


class ImageOCR:
    """Extract text from images using Tesseract OCR."""

    SUPPORTED_LANGUAGES: ClassVar[list[str]] = [
        "eng",
        "chi_sim",
        "chi_tra",
        "spa",
        "fra",
        "deu",
        "ita",
        "por",
        "rus",
        "jpn",
        "kor",
        "ara",
    ]

    def __init__(self, language: str = "eng"):
        self.language = language if language in self.SUPPORTED_LANGUAGES else "eng"

    def extract_from_bytes(self, image_bytes: bytes, config: str = "") -> dict[str, Any]:
        """Extract text from image bytes."""
        if not _has_tesseract:
            return {
                "success": False,
                "error": "pytesseract not installed. Run: pip install pytesseract pillow",
            }
        try:
            img = Image.open(io.BytesIO(image_bytes))
            text = pytesseract.image_to_string(img, lang=self.language, config=config)
            data = pytesseract.image_to_data(
                img, lang=self.language, output_type=pytesseract.Output.DICT
            )
            confidences = [c for c in data["conf"] if isinstance(c, int) and 0 <= c <= 100]
            avg_confidence = round(sum(confidences) / len(confidences), 1) if confidences else 0
            return {
                "success": True,
                "text": text.strip(),
                "confidence": avg_confidence,
                "word_count": len(text.split()),
                "language": self.language,
            }
        except OSError as e:
            return {"success": False, "error": str(e)[:200]}

    def extract_from_file(self, image_path: str) -> dict[str, Any]:
        """Extract text from an image file."""
        if not os.path.exists(image_path):
            return {"success": False, "error": f"File not found: {image_path}"}
        with open(image_path, "rb") as f:
            return self.extract_from_bytes(f.read())

    async def extract_from_url(self, url: str) -> dict[str, Any]:
        """Download image from URL and extract text."""
        from pry.api.client import get_client

        client = await get_client()
        try:
            resp = await client.get(url, timeout=30)
            if resp.is_success:
                return self.extract_from_bytes(resp.content)
        except (httpx.HTTPError, httpx.RequestError) as e:
            return {"success": False, "error": str(e)[:200]}
        return {"success": False, "error": "Failed to download image"}

    def is_available(self) -> bool:
        return _has_tesseract
