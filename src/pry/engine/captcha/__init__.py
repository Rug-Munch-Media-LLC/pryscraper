"""Pry — multi-provider CAPTCHA solver package.

Importing this package registers every provider in
:data:`captcha.registry.REGISTRY`:

* ``flaresolverr`` — free JS/Cloudflare lane (no key)
* ``image`` — local OCR (pytesseract / EasyOCR, no network)
* ``recaptcha_v2`` / ``recaptcha_v3`` / ``hcaptcha`` / ``turnstile`` —
  token providers backed by Capsolver / 2captcha-style APIs

Missing token-solver keys are logged loudly at import (startup).
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
import logging

# Importing the provider modules has the side effect of registering them.
from pry.engine.captcha import (  # noqa: F401
    flaresolverr,
    hcaptcha,
    image_ocr,
    recaptcha_v2,
    recaptcha_v3,
    turnstile,
)
from pry.engine.captcha.base import CaptchaProvider
from pry.engine.captcha.keys import CAPTCHA_ENV_FILE, missing_token_keys
from pry.engine.captcha.registry import REGISTRY, get_provider, register

_missing_keys = missing_token_keys()
if _missing_keys:
    logging.getLogger(__name__).warning(
        "captcha_token_providers_unavailable missing=%s keys_file=%s",
        _missing_keys,
        CAPTCHA_ENV_FILE,
    )

__all__ = [
    "CAPTCHA_ENV_FILE",
    "REGISTRY",
    "CaptchaProvider",
    "get_provider",
    "register",
]
