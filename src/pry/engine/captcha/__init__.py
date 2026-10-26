"""Pry — free, tiered CAPTCHA solving.

Rungs, cheapest-first by expected cost x latency (see :mod:`tiers`)::

    T0 clean profile -> T1 FlareSolverr -> T3 ONNX OCR -> T4 vision
    -> T2 audio ASR -> T5 browser integrity

No paid provider is reachable from this package: the retired providers live in
:data:`tiers.RETIRED_PROVIDERS` with their reason and nowhere else.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from pry.engine.captcha import flaresolverr, image_ocr  # noqa: F401  (registry adapters)
from pry.engine.captcha.base import CaptchaProvider
from pry.engine.captcha.ladder import LadderResult, solve_ladder
from pry.engine.captcha.registry import REGISTRY, get_provider, register
from pry.engine.captcha.tiers import RETIRED_PROVIDERS, TIERS, ordered_tiers

__all__ = [
    "REGISTRY",
    "RETIRED_PROVIDERS",
    "TIERS",
    "CaptchaProvider",
    "LadderResult",
    "get_provider",
    "ordered_tiers",
    "register",
    "solve_ladder",
]
