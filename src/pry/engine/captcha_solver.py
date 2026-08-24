"""Pry — Multi-provider CAPTCHA solver facade.

Public entry point for the rest of Pry (and external consumers such as
the signup-automation pipeline)::

    from pry.engine.captcha_solver import solve_captcha

    token = await solve_captcha(
        "recaptcha_v2",
        sitekey="6Le...",
        url="https://example.com/signup",
    )
    text = await solve_captcha("image", image=base64_bytes)

Provider backends live in the :mod:`captcha` package and register
themselves in :data:`captcha.registry.REGISTRY`:

* ``image`` — local OCR (pytesseract / EasyOCR), no network
* ``recaptcha_v2`` / ``recaptcha_v3`` / ``hcaptcha`` / ``turnstile`` —
  2captcha-style API (``PRY_CAPTCHA_2CAPTCHA_API_KEY``) and/or Capsolver
  (``PRY_CAPTCHA_CAPSOLVER_API_KEY``)

Set ``PRY_CAPTCHA_ENABLED=false`` to disable all solving (returns None).
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import logging

import httpx

from captcha import REGISTRY
from pry.core.settings import settings

logger = logging.getLogger(__name__)


async def solve_captcha(
    captcha_type: str,
    sitekey: str | None = None,
    url: str | None = None,
    image: bytes | str | None = None,
) -> str | None:
    """Solve a CAPTCHA via the registered provider for ``captcha_type``.

    Args:
        captcha_type: ``"image"`` | ``"recaptcha_v2"`` | ``"recaptcha_v3"``
            | ``"hcaptcha"`` | ``"turnstile"``.
        sitekey: widget site key required by token providers.
        url: page URL required by token providers.
        image: raw bytes, base64 string, data-URL or file path for the
            ``"image"`` type.

    Returns:
        The solution token/text, or ``None`` when the CAPTCHA cannot be
        solved (unsupported type, missing credentials, OCR backend
        unavailable, upstream failure, or disabled via ``PRY_CAPTCHA_ENABLED``).
    """
    if not settings.captcha_enabled:
        logger.debug("captcha solving disabled (PRY_CAPTCHA_ENABLED=false)")
        return None
    provider = REGISTRY.get(captcha_type)
    if provider is None:
        logger.warning("no captcha provider registered for type %r", captcha_type)
        return None
    try:
        return await provider.solve(sitekey=sitekey, url=url, image=image)
    except (httpx.HTTPError, ValueError, KeyError, OSError) as exc:
        logger.warning("captcha solve failed for %r: %s", captcha_type, exc)
        return None


def available_providers() -> list[str]:
    """Return the sorted list of registered CAPTCHA provider types."""
    return sorted(REGISTRY)
