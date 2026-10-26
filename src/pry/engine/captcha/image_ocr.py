"""Pry — T3: local OCR for text/image CAPTCHAs, offline.

The engine is ONNX (``ddddocr``-compatible model layout: one model file, a
``predict(bytes) -> str`` call), executed through onnxruntime on CPU. Both the
runtime and the model are optional: absent either one, ``capability()`` is
False and the rung is skipped with ``unavailable.model`` — never a slow crash
in the middle of a fetch.

Images are normalised first (bytes / base64 / data-URL / path) and
preprocessed with Pillow, mirroring the previous backend contract.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

import asyncio
import base64
import binascii
import logging
import os
from io import BytesIO
from pathlib import Path
from typing import Any

from pry.engine.captcha.base import CaptchaProvider
from pry.engine.captcha.registry import register

logger = logging.getLogger(__name__)

MODEL_ENV = "PRY_CAPTCHA_OCR_MODEL"
DEFAULT_MODEL = Path.home() / ".cache" / "pry" / "models" / "ddddocr" / "common.onnx"
THRESHOLD = 160
MEDIAN_SIZE = 3


def model_path() -> Path:
    """ONNX model file: env override first, then the fleet default."""
    return Path(os.environ.get(MODEL_ENV, DEFAULT_MODEL))


def capability() -> bool:
    """True when onnxruntime is importable and the model file exists."""
    if not model_path().is_file():
        return False
    try:
        import onnxruntime  # noqa: F401
    except ImportError:
        return False
    return True


def _normalize_image(image: bytes | str | None) -> bytes | None:
    """Return raw bytes from bytes, base64 text, data-URL or file path."""
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
            logger.warning("captcha_ocr_path_unreadable path=%s", text)
            return None
    try:
        return base64.b64decode(text) or None
    except (binascii.Error, ValueError):
        logger.warning("captcha_ocr_base64_invalid")
        return None


def preprocess_image(data: bytes) -> Any | None:
    """Grayscale, contrast-stretch, threshold and denoise for OCR."""
    try:
        from PIL import Image, ImageFilter, ImageOps
    except ImportError:
        logger.warning("captcha_ocr_pillow_missing")
        return None
    try:
        img = Image.open(BytesIO(data)).convert("L")
        img = ImageOps.autocontrast(img)
        img = img.point(lambda p: 255 if p > THRESHOLD else 0)
        return img.filter(ImageFilter.MedianFilter(size=MEDIAN_SIZE))
    except (OSError, ValueError) as exc:
        logger.warning("captcha_ocr_preprocess_failed error=%s", exc)
        return None


def _classify(raw: bytes, path: Path) -> str | None:
    """Blocking single-model ONNX classification (ddddocr-compatible)."""
    import numpy as np
    import onnxruntime as ort

    session = ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])
    name = session.get_inputs()[0].name
    array = np.frombuffer(raw, dtype=np.uint8).reshape(1, -1)
    text = session.run(None, {name: array})[0]
    cleaned = "".join(ch for ch in str(text) if ch.isalnum())
    return cleaned or None


async def solve_image(image: bytes | str | None, timeout_s: float = 15.0) -> tuple[str | None, str]:
    """OCR an image CAPTCHA -> (text, reason)."""
    if image is None:
        return None, "not_applicable"
    if not capability():
        return None, f"unavailable.model:{model_path()}"
    raw = _normalize_image(image)
    if raw is None:
        return None, "unsolved"
    try:
        async with asyncio.timeout(timeout_s):
            text = await asyncio.to_thread(_classify, raw, model_path())
    except TimeoutError:
        return None, "timeout"
    except (OSError, RuntimeError, ValueError):
        return None, "failed"
    return (text, "solved") if text else (None, "unsolved")


class ImageOcrProvider(CaptchaProvider):
    """Registry adapter for the free T3 OCR rung (backward compatible)."""

    captcha_type = "image"

    async def solve(self, *, image: bytes | str | None = None, **_: object) -> str | None:
        text, _reason = await solve_image(image)
        return text


register(ImageOcrProvider())
