"""Pry — CAPTCHA provider base class.

Every CAPTCHA backend (image OCR, 2captcha-style token APIs, Capsolver)
implements the :class:`CaptchaProvider` interface and registers itself in
the :data:`captcha.registry.REGISTRY` under its ``captcha_type``.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class CaptchaProvider(ABC):
    """Base class for a single CAPTCHA solving backend."""

    captcha_type: str = ""

    @abstractmethod
    async def solve(self, **kwargs: Any) -> str | None:
        """Attempt to solve a CAPTCHA.

        Returns the solution token / text on success, or ``None`` when the
        challenge cannot be solved (missing credentials, unsupported input,
        OCR backend unavailable, upstream failure, timeout, ...).

        Keyword arguments are provider-specific; the dispatcher passes the
        values it received from :func:`captcha_solver.solve_captcha`
        (``sitekey``, ``url``, ``image``).
        """
