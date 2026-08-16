"""Pry — CAPTCHA provider registry.

A plain ``dict`` mapping ``captcha_type`` -> provider instance. Providers
register themselves at import time; importing the ``captcha`` package
pulls every provider module in so the registry is fully populated.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from captcha.base import CaptchaProvider

#: Mapping of ``captcha_type`` -> provider instance.
REGISTRY: dict[str, CaptchaProvider] = {}


def register(provider: CaptchaProvider) -> None:
    """Register a provider under its ``captcha_type``."""
    if not provider.captcha_type:
        raise ValueError("provider must declare a non-empty captcha_type")
    REGISTRY[provider.captcha_type] = provider


def get_provider(captcha_type: str) -> CaptchaProvider | None:
    """Return the provider for ``captcha_type`` or None."""
    return REGISTRY.get(captcha_type)
