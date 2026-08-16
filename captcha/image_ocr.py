"""Pry — OCR-based image CAPTCHA solver.

Uses Tesseract via ``pytesseract`` (default) or EasyOCR when selected by
``PRY_CAPTCHA_OCR_BACKEND``. Images are preprocessed with Pillow
(grayscale -> autocontrast -> threshold -> median denoise) before OCR.

The OCR libraries are imported lazily so this module loads even when
neither backend is installed; in that case ``solve`` returns None
gracefully (flagged for install via the log).
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import asyncio
import base64
import binascii
import logging
import os
from io import BytesIO
from pathlib import Path
from typing import Any

from captcha.base import CaptchaProvider
from captcha.registry import register
from settings import settings

logger = logging.getLogger(__name__)

THRESHOLD = 160
MEDIAN_SIZE = 3


def _normalize_image(image: bytes | str | None) -> bytes | None:
    """Return raw image bytes from bytes, base64 str, data-URL or file path."""
    if image is None:
        return None
    if isinstance(image, bytes):
        return image or None
    text = image.strip()
    if not text:
        return None
    if text.startswith("data:") and "," in text:
        text = text.split(",", 1)[1]
    if os.path.exists(text):
        try:
            return Path(text).read_bytes()
        except OSError:
            return None
    try:
        return base64.b64decode(text) or None
    except (binascii.Error, ValueError):
        return None


def preprocess_image(data: bytes) -> Any | None:
    """Preprocess raw image bytes for OCR.

    Returns a Pillow image (grayscale, contrast-stretched, thresholded and
    denoised) or None if the bytes cannot be decoded.
    """
    try:
        from PIL import Image, ImageFilter, ImageOps
    except ImportError:
        logger.warning("Pillow not installed; cannot preprocess image captcha")
        return None
    try:
        img = Image.open(BytesIO(data)).convert("L")
        img = ImageOps.autocontrast(img)
        img = img.point(lambda p: 255 if p > THRESHOLD else 0)
        return img.filter(ImageFilter.MedianFilter(size=MEDIAN_SIZE))
    except (OSError, ValueError) as exc:
        logger.warning("image preprocess failed: %s", exc)
        return None


def _ocr_tesseract(img: Any) -> str | None:
    try:
        import pytesseract
    except ImportError:
        logger.warning("pytesseract not installed; cannot solve image captcha")
        return None
    try:
        text = pytesseract.image_to_string(img)
    except (pytesseract.TesseractError, OSError, ValueError) as exc:
        logger.warning("tesseract OCR failed: %s", exc)
        return None
    text = (text or "").strip()
    return text or None


def _ocr_easyocr(img: Any) -> str | None:
    try:
        import easyocr
    except ImportError:
        logger.warning("easyocr not installed; cannot solve image captcha")
        return None
    try:
        import numpy as np

        reader = easyocr.Reader(["en"], gpu=False, verbose=False)
        result = reader.readtext(np.array(img), detail=0)
    except (OSError, RuntimeError, ValueError, ImportError) as exc:
        logger.warning("easyocr OCR failed: %s", exc)
        return None
    text = " ".join(str(part) for part in (result or [])).strip()
    return text or None


def ocr_image(img: Any) -> str | None:
    """Run OCR on a preprocessed image using the configured backend."""
    backend = (settings.captcha_ocr_backend or "tesseract").lower()
    if backend == "easyocr":
        return _ocr_easyocr(img)
    if backend == "auto":
        return _ocr_tesseract(img) or _ocr_easyocr(img)
    return _ocr_tesseract(img)


class ImageOcrProvider(CaptchaProvider):
    """Solve image CAPTCHAs via local OCR (no network)."""

    captcha_type = "image"

    async def solve(
        self,
        *,
        image: bytes | str | None = None,
        **_: Any,
    ) -> str | None:
        raw = _normalize_image(image)
        if raw is None:
            return None
        img = preprocess_image(raw)
        if img is None:
            return None
        # OCR is CPU-bound; run it off the event loop.
        return await asyncio.to_thread(ocr_image, img)


register(ImageOcrProvider())
