"""Pry — the free CAPTCHA tier table.

Every rung is free and local-first. The ladder order is derived from
``cost x latency`` (cheapest expected work first), never written by hand, and
each rung declares the capability it needs so a missing engine is skipped
instantly instead of failing slowly.

Paid providers are retired by policy. They stay in :data:`RETIRED_PROVIDERS`
with their reason so nobody re-adds one quietly — and nothing else in this
package is allowed to name them.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

from dataclasses import dataclass

from pry.engine.captcha.outcomes import UNAVAILABLE_BROWSER, UNAVAILABLE_MODEL


@dataclass(frozen=True, slots=True)
class Tier:
    """A single free rung: what it is, what it costs, what it needs."""

    tier: str
    kind: str
    label: str
    cost: int
    latency_s: int
    capability: str
    missing: str = UNAVAILABLE_MODEL

    @property
    def rank(self) -> int:
        """Expected cost x latency; the ladder sorts on this."""
        return self.cost * self.latency_s


TIERS: tuple[Tier, ...] = (
    Tier("T0", "http", "clean browser profile", 1, 1, "curl_cffi"),
    Tier("T1", "js", "flaresolverr", 2, 5, "flaresolverr"),
    Tier("T2", "audio", "audio ASR (faster-whisper)", 3, 20, "faster_whisper"),
    Tier("T3", "image", "local ONNX OCR", 3, 8, "onnx_ocr"),
    Tier("T4", "vision", "vision/puzzle (OpenCV)", 4, 10, "cv2"),
    Tier("T5", "browser", "browser integrity", 6, 30, "patchright", UNAVAILABLE_BROWSER),
)

#: Retired paid providers -> why. Single source of truth; do not extend.
RETIRED_PROVIDERS: tuple[tuple[str, str], ...] = (
    ("capsolver", "paid — removed by policy"),
    ("2captcha", "paid — removed by policy"),
)


def spec(tier: str) -> Tier | None:
    """Return the tier with id ``tier`` (``T0``..``T5``) or None."""
    return next((t for t in TIERS if t.tier == tier), None)


def ordered_tiers() -> list[Tier]:
    """Tiers sorted by expected cost x latency, table order breaking ties."""
    return sorted(TIERS, key=lambda t: (t.rank, t.tier))
