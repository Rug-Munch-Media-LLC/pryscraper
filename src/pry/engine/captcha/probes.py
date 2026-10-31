"""Pry — capability probes for the ladder.

A tier is skipped, not attempted-and-failed, when its engine is absent. Each
probe is a cheap local check (import + file existence); none of them touches
the network.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from collections.abc import Callable


def _probe(capability: str) -> Callable[[], bool] | None:
    """Resolve the capability's probe lazily so imports stay optional."""
    if capability == "curl_cffi":
        from pry.engine.captcha import t0_profile

        return t0_profile.capability
    if capability == "faster_whisper":
        from pry.engine.captcha import audio_asr

        return audio_asr.capability
    if capability == "onnx_ocr":
        from pry.engine.captcha import image_ocr

        return image_ocr.capability
    if capability == "cv2":
        from pry.engine.captcha import vision

        return vision.capability
    if capability == "patchright":
        from pry.engine.captcha import browser_integrity

        return browser_integrity.capability
    return None


def available(capability: str) -> bool:
    """True when the engine behind ``capability`` can run on this box."""
    probe = _probe(capability)
    if probe is None:
        return capability == "flaresolverr"
    try:
        return bool(probe())
    except (ImportError, OSError, RuntimeError, ValueError):
        logger.debug("best-effort fallback", exc_info=True)
        return False
