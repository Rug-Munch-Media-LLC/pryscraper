"""Pry — T4: vision/puzzle rung (slider + rotate), offline.

OpenCV template matching locates the cut-out on the background and the rung
answers with the horizontal gap the caller must drag. Classes it does not
implement (semantic grids, "select all bicycles") are refused with
``unsupported.class`` — never attempted blindly.

cv2 is optional: absent -> ``capability()`` False -> the rung is skipped with
``unavailable.model``.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

import asyncio

SUPPORTED = ("slider", "rotate")


def capability() -> bool:
    """True when OpenCV is importable."""
    try:
        import cv2  # noqa: F401
    except ImportError:
        return False
    return True


def _match(background: bytes, piece: bytes) -> float | None:
    """Blocking template match -> x offset of the best match, if any."""
    import cv2
    import numpy as np

    bg = cv2.imdecode(np.frombuffer(background, np.uint8), cv2.IMREAD_GRAYSCALE)
    pc = cv2.imdecode(np.frombuffer(piece, np.uint8), cv2.IMREAD_GRAYSCALE)
    if bg is None or pc is None or pc.size == 0:
        return None
    result = cv2.matchTemplate(bg, pc, cv2.TM_CCOEFF_NORMED)
    _min_v, max_v, _min_l, max_l = cv2.minMaxLoc(result)
    if max_v < 0.4:
        return None
    return float(max_l[0])


async def solve_puzzle(
    background: bytes | None,
    piece: bytes | None,
    captcha_class: str = "slider",
    timeout_s: float = 10.0,
) -> tuple[float | None, str]:
    """Locate the slider gap -> (x offset, reason).

    ``reason`` is ``solved``, ``unsupported.class``, ``not_applicable``,
    ``unavailable.model``, ``timeout``, ``failed`` or ``unsolved``.
    """
    if captcha_class not in SUPPORTED:
        return None, "unsupported.class"
    if not background or not piece:
        return None, "not_applicable"
    if not capability():
        return None, "unavailable.model"
    try:
        async with asyncio.timeout(timeout_s):
            offset = await asyncio.to_thread(_match, background, piece)
    except TimeoutError:
        return None, "timeout"
    except (OSError, RuntimeError, ValueError):
        return None, "failed"
    return (offset, "solved") if offset is not None else (None, "unsolved")
