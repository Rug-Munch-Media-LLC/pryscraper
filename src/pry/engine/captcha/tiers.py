"""Pry — the free CAPTCHA tier table.

Every field here is *evidence*, not opinion. ``cost`` and ``latency_p50_ms``
give the static rank; ``capability`` names the engine that has to exist on this
box; ``closed_for`` names the CAPTCHA classes the rung cannot answer at all;
``requires_residential_ip`` marks a rung that is useless from a datacentre IP
(an audio challenge is). A residential rung is never chosen unless
``PRY_CAPTCHA_ALLOW_RESIDENTIAL`` is explicitly truthy — that is what makes
"no proxy needed by default" a property of the table rather than a promise.

Paid providers are retired by policy. They stay in :data:`RETIRED_PROVIDERS`
with their reason so nobody re-adds one quietly — and nothing else in this
package is allowed to name them.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

import os
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, TypeAlias

from pry.engine.captcha import probes
from pry.engine.captcha.outcomes import UNAVAILABLE_BROWSER, UNAVAILABLE_MODEL

if TYPE_CHECKING:
    from collections.abc import Callable

#: Cheap, offline capability check (``probes.available`` by default).
Probe: TypeAlias = "Callable[[str], bool]"

#: Explicit operator opt-in for rungs that only work from a residential exit.
RESIDENTIAL_ENV = "PRY_CAPTCHA_ALLOW_RESIDENTIAL"
_TRUTHY = frozenset({"1", "true", "yes", "on"})


class CaptchaClass(StrEnum):
    """The CAPTCHA families the ladder distinguishes (``unknown`` when unsure)."""

    RECAPTCHA_V2 = "recaptcha_v2"
    RECAPTCHA_V3 = "recaptcha_v3"
    HCAPTCHA = "hcaptcha"
    TURNSTILE = "turnstile"
    UNKNOWN = "unknown"

    @classmethod
    def parse(cls, value: str | None) -> CaptchaClass:
        """Coerce a raw ``captcha_type`` string, defaulting to ``unknown``."""
        try:
            return cls((value or "").strip().lower())
        except ValueError:
            return cls.UNKNOWN


@dataclass(frozen=True, slots=True)
class Tier:
    """A single free rung: what it is, what it costs, what it needs."""

    tier: str
    kind: str
    label: str
    cost: int
    latency_p50_ms: int
    capability: str
    requires_residential_ip: bool = False
    closed_for: tuple[CaptchaClass, ...] = ()
    missing: str = UNAVAILABLE_MODEL

    @property
    def rank(self) -> float:
        """Static expected work: cost x p50 latency in seconds (lower is better)."""
        return self.cost * self.latency_p50_ms / 1000.0


TIERS: tuple[Tier, ...] = (
    Tier(
        tier="T0",
        kind="http",
        label="clean browser profile",
        cost=1,
        latency_p50_ms=1_000,
        capability="curl_cffi",
    ),
    Tier(
        tier="T1",
        kind="js",
        label="flaresolverr",
        cost=2,
        latency_p50_ms=5_000,
        capability="flaresolverr",
    ),
    Tier(
        tier="T2",
        kind="audio",
        label="audio ASR (faster-whisper)",
        cost=3,
        latency_p50_ms=20_000,
        capability="faster_whisper",
        # Audio challenges are closed on a datacentre IP: require an explicit
        # residential opt-in before this rung may ever be chosen.
        requires_residential_ip=True,
        closed_for=(CaptchaClass.RECAPTCHA_V3,),
    ),
    Tier(
        tier="T3",
        kind="image",
        label="local ONNX OCR",
        cost=3,
        latency_p50_ms=8_000,
        capability="onnx_ocr",
        closed_for=(CaptchaClass.RECAPTCHA_V3, CaptchaClass.TURNSTILE),
    ),
    Tier(
        tier="T4",
        kind="vision",
        label="vision/puzzle (OpenCV)",
        cost=4,
        latency_p50_ms=10_000,
        capability="cv2",
        closed_for=(CaptchaClass.RECAPTCHA_V3, CaptchaClass.TURNSTILE),
    ),
    Tier(
        tier="T5",
        kind="browser",
        label="browser integrity",
        cost=6,
        latency_p50_ms=30_000,
        capability="patchright",
        missing=UNAVAILABLE_BROWSER,
    ),
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


def residential_opt_in() -> bool:
    """True only when the operator explicitly allowed a residential exit."""
    return os.environ.get(RESIDENTIAL_ENV, "").strip().lower() in _TRUTHY


def impossible_reason(
    tier: Tier | str,
    captcha_class: str | CaptchaClass,
    *,
    available: Probe | None = None,
) -> str | None:
    """Why this rung cannot succeed for this class here, or None when it can.

    The three reasons are independent and cheap to check: a closed class, an
    absent engine, and a residential-only rung without the opt-in. Checking
    them costs no budget, which is the point — the ladder can skip instead of
    paying for a guaranteed failure.

    ``available`` is the capability probe (``probes.available`` by default);
    injecting it keeps this predicate deterministic under test.
    """
    candidate = tier if isinstance(tier, Tier) else spec(tier)
    if candidate is None:
        return "unknown.tier"
    wanted = CaptchaClass.parse(str(captcha_class))
    if wanted in candidate.closed_for:
        return f"closed.class {wanted.value}"
    if candidate.requires_residential_ip and not residential_opt_in():
        return f"residential.opt_in {RESIDENTIAL_ENV}"
    probe = available or probes.available
    if not probe(candidate.capability):
        return f"{candidate.missing} {candidate.capability}"
    return None


def is_impossible(
    tier: Tier | str,
    captcha_class: str | CaptchaClass,
    *,
    available: Probe | None = None,
) -> bool:
    """True when the ladder must skip this rung without spending budget."""
    return impossible_reason(tier, captcha_class, available=available) is not None
